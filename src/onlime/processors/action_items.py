"""LLM-based action item extraction from transcripts and messages."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from onlime.llm import call_llm

logger = structlog.get_logger()

_MIN_TEXT_LENGTH = 200

_PROMPT = (
    "다음 텍스트에서 액션 아이템(할 일, 약속, 결정사항)을 추출해주세요.\n"
    "JSON 배열로 반환. 각 항목: {{\"task\": \"...\", \"owner\": \"...\", \"due_date\": \"...\"}}\n"
    "- task: 구체적인 할 일 (한국어, 동사형으로 끝나게)\n"
    "- owner: 담당자 이름 (알 수 없으면 빈 문자열)\n"
    "- due_date: 기한 (YYYY-MM-DD 형식, 알 수 없으면 빈 문자열)\n"
    "액션 아이템이 없으면 빈 배열 [] 을 반환하세요.\n"
    "{context}\n"
    "텍스트:\n{text}"
)


def _build_context(meeting_context: dict[str, Any] | None) -> str:
    """Build optional context string for the prompt."""
    if not meeting_context:
        return ""
    parts: list[str] = []
    if meeting_context.get("attendees"):
        parts.append(f"참석자: {', '.join(meeting_context['attendees'])}")
    if meeting_context.get("project"):
        parts.append(f"프로젝트: {meeting_context['project']}")
    if parts:
        return "참고 정보:\n" + "\n".join(parts) + "\n"
    return ""


def _parse_action_items(raw: str) -> list[dict[str, str]]:
    """Parse JSON array of action items from LLM response."""
    # Try to find JSON array in the response
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            items = json.loads(match.group(0))
            if isinstance(items, list):
                result: list[dict[str, str]] = []
                for item in items:
                    if isinstance(item, dict) and item.get("task"):
                        result.append({
                            "task": str(item.get("task", "")).strip(),
                            "owner": str(item.get("owner", "")).strip(),
                            "due_date": str(item.get("due_date", "")).strip(),
                        })
                return result
        except json.JSONDecodeError:
            pass

    logger.warning("action_items.parse_failed", raw_length=len(raw))
    return []


async def extract_action_items(
    text: str,
    source_note: str = "",
    meeting_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Extract action items from text using LLM.

    Returns list of dicts: {task, owner, due_date, source_note}.
    """
    if len(text) < _MIN_TEXT_LENGTH:
        return []

    context = _build_context(meeting_context)
    prompt = _PROMPT.format(context=context, text=text[:8000])

    raw = await call_llm(prompt, max_tokens=512, caller="action_items")
    items = _parse_action_items(raw)

    # Attach source_note to each item
    for item in items:
        item["source_note"] = source_note

    logger.info("action_items.extracted", count=len(items), source=source_note[:40])
    return items


def format_action_items_markdown(items: list[dict[str, str]]) -> str:
    """Format action items for vault note body."""
    lines: list[str] = []
    for item in items:
        line = f"- [ ] {item['task']}"
        if item.get("owner"):
            line += f" (담당: {item['owner']})"
        if item.get("due_date"):
            line += f" (기한: {item['due_date']})"
        lines.append(line)
    return "\n".join(lines)


def format_action_items_daily(items: list[dict[str, str]]) -> str:
    """Format action items for daily note's todo section."""
    lines: list[str] = []
    for item in items:
        line = f"- [ ] {item['task']}"
        if item.get("source_note"):
            line += f" -- [[{item['source_note']}]]"
        lines.append(line)
    return "\n".join(lines)
