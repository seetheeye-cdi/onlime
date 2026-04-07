"""SQLite WAL state store for event tracking and connector cursors."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite
import structlog

logger = structlog.get_logger()

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    connector_name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    payload TEXT NOT NULL,
    obsidian_path TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    UNIQUE(source_type, source_id)
);

CREATE TABLE IF NOT EXISTS connector_state (
    connector_name TEXT PRIMARY KEY,
    cursor_value TEXT,
    last_sync_at TEXT,
    last_success_at TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wikilink TEXT NOT NULL,
    aliases TEXT,
    kakao_name TEXT,
    telegram_username TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wikilink TEXT NOT NULL,
    hashtags TEXT,
    active INTEGER DEFAULT 1,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    input_path TEXT,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 5,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_name TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    checked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_type, created_at);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source_path);
"""


class StateStore:
    """Async SQLite state store with WAL mode."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("state.opened", db=str(self.db_path))

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("StateStore not opened")
        return self._db

    # --- Events ---

    async def save_event(
        self,
        event_id: str,
        source_type: str,
        source_id: str,
        connector_name: str,
        payload: dict,
    ) -> bool:
        """Save event, returns False if duplicate."""
        now = datetime.now().isoformat()
        try:
            await self.db.execute(
                """INSERT INTO events (id, source_type, source_id, connector_name, payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event_id, source_type, source_id, connector_name, json.dumps(payload, ensure_ascii=False), now),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def update_event_status(self, event_id: str, status: str, obsidian_path: str | None = None, error: str | None = None) -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            """UPDATE events SET status=?, processed_at=?, obsidian_path=?, error=? WHERE id=?""",
            (status, now, obsidian_path, error, event_id),
        )
        await self.db.commit()

    async def get_pending_events(self, limit: int = 50) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM events WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Connector State ---

    async def get_cursor(self, connector_name: str) -> str | None:
        cursor = await self.db.execute(
            "SELECT cursor_value FROM connector_state WHERE connector_name=?",
            (connector_name,),
        )
        row = await cursor.fetchone()
        return row["cursor_value"] if row else None

    async def set_cursor(self, connector_name: str, cursor_value: str) -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            """INSERT INTO connector_state (connector_name, cursor_value, last_sync_at, last_success_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(connector_name)
               DO UPDATE SET cursor_value=?, last_sync_at=?, last_success_at=?, consecutive_failures=0""",
            (connector_name, cursor_value, now, now, cursor_value, now, now),
        )
        await self.db.commit()

    async def record_failure(self, connector_name: str) -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            """INSERT INTO connector_state (connector_name, last_sync_at, consecutive_failures)
               VALUES (?, ?, 1)
               ON CONFLICT(connector_name)
               DO UPDATE SET last_sync_at=?, consecutive_failures=consecutive_failures+1""",
            (connector_name, now, now),
        )
        await self.db.commit()

    # --- Task Queue ---

    async def enqueue_task(self, task_type: str, input_path: str, priority: int = 5) -> int:
        now = datetime.now().isoformat()
        cursor = await self.db.execute(
            "INSERT INTO task_queue (task_type, input_path, priority, created_at) VALUES (?, ?, ?, ?)",
            (task_type, input_path, priority, now),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def dequeue_task(self) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM task_queue WHERE status='pending' ORDER BY priority ASC, id ASC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return None
        task = dict(row)
        await self.db.execute("UPDATE task_queue SET status='processing' WHERE id=?", (task["id"],))
        await self.db.commit()
        return task

    async def complete_task(self, task_id: int, result: dict | None = None, error: str | None = None) -> None:
        now = datetime.now().isoformat()
        status = "failed" if error else "done"
        await self.db.execute(
            "UPDATE task_queue SET status=?, completed_at=?, result=?, error=? WHERE id=?",
            (status, now, json.dumps(result) if result else None, error, task_id),
        )
        await self.db.commit()

    # --- Health ---

    async def record_health(self, connector_name: str, status: str, message: str = "") -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            "INSERT INTO health_checks (connector_name, status, message, checked_at) VALUES (?, ?, ?, ?)",
            (connector_name, status, message, now),
        )
        await self.db.commit()
