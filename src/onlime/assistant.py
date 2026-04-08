"""Claude tool-use AI assistant for Telegram conversations."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog

from onlime.config import get_settings
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()

_MAX_TOOL_ROUNDS = 5
_MAX_HISTORY = 20

# Per-chat conversation memory: chat_id → messages list
_conversations: dict[int, list[dict[str, Any]]] = {}

_SYSTEM_PROMPT = (
    "당신은 Onlime AI 비서입니다. 사용자의 Obsidian vault와 Google Calendar를 관리합니다.\n"
    "한국어로 간결하게 답변하세요.\n"
    "도구를 사용해 일정 확인, 노트 검색, 일정 생성, 메모 저장을 수행합니다.\n"
    "현재 시각: {now} (Asia/Seoul)\n"
)

_TOOLS = [
    {
        "name": "search_vault",
        "description": "Obsidian vault에서 노트를 검색합니다. 키워드로 관련 문서를 찾습니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색 키워드",
                },
                "limit": {
                    "type": "integer",
                    "description": "최대 결과 수 (기본: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_events",
        "description": "Google Calendar에서 일정을 조회합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "시작 날짜 (YYYY-MM-DD). 기본: 오늘",
                },
                "end_date": {
                    "type": "string",
                    "description": "종료 날짜 (YYYY-MM-DD). 기본: start_date 다음 날",
                },
            },
        },
    },
    {
        "name": "create_event",
        "description": "Google Calendar에 새 일정을 만듭니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "일정 제목",
                },
                "start_datetime": {
                    "type": "string",
                    "description": "시작 시간 (YYYY-MM-DDTHH:MM 형식)",
                },
                "end_datetime": {
                    "type": "string",
                    "description": "종료 시간 (YYYY-MM-DDTHH:MM 형식). 기본: 시작 1시간 후",
                },
                "description": {
                    "type": "string",
                    "description": "일정 설명",
                },
                "location": {
                    "type": "string",
                    "description": "장소",
                },
            },
            "required": ["summary", "start_datetime"],
        },
    },
    {
        "name": "save_note",
        "description": "Obsidian vault에 빠른 메모를 저장합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "메모 내용",
                },
                "title": {
                    "type": "string",
                    "description": "메모 제목 (생략 시 자동 생성)",
                },
            },
            "required": ["content"],
        },
    },
]


async def handle_assistant_message(
    chat_id: int,
    text: str,
    vault_search: Any | None = None,
    engine_queue: asyncio.Queue | None = None,
) -> str:
    """Process a natural-language message through Claude tool-use.

    Returns the assistant's text response.
    """
    # Append user message to history
    history = _conversations.setdefault(chat_id, [])
    history.append({"role": "user", "content": text})

    # Trim history
    if len(history) > _MAX_HISTORY:
        _conversations[chat_id] = history[-_MAX_HISTORY:]
        history = _conversations[chat_id]

    # Build system prompt with current time
    now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    system = _SYSTEM_PROMPT.format(now=now)

    # Call Claude with tools (multi-turn loop)
    for _round in range(_MAX_TOOL_ROUNDS):
        response = await _call_claude(system, history)

        stop_reason = response.stop_reason
        content_blocks = response.content

        if stop_reason == "end_turn":
            # Extract text response
            text_parts = [b.text for b in content_blocks if b.type == "text"]
            reply = "\n".join(text_parts) if text_parts else ""
            history.append({"role": "assistant", "content": content_blocks})
            return reply

        if stop_reason == "tool_use":
            # Execute tool calls
            history.append({"role": "assistant", "content": content_blocks})
            tool_results = []
            for block in content_blocks:
                if block.type == "tool_use":
                    result = await _execute_tool(
                        block.name,
                        block.input,
                        vault_search=vault_search,
                        engine_queue=engine_queue,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            history.append({"role": "user", "content": tool_results})
            continue

        # Unknown stop reason — break
        text_parts = [b.text for b in content_blocks if b.type == "text"]
        reply = "\n".join(text_parts) if text_parts else "응답을 생성할 수 없습니다."
        history.append({"role": "assistant", "content": content_blocks})
        return reply

    return "도구 호출 한도에 도달했습니다. 다시 시도해주세요."


def clear_history(chat_id: int) -> None:
    """Clear conversation history for a chat."""
    _conversations.pop(chat_id, None)


async def _call_claude(
    system: str,
    messages: list[dict[str, Any]],
) -> Any:
    """Call Claude API with tool-use."""
    import anthropic

    settings = get_settings()
    api_key = get_secret_or_env("claude-api-key", "ANTHROPIC_API_KEY")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=settings.llm.claude.model,
        max_tokens=1024,
        system=system,
        tools=_TOOLS,
        messages=messages,
    )
    return response


async def _execute_tool(
    name: str,
    params: dict[str, Any],
    vault_search: Any | None = None,
    engine_queue: asyncio.Queue | None = None,
) -> str:
    """Execute a tool call and return the result as a string."""
    try:
        if name == "search_vault":
            return await _tool_search_vault(params, vault_search)
        elif name == "get_events":
            return await _tool_get_events(params)
        elif name == "create_event":
            return await _tool_create_event(params)
        elif name == "save_note":
            return await _tool_save_note(params, engine_queue)
        else:
            return f"알 수 없는 도구: {name}"
    except Exception as exc:
        logger.exception("assistant.tool_error", tool=name)
        return f"도구 실행 오류: {exc}"


async def _tool_search_vault(
    params: dict[str, Any],
    vault_search: Any | None,
) -> str:
    """Search vault via hybrid search (FTS5 + semantic)."""
    if vault_search is None:
        return "검색 엔진이 초기화되지 않았습니다."

    query = params.get("query", "")
    limit = params.get("limit", 5)
    results = await vault_search.search(query, limit=limit)

    if not results:
        return f"'{query}'에 대한 검색 결과가 없습니다."

    lines = [f"검색 결과 ({len(results)}건):"]
    for r in results:
        lines.append(f"- [[{r['title']}]] ({r['path']})")
        if r.get("snippet"):
            lines.append(f"  {r['snippet']}")
    return "\n".join(lines)


async def _tool_get_events(params: dict[str, Any]) -> str:
    """Fetch Google Calendar events."""
    from pathlib import Path

    from onlime.config import get_settings

    # Check if GCal is set up
    settings = get_settings()
    token_path = Path(settings.gcal.token_file).expanduser()
    if not token_path.exists():
        return "Google Calendar가 아직 연동되지 않았습니다. 'python scripts/setup_gcal.py'를 실행해주세요."

    from onlime.connectors.gcal import format_events_text, get_events

    today = datetime.now().date()
    start_str = params.get("start_date")
    end_str = params.get("end_date")

    if start_str:
        start = datetime.fromisoformat(start_str)
    else:
        start = datetime.combine(today, datetime.min.time())

    if end_str:
        end = datetime.fromisoformat(end_str)
    else:
        end = start + timedelta(days=1)

    events = await get_events(start, end)
    date_label = start.strftime("%Y-%m-%d")
    header = f"{date_label} 일정 ({len(events)}건):\n"
    return header + format_events_text(events)


async def _tool_create_event(params: dict[str, Any]) -> str:
    """Create a Google Calendar event."""
    from pathlib import Path

    from onlime.config import get_settings

    settings = get_settings()
    token_path = Path(settings.gcal.token_file).expanduser()
    if not token_path.exists():
        return "Google Calendar가 아직 연동되지 않았습니다. 'python scripts/setup_gcal.py'를 실행해주세요."

    from onlime.connectors.gcal import create_event

    summary = params["summary"]
    start = datetime.fromisoformat(params["start_datetime"])
    end = datetime.fromisoformat(params["end_datetime"]) if params.get("end_datetime") else None
    description = params.get("description", "")
    location = params.get("location", "")

    event = await create_event(
        summary=summary,
        start=start,
        end=end,
        description=description,
        location=location,
    )
    time_str = start.strftime("%Y-%m-%d %H:%M")
    return f"일정 생성 완료: {summary} ({time_str})"


async def _tool_save_note(
    params: dict[str, Any],
    engine_queue: asyncio.Queue | None,
) -> str:
    """Save a quick note to vault via the engine pipeline."""
    from onlime.models import ContentType, SourceType
    from onlime.processors.categorizer import extract_hashtags

    content = params["content"]
    title = params.get("title", "")

    if engine_queue:
        event_dict = {
            "id": str(uuid.uuid4()),
            "source": SourceType.TELEGRAM.value,
            "content_type": ContentType.MESSAGE.value,
            "raw_content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "telegram_user_id": 0,
                "telegram_username": "assistant",
                "hashtags": extract_hashtags(content),
                "assistant_title": title,
            },
        }
        await engine_queue.put(event_dict)
        return f"메모 저장 요청됨: {title or content[:30]}"

    return "엔진 큐가 사용 불가합니다."
