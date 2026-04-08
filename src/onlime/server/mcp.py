"""MCP server exposing Onlime tools to Claude Desktop/Code.

Run: python -m onlime.server.mcp
Transport: stdio (standard for Claude Desktop/Code)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from onlime import setup_logging
from onlime.config import get_settings

logger = structlog.get_logger()

server = Server("onlime")

# Lazy-initialized shared resources
_vault_search: Any = None
_hybrid_search: Any = None
_db_conn: Any = None


async def _ensure_search() -> Any:
    """Lazily initialize search engines (FTS5 + hybrid)."""
    global _vault_search, _hybrid_search, _db_conn

    if _hybrid_search is not None:
        return _hybrid_search

    import aiosqlite

    from onlime.search.fts import VaultSearch
    from onlime.search.hybrid import HybridSearch
    from onlime.search.semantic import SemanticSearch

    settings = get_settings()
    db_path = settings.state.db_path

    # Read-only connection to shared WAL database
    _db_conn = await aiosqlite.connect(str(db_path))
    await _db_conn.execute("PRAGMA journal_mode=WAL")

    _vault_search = VaultSearch(_db_conn)
    await _vault_search.ensure_schema()

    semantic = None
    if settings.search.use_semantic:
        semantic = SemanticSearch()
        if await semantic.check_available():
            logger.info("mcp.semantic_search_available")
        else:
            semantic = None
            logger.info("mcp.semantic_search_unavailable")

    _hybrid_search = HybridSearch(_vault_search, semantic)
    return _hybrid_search


def _vault_root() -> Path:
    return get_settings().vault.root.expanduser()


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_vault",
            description="Obsidian vault에서 노트를 검색합니다. 키워드/의미 기반 하이브리드 검색.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 키워드"},
                    "limit": {"type": "integer", "description": "최대 결과 수 (기본: 10)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="read_note",
            description="Vault 노트의 전체 내용을 읽습니다. search_vault로 찾은 path를 전달하세요.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "vault 내 상대 경로 (예: 1.INPUT/Media/제목.md)"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="get_events",
            description="Google Calendar에서 일정을 조회합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "시작 날짜 (YYYY-MM-DD). 기본: 오늘"},
                    "end_date": {"type": "string", "description": "종료 날짜 (YYYY-MM-DD). 기본: start_date 다음 날"},
                },
            },
        ),
        Tool(
            name="create_event",
            description="Google Calendar에 새 일정을 만듭니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "일정 제목"},
                    "start_datetime": {"type": "string", "description": "시작 시간 (YYYY-MM-DDTHH:MM)"},
                    "end_datetime": {"type": "string", "description": "종료 시간 (YYYY-MM-DDTHH:MM). 기본: 시작 1시간 후"},
                    "description": {"type": "string", "description": "일정 설명"},
                    "location": {"type": "string", "description": "장소"},
                },
                "required": ["summary", "start_datetime"],
            },
        ),
        Tool(
            name="save_note",
            description="Obsidian vault Inbox에 메모를 저장합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "메모 내용 (마크다운)"},
                    "title": {"type": "string", "description": "파일 제목 (확장자 불필요)"},
                },
                "required": ["content", "title"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "search_vault":
            result = await _handle_search(arguments)
        elif name == "read_note":
            result = await _handle_read(arguments)
        elif name == "get_events":
            result = await _handle_get_events(arguments)
        elif name == "create_event":
            result = await _handle_create_event(arguments)
        elif name == "save_note":
            result = await _handle_save_note(arguments)
        else:
            result = f"알 수 없는 도구: {name}"
    except Exception as exc:
        logger.exception("mcp.tool_error", tool=name)
        result = f"오류: {exc}"

    return [TextContent(type="text", text=result)]


async def _handle_search(params: dict[str, Any]) -> str:
    search = await _ensure_search()
    query = params.get("query", "")
    limit = params.get("limit", 10)

    results = await search.search(query, limit=limit)
    if not results:
        return f"'{query}'에 대한 검색 결과가 없습니다."

    lines = [f"검색 결과 ({len(results)}건):"]
    for r in results:
        line = f"- **{r['title']}** — `{r['path']}`"
        if r.get("snippet"):
            line += f"\n  {r['snippet']}"
        if r.get("rrf_score"):
            line += f" (score: {r['rrf_score']:.4f})"
        lines.append(line)
    return "\n".join(lines)


async def _handle_read(params: dict[str, Any]) -> str:
    rel_path = params.get("path", "")
    if not rel_path:
        return "path 파라미터가 필요합니다."

    full_path = _vault_root() / rel_path
    if not full_path.exists():
        return f"파일을 찾을 수 없습니다: {rel_path}"

    # Security: ensure path is within vault
    try:
        full_path.resolve().relative_to(_vault_root().resolve())
    except ValueError:
        return "잘못된 경로입니다."

    try:
        content = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"파일 읽기 오류: {exc}"

    # Truncate very large files
    if len(content) > 50_000:
        content = content[:50_000] + "\n\n... (이하 생략, 전체 길이: {})".format(len(content))

    return content


async def _handle_get_events(params: dict[str, Any]) -> str:
    settings = get_settings()
    token_path = Path(settings.gcal.token_file).expanduser()
    if not token_path.exists():
        return "Google Calendar 미연동. 'python scripts/setup_gcal.py' 실행 필요."

    from onlime.connectors.gcal import format_events_text, get_events

    today = datetime.now().date()
    start_str = params.get("start_date")
    end_str = params.get("end_date")

    start = datetime.fromisoformat(start_str) if start_str else datetime.combine(today, datetime.min.time())
    end = datetime.fromisoformat(end_str) if end_str else start + timedelta(days=1)

    events = await get_events(start, end)
    header = f"{start.strftime('%Y-%m-%d')} 일정 ({len(events)}건):\n"
    return header + format_events_text(events)


async def _handle_create_event(params: dict[str, Any]) -> str:
    settings = get_settings()
    token_path = Path(settings.gcal.token_file).expanduser()
    if not token_path.exists():
        return "Google Calendar 미연동. 'python scripts/setup_gcal.py' 실행 필요."

    from onlime.connectors.gcal import create_event

    summary = params["summary"]
    start = datetime.fromisoformat(params["start_datetime"])
    end = datetime.fromisoformat(params["end_datetime"]) if params.get("end_datetime") else None
    description = params.get("description", "")
    location = params.get("location", "")

    await create_event(
        summary=summary, start=start, end=end,
        description=description, location=location,
    )
    return f"일정 생성 완료: {summary} ({start.strftime('%Y-%m-%d %H:%M')})"


async def _handle_save_note(params: dict[str, Any]) -> str:
    content = params["content"]
    title = params.get("title", datetime.now().strftime("%Y%m%d_%H%M%S"))

    # Sanitize filename
    safe_title = "".join(c for c in title if c not in r'?":*|<>\/')
    safe_title = safe_title.strip(". ")
    if not safe_title:
        safe_title = datetime.now().strftime("%Y%m%d_%H%M%S")

    inbox_dir = _vault_root() / get_settings().vault.inbox_dir
    inbox_dir.mkdir(parents=True, exist_ok=True)

    file_path = inbox_dir / f"{safe_title}.md"
    # Avoid overwrite
    counter = 2
    while file_path.exists():
        file_path = inbox_dir / f"{safe_title} ({counter}).md"
        counter += 1

    file_path.write_text(content, encoding="utf-8")
    rel = file_path.relative_to(_vault_root())
    return f"저장 완료: {rel}"


def main() -> None:
    """Entry point for onlime-mcp command."""
    setup_logging("INFO")

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            logger.info("mcp.server_starting")
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
