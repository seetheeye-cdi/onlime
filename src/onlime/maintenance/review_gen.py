"""Generate weekly and monthly review notes from daily notes."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from onlime.config import get_settings
from onlime.llm import call_llm
from onlime.outputs.vault import atomic_write
from onlime.processors.name_resolver import VaultNameIndex, resolve_wikilinks
from onlime.processors.summarizer import _SENTENCE_RULE, _WIKILINK_RULE, format_one_sentence_per_line

if TYPE_CHECKING:
    from onlime.personal_context import PersonalContextStore

logger = structlog.get_logger()

# Section header patterns in daily notes
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _extract_sections(content: str) -> dict[str, str]:
    """Extract named sections from a daily note's markdown.

    Returns a dict like {"==잡서": "...", "일정": "...", "회고": "..."}.
    """
    sections: dict[str, str] = {}
    lines = content.split("\n")
    current_header: str | None = None
    current_body: list[str] = []

    for line in lines:
        m = _SECTION_RE.match(line)
        if m:
            if current_header is not None:
                sections[current_header] = "\n".join(current_body).strip()
            current_header = m.group(1).strip()
            current_body = []
        elif current_header is not None:
            # Stop at --- separator (section boundary)
            if line.strip() == "---":
                sections[current_header] = "\n".join(current_body).strip()
                current_header = None
                current_body = []
            else:
                current_body.append(line)

    if current_header is not None:
        sections[current_header] = "\n".join(current_body).strip()

    return sections


def _collect_daily_notes(
    vault_root: Path, start_date: date, end_date: date,
) -> dict[str, dict[str, str]]:
    """Read daily notes in date range, return {date_str: {section: text}}.

    end_date is exclusive.
    """
    settings = get_settings()
    daily_dir = vault_root.expanduser() / settings.vault.daily_dir
    result: dict[str, dict[str, str]] = {}

    d = start_date
    while d < end_date:
        date_str = d.isoformat()
        path = daily_dir / f"{date_str}.md"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            sections = _extract_sections(content)
            result[date_str] = sections
        d += timedelta(days=1)

    return result


def _has_enough_content(daily_notes: dict[str, dict[str, str]], min_entries: int = 2) -> bool:
    """Check if there's enough scratch content to justify a review."""
    count = 0
    for sections in daily_notes.values():
        scratch = sections.get("==잡서", "").strip()
        if scratch:
            count += 1
    return count >= min_entries


def _build_context_text(daily_notes: dict[str, dict[str, str]]) -> str:
    """Build a combined text from daily notes for LLM input."""
    parts: list[str] = []
    for date_str in sorted(daily_notes.keys()):
        sections = daily_notes[date_str]
        parts.append(f"### {date_str}")
        for key in ("==잡서", "일정", "회고", "리뷰"):
            text = sections.get(key, "").strip()
            if text:
                parts.append(f"**{key}**:\n{text}")
        parts.append("")
    return "\n".join(parts)


def _week_label(d: date) -> str:
    """ISO week label like '2026-W15'."""
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month_label(year: int, month: int) -> str:
    """Month label like '2026-04'."""
    return f"{year}-{month:02d}"


async def generate_weekly_review(
    vault_root: Path,
    week_start: date,
    name_index: VaultNameIndex | None = None,
    personal_context_store: PersonalContextStore | None = None,
) -> Path | None:
    """Generate a weekly review note from Mon-Sun daily notes.

    Args:
        vault_root: Obsidian vault root path.
        week_start: Monday of the target week.
        name_index: Optional VaultNameIndex for wikilink resolution.

    Returns:
        Path of the created file, or None if skipped.
    """
    vault_root = vault_root.expanduser()
    settings = get_settings()
    weekly_dir = vault_root / settings.vault.weekly_dir
    weekly_dir.mkdir(parents=True, exist_ok=True)

    week_end = week_start + timedelta(days=7)  # exclusive
    label = _week_label(week_start)
    out_path = weekly_dir / f"{label}.md"

    if out_path.exists():
        logger.info("review.weekly_exists", week=label)
        return None

    daily_notes = _collect_daily_notes(vault_root, week_start, week_end)
    if not _has_enough_content(daily_notes):
        logger.info("review.weekly_skipped", week=label, reason="insufficient content")
        return None

    context = _build_context_text(daily_notes)

    personal_context_suffix = ""
    settings = get_settings()
    flags = getattr(settings, "feature_flags", None)
    if flags and getattr(flags, "personal_context", False) and personal_context_store is not None:
        personal_context_suffix = personal_context_store.build_system_suffix(
            max_tokens=120, categories=["project", "ontology", "preference"]
        )

    # Generate AI summary
    summary_prompt = (
        "다음은 한 주간의 일일 노트입니다. "
        "이번 주에 있었던 주요 활동, 프로젝트 진행, 배운 점을 3~5문장으로 요약해주세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{context}"
        + personal_context_suffix
    )
    ai_summary = await call_llm(summary_prompt, caller="weekly_review")
    ai_summary = format_one_sentence_per_line(ai_summary)

    # Generate AI reflection
    reflection_prompt = (
        "다음은 한 주간의 일일 노트입니다. "
        "이번 주를 돌아보며 잘한 점, 개선할 점, 다음 주에 집중할 것을 각 1~2문장으로 정리해주세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{context}"
        + personal_context_suffix
    )
    ai_reflection = await call_llm(reflection_prompt, caller="weekly_review")
    ai_reflection = format_one_sentence_per_line(ai_reflection)

    # Resolve wikilinks
    if name_index:
        ai_summary = resolve_wikilinks(ai_summary, name_index)
        ai_reflection = resolve_wikilinks(ai_reflection, name_index)

    # Build daily entries for template
    daily_entries: dict[str, dict[str, str]] = {}
    d = week_start
    while d < week_end:
        ds = d.isoformat()
        sections = daily_notes.get(ds, {})
        daily_entries[ds] = {"scratch": sections.get("==잡서", "").strip()}
        d += timedelta(days=1)

    # Navigation
    prev_week = _week_label(week_start - timedelta(weeks=1))
    next_week = _week_label(week_start + timedelta(weeks=1))

    # Render template
    from onlime.outputs.vault import _get_template_env
    env = _get_template_env()
    tmpl = env.get_template("weekly_note.md.j2")
    rendered = tmpl.render(
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        week_label=label,
        start_date=week_start.isoformat(),
        end_date=(week_end - timedelta(days=1)).isoformat(),
        prev_week=prev_week,
        next_week=next_week,
        ai_summary=ai_summary,
        ai_reflection=ai_reflection,
        daily_entries=daily_entries,
    )

    atomic_write(out_path, rendered)
    logger.info("review.weekly_generated", week=label, path=str(out_path))
    return out_path


