"""Background task: sync Claude Code sessions to daily notes."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import structlog

from onlime.config import get_settings
from onlime.llm import LLMError, call_llm
from onlime.maintenance.base import BackgroundTask
from onlime.outputs.vault import atomic_write, render_daily_note

logger = structlog.get_logger()

_CLAUDE_DIR = Path.home() / ".claude"
_SESSION_STATS = _CLAUDE_DIR / ".session-stats.json"
_PROJECTS_DIR = _CLAUDE_DIR / "projects"

# Sessions inactive for this long are considered finished
_STALE_SECONDS = 15 * 60  # 15 minutes

_SUMMARY_PROMPT = (
    "다음은 Claude Code 세션의 대화 내용입니다. 한국어로 2~3줄 이내로 요약해주세요.\n"
    "포함할 내용:\n"
    "- 무엇을 했는지 (작업 내용)\n"
    "- 어떤 파일을 수정/생성했는지 (주요 파일만)\n"
    "- 핵심 결정사항\n"
    "부연 설명 없이 요약만 출력하세요.\n\n{text}"
)

_MAX_CONVERSATION_CHARS = 6000

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS claude_sessions (
    session_id   TEXT PRIMARY KEY,
    project      TEXT NOT NULL,
    started_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    message_count INTEGER DEFAULT 0,
    synced_at    TEXT,
    summary      TEXT
);
"""


def _project_label(dir_name: str) -> str:
    """Extract human-readable project name from Claude projects dir name.

    '-Users-cdiseetheeye-Desktop-Onlime' → 'Onlime'
    """
    parts = dir_name.strip("-").split("-")
    # Skip common path prefixes
    skip = {"Users", "cdiseetheeye", "Desktop", "Documents", "Home", "home"}
    meaningful = [p for p in parts if p and p not in skip]
    return meaningful[-1] if meaningful else dir_name


def _find_session_project(session_id: str) -> tuple[str, Path | None]:
    """Find which project directory contains a session JSONL.

    Returns (project_dir_name, jsonl_path) or ("unknown", None).
    """
    if not _PROJECTS_DIR.exists():
        return "unknown", None
    for proj_dir in _PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        jsonl = proj_dir / f"{session_id}.jsonl"
        if jsonl.exists():
            return proj_dir.name, jsonl
    return "unknown", None


def _extract_conversation(jsonl_path: Path) -> list[dict]:
    """Extract user/assistant text from session JSONL.

    Excludes: progress, file-history-snapshot, queue-operation, system,
    thinking blocks, tool_use blocks, tool_result user messages.
    """
    messages: list[dict] = []
    try:
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                entry_type = entry.get("type", "")

                if entry_type == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    # Skip tool_result arrays
                    if isinstance(content, list):
                        continue
                    if isinstance(content, str) and content.strip():
                        messages.append({"role": "user", "text": content.strip()})

                elif entry_type == "assistant":
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        texts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                texts.append(block["text"])
                        if texts:
                            messages.append({"role": "assistant", "text": "\n".join(texts)})
    except Exception:
        logger.warning("claude_sync.jsonl_parse_error", path=str(jsonl_path))
    return messages


def _conversation_to_text(messages: list[dict], max_chars: int = _MAX_CONVERSATION_CHARS) -> str:
    """Convert extracted messages to plain text, truncating if needed."""
    parts: list[str] = []
    for m in messages:
        prefix = "User" if m["role"] == "user" else "Assistant"
        parts.append(f"[{prefix}] {m['text']}")

    full = "\n\n".join(parts)
    if len(full) <= max_chars:
        return full

    # Keep first 40% + last 60% for better context
    head_len = int(max_chars * 0.4)
    tail_len = max_chars - head_len - 20  # room for separator
    return full[:head_len] + "\n\n[...중략...]\n\n" + full[-tail_len:]


