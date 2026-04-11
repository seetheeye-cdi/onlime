"""SQLite WAL state store for event tracking and connector cursors."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

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

CREATE TABLE IF NOT EXISTS telegram_group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    user_name TEXT NOT NULL,
    message_text TEXT NOT NULL,
    message_ts TEXT NOT NULL,
    digested INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_type, created_at);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source_path);
CREATE INDEX IF NOT EXISTS idx_tg_group_digest
    ON telegram_group_messages(group_id, digested, message_ts);

CREATE TABLE IF NOT EXISTS people_timeline (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_name   TEXT    NOT NULL,
    event_id      TEXT,
    source_path   TEXT,
    timestamp     TEXT    NOT NULL,
    source_type   TEXT    NOT NULL,
    relation_kind TEXT,
    context_excerpt TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_people_timeline_person ON people_timeline(person_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_people_timeline_event  ON people_timeline(event_id);
CREATE INDEX IF NOT EXISTS idx_people_timeline_source ON people_timeline(source_path);

CREATE TABLE IF NOT EXISTS action_lifecycle (
    task_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_text        TEXT    NOT NULL,
    state            TEXT    NOT NULL DEFAULT 'open'
        CHECK(state IN ('open','in_progress','waiting_on_other','blocked','completed','cancelled','escalated')),
    owner            TEXT,
    priority         TEXT    NOT NULL DEFAULT 'normal'
        CHECK(priority IN ('urgent','high','normal','low')),
    source_event_id  TEXT,
    source_note_path TEXT,
    due_at           TEXT,
    escalated_at     TEXT,
    completed_at     TEXT,
    cancelled_at     TEXT,
    last_nudged_at   TEXT,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    notes            TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_action_state_due ON action_lifecycle(state, due_at);
CREATE INDEX IF NOT EXISTS idx_action_owner     ON action_lifecycle(owner, state);
CREATE INDEX IF NOT EXISTS idx_action_source    ON action_lifecycle(source_note_path);

CREATE TABLE IF NOT EXISTS synthesis_cache (
    id                  TEXT    PRIMARY KEY,
    topic               TEXT    NOT NULL,
    scope_json          TEXT    NOT NULL,
    output_md           TEXT    NOT NULL,
    source_paths_json   TEXT    NOT NULL,
    source_count        INTEGER NOT NULL,
    token_count_input   INTEGER,
    token_count_output  INTEGER,
    model               TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_used_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    hit_count           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_synth_topic ON synthesis_cache(topic, created_at DESC);
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

    async def get_event(self, event_id: str) -> dict | None:
        """Fetch a single event by ID."""
        cursor = await self.db.execute("SELECT * FROM events WHERE id=?", (event_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_retryable_events(self, max_retries: int = 3, max_age_hours: int = 24) -> list[dict]:
        """Get failed events eligible for retry."""
        cursor = await self.db.execute(
            """SELECT id, payload, retry_count FROM events
               WHERE status = 'failed'
                 AND retry_count < ?
                 AND created_at > datetime('now', ?)
               ORDER BY created_at""",
            (max_retries, f"-{max_age_hours} hours"),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def increment_retry(self, event_id: str) -> None:
        """Mark a failed event as pending for retry and bump retry_count."""
        await self.db.execute(
            "UPDATE events SET status='pending', retry_count=retry_count+1 WHERE id=?",
            (event_id,),
        )
        await self.db.commit()

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

    # --- Action Items ---

    async def get_action_items(self, status: str = "pending", limit: int = 20) -> list[dict]:
        """Fetch action_item tasks from task_queue."""
        cursor = await self.db.execute(
            """SELECT id, input_path, status, result, created_at
               FROM task_queue
               WHERE task_type = 'action_item' AND status = ?
               ORDER BY created_at DESC LIMIT ?""",
            (status, limit),
        )
        rows = await cursor.fetchall()
        items: list[dict] = []
        for r in rows:
            row = dict(r)
            if row.get("result"):
                try:
                    row["data"] = json.loads(row["result"])
                except (json.JSONDecodeError, TypeError):
                    row["data"] = {}
            else:
                row["data"] = {}
            items.append(row)
        return items

    async def complete_action_item(self, task_id: int) -> bool:
        """Mark an action_item as done."""
        cursor = await self.db.execute(
            "SELECT id FROM task_queue WHERE id = ? AND task_type = 'action_item'",
            (task_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return False
        now = datetime.now().isoformat()
        await self.db.execute(
            "UPDATE task_queue SET status = 'done', completed_at = ? WHERE id = ?",
            (now, task_id),
        )
        await self.db.commit()
        return True

    # --- Health ---

    async def record_health(self, connector_name: str, status: str, message: str = "") -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            "INSERT INTO health_checks (connector_name, status, message, checked_at) VALUES (?, ?, ?, ?)",
            (connector_name, status, message, now),
        )
        await self.db.commit()

    # --- Telegram Group Messages ---

    async def save_group_message(
        self,
        group_id: int,
        group_name: str,
        user_name: str,
        text: str,
        ts: str,
    ) -> None:
        now = datetime.now().isoformat()
        await self.db.execute(
            """INSERT INTO telegram_group_messages
               (group_id, group_name, user_name, message_text, message_ts, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (group_id, group_name, user_name, text, ts, now),
        )
        await self.db.commit()

    async def get_undigested_messages(self, group_id: int) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT id, group_id, group_name, user_name, message_text, message_ts
               FROM telegram_group_messages
               WHERE group_id = ? AND digested = 0
               ORDER BY message_ts ASC""",
            (group_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_messages_digested(self, group_id: int, before_ts: str) -> None:
        await self.db.execute(
            """UPDATE telegram_group_messages
               SET digested = 1
               WHERE group_id = ? AND digested = 0 AND message_ts <= ?""",
            (group_id, before_ts),
        )
        await self.db.commit()

    # --- People Timeline ---

    async def insert_timeline_event(
        self,
        *,
        person_name: str,
        event_id: str | None,
        source_path: str | None,
        timestamp: str,
        source_type: str,
        relation_kind: str | None = None,
        context_excerpt: str | None = None,
    ) -> int:
        # Pass created_at explicitly so local-time is recorded regardless of
        # the table's CREATE DEFAULT (existing dev DBs may still have the old
        # UTC-based default from the initial schema).
        now_local = datetime.now().isoformat()
        cursor = await self.db.execute(
            """INSERT INTO people_timeline
               (person_name, event_id, source_path, timestamp, source_type,
                relation_kind, context_excerpt, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (person_name, event_id, source_path, timestamp, source_type,
             relation_kind, context_excerpt, now_local),
        )
        await self.db.commit()
        logger.debug("timeline.inserted", person=person_name, source_type=source_type)
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_person_timeline(
        self,
        person_name: str,
        *,
        limit: int = 50,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        if since:
            cursor = await self.db.execute(
                """SELECT * FROM people_timeline
                   WHERE person_name = ? AND timestamp >= ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (person_name, since, limit),
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM people_timeline
                   WHERE person_name = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (person_name, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_person_stats(self, person_name: str) -> dict[str, Any]:
        cursor = await self.db.execute(
            """SELECT
                   MIN(timestamp) AS first_seen,
                   MAX(timestamp) AS last_seen,
                   COUNT(*)       AS interaction_count,
                   source_type
               FROM people_timeline
               WHERE person_name = ?
               GROUP BY source_type""",
            (person_name,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return {"first_seen": None, "last_seen": None, "interaction_count": 0, "sources": {}}
        first_seen = min(r["first_seen"] for r in rows)
        last_seen = max(r["last_seen"] for r in rows)
        total = sum(r["interaction_count"] for r in rows)
        sources = {r["source_type"]: r["interaction_count"] for r in rows}
        return {"first_seen": first_seen, "last_seen": last_seen, "interaction_count": total, "sources": sources}

    # --- Action Lifecycle ---

    async def insert_action(
        self,
        *,
        task_text: str,
        owner: str | None = None,
        priority: str = "normal",
        source_event_id: str | None = None,
        source_note_path: str | None = None,
        due_at: str | None = None,
        notes: str | None = None,
    ) -> int:
        # Pass created_at/updated_at explicitly so local-time is recorded
        # regardless of the table's CREATE DEFAULT (existing dev DBs may
        # still have the old UTC-based default from the initial schema).
        now_local = datetime.now().isoformat()
        cursor = await self.db.execute(
            """INSERT INTO action_lifecycle
               (task_text, owner, priority, source_event_id, source_note_path,
                due_at, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_text, owner, priority, source_event_id, source_note_path,
             due_at, notes, now_local, now_local),
        )
        await self.db.commit()
        logger.debug("action.inserted", task_id=cursor.lastrowid, priority=priority)
        return cursor.lastrowid  # type: ignore[return-value]

    async def transition_action(
        self,
        task_id: int,
        *,
        new_state: str,
        expected_prior: str,
    ) -> bool:
        # Build timestamp columns for terminal states (use localtime to stay
        # consistent with datetime.now().isoformat() elsewhere in the codebase)
        extra_cols = ""
        if new_state == "completed":
            extra_cols = ", completed_at = datetime('now', 'localtime')"
        elif new_state == "cancelled":
            extra_cols = ", cancelled_at = datetime('now', 'localtime')"
        elif new_state == "escalated":
            extra_cols = ", escalated_at = datetime('now', 'localtime')"

        cursor = await self.db.execute(
            f"UPDATE action_lifecycle SET state = ?, "
            f"updated_at = datetime('now', 'localtime'){extra_cols} "
            "WHERE task_id = ? AND state = ?",
            (new_state, task_id, expected_prior),
        )
        await self.db.commit()
        updated = cursor.rowcount > 0
        if not updated:
            logger.debug("action.transition_noop", task_id=task_id, expected=expected_prior, new=new_state)
        return updated

    async def get_actions_by_state(
        self,
        state: str,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if owner:
            cursor = await self.db.execute(
                """SELECT * FROM action_lifecycle
                   WHERE state = ? AND owner = ?
                   ORDER BY due_at ASC, created_at ASC LIMIT ?""",
                (state, owner, limit),
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM action_lifecycle
                   WHERE state = ?
                   ORDER BY due_at ASC, created_at ASC LIMIT ?""",
                (state, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_overdue_actions(
        self,
        *,
        hours: int = 72,
        owner: str | None = None,
    ) -> list[dict[str, Any]]:
        if owner:
            cursor = await self.db.execute(
                """SELECT * FROM action_lifecycle
                   WHERE state = 'open'
                     AND due_at IS NOT NULL
                     AND due_at < datetime('now', 'localtime', ?)
                     AND owner = ?
                   ORDER BY due_at ASC""",
                (f"-{hours} hours", owner),
            )
        else:
            cursor = await self.db.execute(
                """SELECT * FROM action_lifecycle
                   WHERE state = 'open'
                     AND due_at IS NOT NULL
                     AND due_at < datetime('now', 'localtime', ?)
                   ORDER BY due_at ASC""",
                (f"-{hours} hours",),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Synthesis Cache ---

    async def get_synthesis_cache(self, cache_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM synthesis_cache WHERE id = ?",
            (cache_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        await self.db.execute(
            "UPDATE synthesis_cache SET last_used_at = datetime('now', 'localtime'), "
            "hit_count = hit_count + 1 WHERE id = ?",
            (cache_id,),
        )
        await self.db.commit()
        return dict(row)

    async def set_synthesis_cache(
        self,
        *,
        cache_id: str,
        topic: str,
        scope_json: str,
        output_md: str,
        source_paths_json: str,
        source_count: int,
        token_count_input: int | None,
        token_count_output: int | None,
        model: str | None,
    ) -> None:
        # Explicit local-time timestamps so prune queries (which compare
        # against datetime('now', 'localtime', -N hours)) work regardless of
        # whatever CREATE DEFAULT the existing table was built with.
        now_local = datetime.now().isoformat()
        await self.db.execute(
            """INSERT INTO synthesis_cache
               (id, topic, scope_json, output_md, source_paths_json, source_count,
                token_count_input, token_count_output, model, created_at, last_used_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   topic = excluded.topic,
                   scope_json = excluded.scope_json,
                   output_md = excluded.output_md,
                   source_paths_json = excluded.source_paths_json,
                   source_count = excluded.source_count,
                   token_count_input = excluded.token_count_input,
                   token_count_output = excluded.token_count_output,
                   model = excluded.model,
                   created_at = excluded.created_at,
                   last_used_at = excluded.last_used_at""",
            (cache_id, topic, scope_json, output_md, source_paths_json, source_count,
             token_count_input, token_count_output, model, now_local, now_local),
        )
        await self.db.commit()
        logger.debug("synthesis_cache.set", cache_id=cache_id, topic=topic)

    async def prune_synthesis_cache(self, *, max_age_hours: int = 24) -> int:
        cursor = await self.db.execute(
            "DELETE FROM synthesis_cache WHERE created_at < datetime('now', 'localtime', ?)",
            (f"-{max_age_hours} hours",),
        )
        await self.db.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.debug("synthesis_cache.pruned", count=deleted, max_age_hours=max_age_hours)
        return deleted

    # --- Connector State (metadata blob) ---

    async def get_connector_state(self, connector_name: str) -> dict[str, Any] | None:
        """Return the metadata dict stored for this connector, or None if absent."""
        cursor = await self.db.execute(
            "SELECT metadata FROM connector_state WHERE connector_name = ?",
            (connector_name,),
        )
        row = await cursor.fetchone()
        if not row or row["metadata"] is None:
            return None
        try:
            return json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            return None

    async def save_connector_state(self, connector_name: str, state: dict[str, Any]) -> None:
        """Upsert the metadata blob for this connector_state row."""
        now = datetime.now().isoformat()
        await self.db.execute(
            """INSERT INTO connector_state (connector_name, last_sync_at, metadata)
               VALUES (?, ?, ?)
               ON CONFLICT(connector_name)
               DO UPDATE SET last_sync_at = ?, metadata = ?""",
            (connector_name, now, json.dumps(state, ensure_ascii=False),
             now, json.dumps(state, ensure_ascii=False)),
        )
        await self.db.commit()

    # --- Backfill helper ---

    async def iter_events_for_backfill(self, *, batch_size: int = 500):
        """Yield event rows as dicts for backfill, ordered by created_at ASC."""
        offset = 0
        while True:
            cursor = await self.db.execute(
                "SELECT id, source_type, payload, created_at FROM events "
                "ORDER BY created_at ASC LIMIT ? OFFSET ?",
                (batch_size, offset),
            )
            rows = await cursor.fetchall()
            if not rows:
                break
            for row in rows:
                yield dict(row)
            offset += len(rows)
            if len(rows) < batch_size:
                break
