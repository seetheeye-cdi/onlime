"""People note auto-section writer.

Renders Onlime-maintained stats between <!-- onlime-auto-start --> and
<!-- onlime-auto-end --> markers in People vault files. Never touches content
outside the markers. If markers missing, appends them at end of file.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from onlime.processors.people_crm import PersonRecord

logger = structlog.get_logger()

START_MARKER = "<!-- onlime-auto-start -->"
END_MARKER = "<!-- onlime-auto-end -->"

# Regex matches the block including markers, DOTALL for multi-line content between them.
_BLOCK_RE = re.compile(
    re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
    re.DOTALL,
)


def render_people_profile_section(
    record: "PersonRecord",
    pending_actions: list[dict[str, Any]] | None = None,
) -> str:
    """Render the auto-section markdown block (without markers)."""
    lines: list[str] = []
    lines.append("## Onlime 자동 기록")
    lines.append(f"*최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    # Identity
    if record.aliases or record.kakao_name or record.telegram_username:
        lines.append("### 식별자")
        if record.aliases:
            lines.append(f"- 별명: {', '.join(record.aliases)}")
        if record.kakao_name:
            lines.append(f"- 카카오: {record.kakao_name}")
        if record.telegram_username:
            lines.append(f"- 텔레그램: @{record.telegram_username}")
        lines.append("")

    # Interaction stats
    lines.append("### 상호작용 통계")
    lines.append(f"- 총 상호작용: {record.interaction_count}회")
    if record.first_seen:
        lines.append(f"- 첫 기록: {_fmt_date(record.first_seen)}")
    if record.last_seen:
        lines.append(f"- 최근 기록: {_fmt_date(record.last_seen)}")
    if record.sources:
        source_str = ", ".join(
            f"{k} {v}회" for k, v in sorted(record.sources.items(), key=lambda x: -x[1])
        )
        lines.append(f"- 소스: {source_str}")
    lines.append("")

    # Recent relation kinds
    if record.recent_relations:
        lines.append("### 최근 접점")
        for rel in record.recent_relations[:10]:
            lines.append(f"- {rel}")
        lines.append("")

    # Pending actions where this person is owner
    if pending_actions:
        lines.append("### 대기 중인 할 일")
        for action in pending_actions[:10]:
            task = action.get("task_text", "")
            state = action.get("state", "open")
            due = action.get("due_at")
            line = f"- [{state}] {task}"
            if due:
                line += f" (due {_fmt_date(due)})"
            lines.append(line)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _fmt_date(iso: str) -> str:
    """Format ISO timestamp to YYYY-MM-DD, gracefully handles non-ISO strings."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(iso)[:10] if iso else ""


def upsert_auto_section(
    people_note_path: Path,
    rendered_md: str,
) -> bool:
    """Read the People note, replace (or append) the auto-section block.

    Returns True if file was modified, False if content unchanged.
    Never touches content outside the marker block.
    Creates the file if it doesn't exist (with only the auto block).
    """
    block_with_markers = f"{START_MARKER}\n{rendered_md.strip()}\n{END_MARKER}"

    if not people_note_path.exists():
        logger.info("people_profile.creating_new", path=str(people_note_path))
        people_note_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(people_note_path, block_with_markers + "\n")
        return True

    try:
        content = people_note_path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("people_profile.read_failed", path=str(people_note_path))
        return False

    if _BLOCK_RE.search(content):
        new_content = _BLOCK_RE.sub(block_with_markers, content, count=1)
    else:
        # Append block at end, preserving existing content
        if not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n" + block_with_markers + "\n"

    if new_content == content:
        return False

    _atomic_write(people_note_path, new_content)
    return True


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


async def refresh_people_profiles(
    crm: Any,  # PeopleCRM
    vault_root: Path,
    *,
    modified_since: datetime | None = None,
    limit: int = 200,
) -> int:
    """Iterate People vault files modified since `modified_since`, re-render auto-sections.

    Returns number of files updated.
    If modified_since is None, does a full pass (expensive — use only on first run).
    """
    people_dirs = [
        vault_root / "1.INPUT" / "People",
        vault_root / "2.OUTPUT" / "People" / "Active",
        vault_root / "2.OUTPUT" / "People" / "Network",
        vault_root / "2.OUTPUT" / "People" / "Reference",
    ]
    updated = 0
    for d in people_dirs:
        if not d.exists():
            continue
        for md_path in d.glob("*.md"):
            if updated >= limit:
                return updated
            if modified_since is not None:
                try:
                    mtime = datetime.fromtimestamp(md_path.stat().st_mtime)
                    if mtime < modified_since:
                        continue
                except OSError:
                    continue
            stem = md_path.stem
            try:
                record = await crm.get_person_profile(stem)
                if not record:
                    continue
                pending = await crm.get_pending_actions_for_person(record.canonical_name)
                rendered = render_people_profile_section(record, pending_actions=pending)
                if upsert_auto_section(md_path, rendered):
                    updated += 1
            except Exception:
                logger.exception("people_profile.refresh_failed", path=str(md_path))
    logger.info("people_profile.refresh_done", updated=updated)
    return updated