class ClaudeSessionSync(BackgroundTask):
    """Sync Claude Code session summaries to daily notes."""

    name = "claude_sync"

    def __init__(self, interval_seconds: int, db: object) -> None:
        super().__init__(interval_seconds)
        self._db = db  # aiosqlite.Connection

    async def _ensure_schema(self) -> None:
        await self._db.execute(_SCHEMA_DDL)
        await self._db.commit()

    def _load_session_stats(self) -> dict[str, dict]:
        """Load session-stats.json → {session_id: info}."""
        if not _SESSION_STATS.exists():
            return {}
        try:
            with _SESSION_STATS.open(encoding="utf-8") as f:
                data = json.load(f)
            return data.get("sessions", {})
        except Exception:
            logger.warning("claude_sync.stats_load_error")
            return {}

    async def _find_changed_sessions(self, stats: dict[str, dict]) -> dict[str, dict]:
        """Filter to sessions that are new or updated since last sync."""
        now_ts = int(time.time())
        changed: dict[str, dict] = {}

        for sid, info in stats.items():
            updated_at = info.get("updated_at", 0)
            started_at = info.get("started_at", 0)

            # Skip sessions still active (updated within 15 min)
            if now_ts - updated_at < _STALE_SECONDS:
                continue

            # Skip tiny sessions (fewer than 2 tool calls → likely accidental)
            if info.get("total_calls", 0) < 2:
                continue

            # Check DB for existing record
            cursor = await self._db.execute(
                "SELECT updated_at, synced_at FROM claude_sessions WHERE session_id = ?",
                (sid,),
            )
            row = await cursor.fetchone()

            if row is None:
                # New session
                changed[sid] = info
            elif row["synced_at"] is None or row["updated_at"] < updated_at:
                # Updated since last sync
                changed[sid] = info

        return changed

    async def _summarize_session(self, conversation_text: str) -> str:
        """Summarize session conversation using Claude."""
        prompt = _SUMMARY_PROMPT.format(text=conversation_text)
        try:
            return await call_llm(prompt, max_tokens=512, caller="claude_sync")
        except LLMError:
            logger.warning("claude_sync.summarize_failed")
            return conversation_text[:200] + "..."

    async def _process_session(self, session_id: str, info: dict) -> None:
        """Process a single session: parse, summarize, record."""
        started_at = info.get("started_at", 0)
        updated_at = info.get("updated_at", 0)

        project_dir, jsonl_path = _find_session_project(session_id)
        if jsonl_path is None:
            logger.debug("claude_sync.jsonl_not_found", session_id=session_id)
            # Still record to avoid re-checking
            await self._upsert_session(session_id, project_dir, started_at, updated_at, 0, "")
            return

        messages = _extract_conversation(jsonl_path)
        if not messages:
            await self._upsert_session(session_id, project_dir, started_at, updated_at, 0, "")
            return

        conversation_text = _conversation_to_text(messages)
        summary = await self._summarize_session(conversation_text)

        await self._upsert_session(
            session_id, project_dir, started_at, updated_at, len(messages), summary,
        )

        # Append to daily note
        session_dt = datetime.fromtimestamp(started_at)
        project_name = _project_label(project_dir)
        time_str = session_dt.strftime("%H:%M")
        entry_line = f"- {time_str} **{project_name}** — {summary}"

        self._append_to_daily(session_dt, entry_line, session_id)

        logger.info(
            "claude_sync.processed",
            session_id=session_id[:8],
            project=project_name,
            messages=len(messages),
        )

    async def _upsert_session(
        self,
        session_id: str,
        project: str,
        started_at: int,
        updated_at: int,
        message_count: int,
        summary: str,
    ) -> None:
        now = datetime.now().isoformat()
        await self._db.execute(
            """INSERT INTO claude_sessions (session_id, project, started_at, updated_at, message_count, synced_at, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id)
               DO UPDATE SET updated_at=?, message_count=?, synced_at=?, summary=?""",
            (session_id, project, started_at, updated_at, message_count, now, summary,
             updated_at, message_count, now, summary),
        )
        await self._db.commit()

    def _append_to_daily(self, session_dt: datetime, entry_line: str, session_id: str) -> None:
        """Append entry to daily note's '## Claude Code' section."""
        settings = get_settings()
        vault_root = settings.vault.root.expanduser()
        daily_dir = vault_root / settings.vault.daily_dir

        date_str = session_dt.strftime("%Y-%m-%d")
        daily_path = daily_dir / f"{date_str}.md"

        if daily_path.exists():
            content = daily_path.read_text(encoding="utf-8")
        else:
            content = render_daily_note(date_str)

        # Dedup by session_id (first 8 chars embedded as HTML comment)
        dedup_marker = f"<!-- cc:{session_id[:8]} -->"
        if dedup_marker in content:
            logger.debug("claude_sync.already_recorded", session_id=session_id[:8])
            return

        tagged_line = f"{entry_line} {dedup_marker}"

        section_header = "## Claude Code"
        if section_header not in content:
            # Insert section before --- separator at end, or append
            content = content.rstrip() + f"\n\n{section_header}\n\n{tagged_line}\n"
        else:
            lines = content.split("\n")
            new_lines: list[str] = []
            inserted = False
            i = 0
            while i < len(lines):
                new_lines.append(lines[i])
                if lines[i].strip() == section_header and not inserted:
                    i += 1
                    # Collect existing entries until next ## or --- or end
                    while i < len(lines) and not lines[i].startswith("## ") and lines[i].strip() != "---":
                        new_lines.append(lines[i])
                        i += 1
                    new_lines.append(tagged_line)
                    inserted = True
                    continue
                i += 1
            content = "\n".join(new_lines)

        atomic_write(daily_path, content)

    async def run_once(self) -> None:
        await self._ensure_schema()
        stats = self._load_session_stats()
        if not stats:
            return

        changed = await self._find_changed_sessions(stats)
        if not changed:
            return

        processed = 0
        for session_id, info in changed.items():
            try:
                await self._process_session(session_id, info)
                processed += 1
            except Exception:
                logger.exception("claude_sync.session_error", session_id=session_id[:8])

        if processed:
            logger.info("claude_sync.cycle", processed=processed, total=len(stats))