async def generate_monthly_review(
    vault_root: Path,
    year: int,
    month: int,
    name_index: VaultNameIndex | None = None,
    personal_context_store: PersonalContextStore | None = None,
) -> Path | None:
    """Generate a monthly review note.

    Args:
        vault_root: Obsidian vault root path.
        year: Target year.
        month: Target month (1-12).
        name_index: Optional VaultNameIndex for wikilink resolution.

    Returns:
        Path of the created file, or None if skipped.
    """
    vault_root = vault_root.expanduser()
    settings = get_settings()
    monthly_dir = vault_root / settings.vault.monthly_dir
    monthly_dir.mkdir(parents=True, exist_ok=True)

    label = _month_label(year, month)
    out_path = monthly_dir / f"{label}.md"

    if out_path.exists():
        logger.info("review.monthly_exists", month=label)
        return None

    # Date range for the month
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    daily_notes = _collect_daily_notes(vault_root, start, end)
    if not _has_enough_content(daily_notes, min_entries=3):
        logger.info("review.monthly_skipped", month=label, reason="insufficient content")
        return None

    context = _build_context_text(daily_notes)
    # Truncate for very active months
    if len(context) > 15000:
        context = context[:15000] + "\n\n... (이하 생략)"

    personal_context_suffix = ""
    settings = get_settings()
    flags = getattr(settings, "feature_flags", None)
    if flags and getattr(flags, "personal_context", False) and personal_context_store is not None:
        personal_context_suffix = personal_context_store.build_system_suffix(
            max_tokens=120, categories=["project", "ontology", "preference"]
        )

    # Generate AI summary
    summary_prompt = (
        "다음은 한 달간의 일일 노트입니다. "
        "이번 달의 주요 활동, 프로젝트 진행, 핵심 성과를 5~8문장으로 요약해주세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{context}"
        + personal_context_suffix
    )
    ai_summary = await call_llm(summary_prompt, caller="monthly_review")
    ai_summary = format_one_sentence_per_line(ai_summary)

    # Generate AI reflection
    reflection_prompt = (
        "다음은 한 달간의 일일 노트입니다. "
        "이번 달을 돌아보며 가장 큰 성취, 아쉬운 점, 다음 달 목표를 각 1~2문장으로 정리해주세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{context}"
        + personal_context_suffix
    )
    ai_reflection = await call_llm(reflection_prompt, caller="monthly_review")
    ai_reflection = format_one_sentence_per_line(ai_reflection)

    # Resolve wikilinks
    if name_index:
        ai_summary = resolve_wikilinks(ai_summary, name_index)
        ai_reflection = resolve_wikilinks(ai_reflection, name_index)

    # Find existing weekly reviews for this month
    weekly_dir = vault_root / settings.vault.weekly_dir
    weekly_reviews: list[str] = []
    if weekly_dir.exists():
        for f in sorted(weekly_dir.glob(f"{year}-W*.md")):
            # Check if the week falls within this month
            stem = f.stem  # e.g. "2026-W15"
            try:
                parts = stem.split("-W")
                w_year = int(parts[0])
                w_num = int(parts[1])
                # Monday of that ISO week
                monday = date.fromisocalendar(w_year, w_num, 1)
                if start <= monday < end:
                    weekly_reviews.append(stem)
            except (ValueError, IndexError):
                continue

    # Navigation
    if month == 1:
        prev_m = _month_label(year - 1, 12)
    else:
        prev_m = _month_label(year, month - 1)
    if month == 12:
        next_m = _month_label(year + 1, 1)
    else:
        next_m = _month_label(year, month + 1)

    # Render template
    from onlime.outputs.vault import _get_template_env
    env = _get_template_env()
    tmpl = env.get_template("monthly_note.md.j2")
    rendered = tmpl.render(
        created=datetime.now().strftime("%Y-%m-%d %H:%M"),
        month_label=label,
        start_date=start.isoformat(),
        end_date=(end - timedelta(days=1)).isoformat(),
        prev_month=prev_m,
        next_month=next_m,
        ai_summary=ai_summary,
        ai_reflection=ai_reflection,
        weekly_reviews=weekly_reviews,
    )

    atomic_write(out_path, rendered)
    logger.info("review.monthly_generated", month=label, path=str(out_path))
    return out_path
