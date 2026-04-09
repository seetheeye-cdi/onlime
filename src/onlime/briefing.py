"""Shared meeting briefing context builder and renderer."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from onlime.config import get_settings
from onlime.llm import LLMError, call_llm

logger = structlog.get_logger()

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_WHITESPACE_RE = re.compile(r"\s+")
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class PersonContext:
    """Normalized participant or related person."""

    raw_identifier: str
    display_name: str
    canonical_name: str | None = None
    role_hint: str = ""
    note_path: str | None = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class EvidenceNote:
    """Relevant note pulled from the vault."""

    path: str
    title: str
    category: str
    matched_queries: list[str] = field(default_factory=list)
    snippet: str = ""
    excerpt: str = ""
    score: float = 0.0


@dataclass
class MeetingContextPacket:
    """Grounded context for reconstructing an event."""

    title: str
    time_label: str
    location: str
    description: str
    attendees: list[PersonContext]
    evidence_notes: list[EvidenceNote]


@dataclass
class ReconstructedMeetingBrief:
    """Structured brief returned from the LLM or deterministic fallback."""

    situation: str
    why_now: str
    direct_people: list[dict[str, str]]
    background_people: list[dict[str, str]]
    timeline: list[str]
    advice: list[str]
    questions: list[str]
    confidence: str


async def compose_meeting_brief(
    event: dict[str, Any],
    *,
    vault_search: Any | None = None,
    name_index: Any | None = None,
    people_resolver: Any | None = None,
) -> str:
    """Build context, reconstruct the issue, and render a Telegram-safe brief."""
    context = await build_meeting_context(
        event,
        vault_search=vault_search,
        name_index=name_index,
        people_resolver=people_resolver,
    )
    reconstructed = await reconstruct_meeting_context(context)
    return render_meeting_brief(context, reconstructed)


async def build_meeting_context(
    event: dict[str, Any],
    *,
    vault_search: Any | None = None,
    name_index: Any | None = None,
    people_resolver: Any | None = None,
    max_notes: int = 4,
) -> MeetingContextPacket:
    """Collect normalized people and relevant note excerpts for an event."""
    title = str(event.get("summary", "(제목 없음)")).strip() or "(제목 없음)"
    attendees = await _resolve_attendees(
        event.get("attendees", []),
        name_index=name_index,
        people_resolver=people_resolver,
    )
    evidence = await _collect_evidence(
        event,
        attendees,
        vault_search=vault_search,
        max_notes=max_notes,
    )
    return MeetingContextPacket(
        title=title,
        time_label=_format_event_time(event.get("start", "")),
        location=str(event.get("location", "") or "").strip(),
        description=str(event.get("description", "") or "").strip(),
        attendees=attendees,
        evidence_notes=evidence,
    )


async def reconstruct_meeting_context(
    context: MeetingContextPacket,
) -> ReconstructedMeetingBrief:
    """Use an LLM to reconstruct the event context into an actionable brief."""
    prompt = _build_llm_prompt(context)
    try:
        raw = await call_llm(
            prompt,
            max_tokens=1200,
            caller="meeting_brief_reconstruct",
        )
        parsed = _parse_brief_json(raw)
        if parsed:
            return parsed
    except LLMError:
        logger.warning("briefing.llm_failed", title=context.title)
    except Exception:
        logger.exception("briefing.reconstruct_failed", title=context.title)
    return _fallback_brief(context)


def render_meeting_brief(
    context: MeetingContextPacket,
    brief: ReconstructedMeetingBrief,
) -> str:
    """Render the structured brief into plain Telegram text."""
    lines = [f"{context.time_label} {context.title}".strip(), ""]

    if brief.situation:
        lines.extend(["핵심", brief.situation, ""])
    if brief.why_now:
        lines.extend(["맥락", brief.why_now, ""])

    if brief.direct_people:
        lines.append("직접 관련 인물")
        for idx, person in enumerate(brief.direct_people, start=1):
            role = person.get("role", "").strip()
            relevance = person.get("relevance", "").strip()
            desc = " — ".join(part for part in (role, relevance) if part)
            line = f"{idx}. {person.get('name', '').strip()}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
        lines.append("")

    if brief.background_people:
        lines.append("배경 연결")
        for idx, person in enumerate(brief.background_people, start=1):
            desc = person.get("relevance", "").strip()
            line = f"{idx}. {person.get('name', '').strip()}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
        lines.append("")

    if brief.timeline:
        lines.append("최근 단서")
        for idx, item in enumerate(brief.timeline, start=1):
            lines.append(f"{idx}. {item}")
        lines.append("")

    if brief.advice:
        lines.append("조언")
        for idx, item in enumerate(brief.advice, start=1):
            lines.append(f"{idx}. {item}")
        lines.append("")

    if brief.questions:
        lines.append("확인할 점")
        for idx, item in enumerate(brief.questions, start=1):
            lines.append(f"{idx}. {item}")
        lines.append("")

    sources = [note.title for note in context.evidence_notes[:3] if note.title]
    if sources:
        lines.append(f"근거 노트: {', '.join(sources)}")

    text = "\n".join(_trim_blank_edges(lines))
    if len(text) > 4096:
        text = text[:4090].rstrip() + "\n..."
    return text


async def _resolve_attendees(
    attendees: list[str],
    *,
    name_index: Any | None,
    people_resolver: Any | None,
) -> list[PersonContext]:
    settings = get_settings()
    vault_root = settings.vault.root.expanduser()
    resolved: list[PersonContext] = []
    seen: set[str] = set()

    for attendee in attendees:
        raw = str(attendee or "").strip()
        if not raw:
            continue
        person = _resolve_person(raw, vault_root, name_index, people_resolver)
        dedup_key = person.canonical_name or person.display_name
        dedup_key = dedup_key.strip().lower()
        if dedup_key and dedup_key not in seen:
            seen.add(dedup_key)
            resolved.append(person)

    return resolved


def _resolve_person(
    identifier: str,
    vault_root: Path,
    name_index: Any | None,
    people_resolver: Any | None,
) -> PersonContext:
    candidate_names = _person_candidates(identifier)
    canonical: str | None = None
    if people_resolver:
        for candidate in [identifier, *candidate_names]:
            canonical = people_resolver.resolve(candidate)
            if canonical:
                break
    elif name_index:
        for candidate in candidate_names:
            canonical = name_index.match(candidate)
            if canonical:
                break

    display_name = candidate_names[0] if candidate_names else identifier
    note_path: str | None = None
    summary = ""
    tags: list[str] = []

    if canonical and name_index:
        entity = getattr(name_index, "_by_stem", {}).get(canonical)
        if entity and entity.path.exists():
            try:
                note_path = str(entity.path.relative_to(vault_root))
            except ValueError:
                note_path = None
            tags = _extract_stem_tags(canonical)
            summary = _extract_note_summary(entity.path, max_chars=420)
            display_name = canonical.split("_", 1)[0].strip()

    role_hint = ", ".join(tags[:3])
    return PersonContext(
        raw_identifier=identifier,
        display_name=display_name,
        canonical_name=canonical,
        role_hint=role_hint,
        note_path=note_path,
        summary=summary,
        tags=tags,
    )


async def _collect_evidence(
    event: dict[str, Any],
    attendees: list[PersonContext],
    *,
    vault_search: Any | None,
    max_notes: int,
) -> list[EvidenceNote]:
    if vault_search is None:
        return []

    queries = _build_queries(event, attendees)
    by_path: dict[str, EvidenceNote] = {}

    for idx, query in enumerate(queries):
        try:
            results = await vault_search.search(query, limit=5)
        except Exception:
            logger.warning("briefing.search_failed", query=query[:80])
            results = []
        _merge_search_results(by_path, results, query, event, attendees)
        if idx < 2:
            for category in ("Inbox", "Meeting", "Recording", "Telegram"):
                try:
                    cat_results = await vault_search.search(query, limit=2, category=category)
                except Exception:
                    logger.warning(
                        "briefing.search_failed",
                        query=query[:80],
                        category=category,
                    )
                    cat_results = []
                _merge_search_results(by_path, cat_results, query, event, attendees)

    ranked = sorted(by_path.values(), key=lambda item: (-item.score, item.title))
    for note in ranked[:max_notes]:
        note.excerpt = _read_note_excerpt(note.path, max_chars=1600)
    return ranked[:max_notes]


def _build_queries(event: dict[str, Any], attendees: list[PersonContext]) -> list[str]:
    title = str(event.get("summary", "")).strip()
    description = str(event.get("description", "")).strip()
    names = [person.display_name for person in attendees if person.display_name]

    raw_queries = [title]
    if description:
        raw_queries.append(f"{title} {description[:80]}")
    for name in names[:4]:
        raw_queries.append(f"{title} {name}".strip())
    if len(names) >= 2:
        raw_queries.append(" ".join(names[:2]))
        raw_queries.append(f"{title} {' '.join(names[:2])}".strip())
    if len(names) >= 3:
        raw_queries.append(" ".join(names[:3]))

    queries: list[str] = []
    seen: set[str] = set()
    for query in raw_queries:
        clean = _WHITESPACE_RE.sub(" ", query).strip()
        if clean and clean not in seen:
            seen.add(clean)
            queries.append(clean)
    return queries[:6]


def _merge_search_results(
    by_path: dict[str, EvidenceNote],
    results: list[dict[str, Any]],
    query: str,
    event: dict[str, Any],
    attendees: list[PersonContext],
) -> None:
    title = str(event.get("summary", "")).strip().lower()
    attendee_terms = {
        person.display_name.lower()
        for person in attendees
        if person.display_name
    }
    summary_terms = {
        token.lower()
        for token in re.split(r"[\s/|,()]+", title)
        if len(token) >= 2
    }

    for result in results:
        path = str(result.get("path", "")).strip()
        if not path:
            continue
        note = by_path.get(path)
        if note is None:
            note = EvidenceNote(
                path=path,
                title=str(result.get("title", "")).strip() or Path(path).stem,
                category=_path_category(path),
            )
            by_path[path] = note
        if query not in note.matched_queries:
            note.matched_queries.append(query)

        snippet = str(result.get("snippet", "") or "")
        if snippet and not note.snippet:
            note.snippet = snippet

        text = f"{note.title} {snippet} {path}".lower()
        score = 1.0
        score += len(note.matched_queries) * 2.0
        if any(term in text for term in summary_terms):
            score += 2.0
        score += sum(1.5 for term in attendee_terms if term and term in text)
        if note.category in {"Meeting", "Recording", "Inbox", "Telegram"}:
            score += 2.5
        if _DATE_RE.search(note.title) or _DATE_RE.search(path):
            score += 0.5
        note.score += score


def _build_llm_prompt(context: MeetingContextPacket) -> str:
    attendee_lines = []
    for idx, attendee in enumerate(context.attendees, start=1):
        parts = [attendee.display_name]
        if attendee.role_hint:
            parts.append(attendee.role_hint)
        if attendee.summary:
            parts.append(attendee.summary)
        attendee_lines.append(f"{idx}. {' -- '.join(parts)}")

    evidence_blocks = []
    for idx, note in enumerate(context.evidence_notes, start=1):
        evidence_blocks.append(
            "\n".join([
                f"[Evidence {idx}]",
                f"title: {note.title}",
                f"path: {note.path}",
                f"category: {note.category}",
                f"matched_queries: {', '.join(note.matched_queries)}",
                f"snippet: {note.snippet}",
                f"excerpt:\n{note.excerpt}",
            ])
        )

    return (
        "당신은 개인 비서형 chief-of-staff입니다.\n"
        "다가오는 미팅의 현재 사건 맥락을 재구성하고, 바로 행동 가능한 조언을 만들어야 합니다.\n"
        "역사적으로 연결된 사람과 이번 사건의 직접 당사자를 구분하세요.\n"
        "직접 증거가 약하면 추정이라고 명시하고 confidence를 낮추세요.\n"
        "raw snippet을 복사하지 말고, 사건을 재구성해 짧게 요약하세요.\n"
        "반드시 JSON 객체만 반환하세요.\n"
        "스키마:\n"
        "{\n"
        '  "situation": "한두 문장",\n'
        '  "why_now": "왜 지금 중요한지",\n'
        '  "direct_people": [{"name": "", "role": "", "relevance": ""}],\n'
        '  "background_people": [{"name": "", "relevance": ""}],\n'
        '  "timeline": ["최근 맥락 1", "최근 맥락 2"],\n'
        '  "advice": ["조언 1", "조언 2", "조언 3"],\n'
        '  "questions": ["확인할 점 1", "확인할 점 2"],\n'
        '  "confidence": "low|medium|high"\n'
        "}\n\n"
        f"미팅명: {context.title}\n"
        f"시간: {context.time_label}\n"
        f"장소: {context.location or '(없음)'}\n"
        f"설명: {context.description or '(없음)'}\n\n"
        "참석자:\n"
        f"{chr(10).join(attendee_lines) if attendee_lines else '(없음)'}\n\n"
        "근거 자료:\n"
        f"{chr(10).join(evidence_blocks) if evidence_blocks else '(없음)'}\n"
    )


def _parse_brief_json(raw: str) -> ReconstructedMeetingBrief | None:
    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    return ReconstructedMeetingBrief(
        situation=str(data.get("situation", "")).strip(),
        why_now=str(data.get("why_now", "")).strip(),
        direct_people=_normalize_people_list(data.get("direct_people")),
        background_people=_normalize_people_list(data.get("background_people")),
        timeline=_normalize_str_list(data.get("timeline")),
        advice=_normalize_str_list(data.get("advice")),
        questions=_normalize_str_list(data.get("questions")),
        confidence=str(data.get("confidence", "")).strip() or "low",
    )


def _fallback_brief(context: MeetingContextPacket) -> ReconstructedMeetingBrief:
    attendee_people = []
    for attendee in context.attendees:
        attendee_people.append({
            "name": attendee.display_name,
            "role": attendee.role_hint,
            "relevance": "현재 일정 참석자",
        })

    timeline = []
    for note in context.evidence_notes[:3]:
        clue = note.excerpt.splitlines()[0].strip() if note.excerpt else note.title
        if clue:
            timeline.append(f"{note.title}: {clue[:120]}")

    advice = []
    if context.evidence_notes:
        advice.append("근거 노트 2~3개를 먼저 확인하고, 이번 안건의 직접 당사자를 분리해서 보세요.")
    if len(context.attendees) >= 2:
        names = ", ".join(person.display_name for person in context.attendees[:3])
        advice.append(f"{names} 사이의 현재 쟁점과 최소 합의선을 먼저 정리하세요.")
    advice.append("미팅 전에 확인 질문 2개와 후속 커뮤니케이션 문구 1개를 준비하세요.")

    return ReconstructedMeetingBrief(
        situation="관련 노트와 최근 기록을 바탕으로 이번 미팅의 핵심 쟁점을 정리해야 합니다.",
        why_now="다가오는 일정 전에 직접 당사자, 쟁점, 합의 목표를 분리해 두는 것이 필요합니다.",
        direct_people=attendee_people,
        background_people=[],
        timeline=timeline,
        advice=advice[:3],
        questions=[
            "이번 안건의 직접 당사자는 누구인가",
            "이번 미팅에서 꼭 정해야 하는 최소 합의선은 무엇인가",
        ],
        confidence="low",
    )


def _normalize_people_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        normalized.append({
            "name": name,
            "role": str(item.get("role", "")).strip(),
            "relevance": str(item.get("relevance", "")).strip(),
        })
    return normalized


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result[:4]


def _path_category(path: str) -> str:
    parts = Path(path).parts
    if len(parts) >= 2 and parts[0] in {"0.SYSTEM", "1.INPUT", "2.OUTPUT"}:
        return parts[1]
    return parts[0] if parts else ""


def _format_event_time(start_str: str) -> str:
    try:
        return datetime.fromisoformat(start_str).strftime("%H:%M")
    except (TypeError, ValueError):
        return str(start_str or "").strip()


def _person_candidates(identifier: str) -> list[str]:
    raw = unicodedata.normalize("NFC", identifier.strip())
    local = raw.split("@", 1)[0]
    local = re.sub(r"[._-]+", " ", local).strip()
    candidates = [candidate for candidate in [local, raw] if candidate]
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        lowered = candidate.lower()
        if lowered not in seen:
            seen.add(lowered)
            result.append(candidate)
    return result


def _extract_stem_tags(stem: str) -> list[str]:
    if "_" not in stem:
        return []
    suffix = stem.split("_", 1)[1]
    return [part.strip() for part in re.split(r"[_/,]", suffix) if part.strip()]


def _read_note_excerpt(rel_path: str, *, max_chars: int) -> str:
    settings = get_settings()
    vault_root = settings.vault.root.expanduser()
    path = (vault_root / rel_path).resolve()
    try:
        path.relative_to(vault_root.resolve())
    except ValueError:
        return ""
    if not path.exists():
        return ""
    return _extract_note_summary(path, max_chars=max_chars)


def _extract_note_summary(path: Path, *, max_chars: int) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    body = _FRONTMATTER_RE.sub("", raw, count=1)
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("#"):
            continue
        cleaned = stripped.lstrip("-*0123456789. ").strip()
        if cleaned:
            lines.append(cleaned)
        if sum(len(item) for item in lines) >= max_chars:
            break
    summary = "\n".join(lines)
    summary = summary[:max_chars].strip()
    return summary


def _trim_blank_edges(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines
