"""Action lifecycle — FSM + escalator + source-note sync + Telegram dispatch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

import structlog

from onlime.config import get_settings

if TYPE_CHECKING:
    from onlime.state.store import StateStore
    from onlime.processors.people_resolver import PeopleResolver

logger = structlog.get_logger()


class ActionState(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_ON_OTHER = "waiting_on_other"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


TERMINAL_STATES = {ActionState.COMPLETED, ActionState.CANCELLED}

ALLOWED_TRANSITIONS: dict[ActionState, set[ActionState]] = {
    ActionState.OPEN: {
        ActionState.IN_PROGRESS, ActionState.WAITING_ON_OTHER, ActionState.BLOCKED,
        ActionState.COMPLETED, ActionState.CANCELLED, ActionState.ESCALATED,
    },
    ActionState.IN_PROGRESS: {
        ActionState.WAITING_ON_OTHER, ActionState.BLOCKED,
        ActionState.COMPLETED, ActionState.CANCELLED,
    },
    ActionState.WAITING_ON_OTHER: {
        ActionState.IN_PROGRESS, ActionState.BLOCKED,
        ActionState.COMPLETED, ActionState.CANCELLED,
    },
    ActionState.BLOCKED: {
        ActionState.OPEN, ActionState.IN_PROGRESS, ActionState.CANCELLED,
    },
    ActionState.COMPLETED: set(),
    ActionState.CANCELLED: set(),
    ActionState.ESCALATED: {
        ActionState.OPEN, ActionState.IN_PROGRESS,
        ActionState.COMPLETED, ActionState.CANCELLED,
    },
}


class InvalidTransitionError(Exception):
    pass


@dataclass
class ActionRecord:
    task_id: int
    task_text: str
    state: str
    owner: str | None
    priority: str
    source_event_id: str | None
    source_note_path: str | None
    due_at: str | None
    created_at: str
    updated_at: str
    notes: str | None = None


class ActionLifecycle:
    """High-level FSM wrapper over action_lifecycle table."""

    def __init__(
        self,
        store: "StateStore",
        resolver: "PeopleResolver",
    ) -> None:
        self._store = store
        self._resolver = resolver

    async def insert_from_extraction(
        self,
        *,
        items: list[dict[str, Any]],
        event_id: str,
        source_note_path: str | None = None,
    ) -> list[int]:
        """Insert LLM-extracted action items.

        Items shape: [{'task': str, 'owner': str, 'due_date': str | None,
                       'source_note': str | None, 'priority': str | None}, ...]
        Returns list of new task_ids.
        Each owner is resolved through PeopleResolver; empty/self stays as None.
        """
        task_ids: list[int] = []
        for item in items:
            task_text = (item.get("task") or "").strip()
            if not task_text:
                continue
            raw_owner = (item.get("owner") or "").strip()
            owner = self._resolve_owner(raw_owner)
            priority = item.get("priority") or "normal"
            if priority not in {"urgent", "high", "normal", "low"}:
                priority = "normal"
            due_at = item.get("due_date") or None
            notes = item.get("context") or None
            try:
                task_id = await self._store.insert_action(
                    task_text=task_text,
                    owner=owner,
                    priority=priority,
                    source_event_id=event_id,
                    source_note_path=source_note_path or item.get("source_note"),
                    due_at=due_at,
                    notes=notes,
                )
                task_ids.append(task_id)
            except Exception:
                logger.exception("action_lifecycle.insert_failed", task_text=task_text[:60])
        logger.info("action_lifecycle.inserted", count=len(task_ids), event_id=event_id)
        return task_ids

    def _resolve_owner(self, raw_owner: str) -> str | None:
        """Resolve owner through PeopleResolver. Returns None for self/empty/'나'/'me'."""
        if not raw_owner:
            return None
        low = raw_owner.strip().lower()
        if low in {"", "나", "self", "me", "i", "본인"}:
            return None
        try:
            canonical = self._resolver.resolve(raw_owner)
            return canonical or raw_owner
        except Exception:
            return raw_owner

    async def transition(
        self,
        task_id: int,
        *,
        new_state: str | ActionState,
        expected_prior: str | ActionState,
        actor: str = "system",
    ) -> bool:
        """Optimistic state transition.

        Returns True on success, False on prior-state mismatch,
        raises InvalidTransitionError on illegal transition.
        """
        new = ActionState(new_state) if isinstance(new_state, str) else new_state
        prior = ActionState(expected_prior) if isinstance(expected_prior, str) else expected_prior
        if new not in ALLOWED_TRANSITIONS.get(prior, set()):
            raise InvalidTransitionError(f"{prior.value} → {new.value} not allowed")
        ok = await self._store.transition_action(
            task_id,
            new_state=new.value,
            expected_prior=prior.value,
        )
        if ok:
            logger.info(
                "action_lifecycle.transition",
                task_id=task_id,
                from_=prior.value,
                to=new.value,
                actor=actor,
            )
            if new == ActionState.COMPLETED:
                await self._maybe_sync_source_note(task_id)
        return ok

    async def _maybe_sync_source_note(self, task_id: int) -> None:
        """On completion, try to update source vault file: - [ ] → - [x]."""
        try:
            rows = await self._store.get_actions_by_state(ActionState.COMPLETED.value, limit=500)
            row = next((r for r in rows if r.get("task_id") == task_id), None)
            if not row:
                return
            source_path = row.get("source_note_path")
            task_text = row.get("task_text")
            if not source_path or not task_text:
                return
            path = Path(source_path)
            if not path.exists():
                logger.debug("action_lifecycle.source_note_missing", path=source_path)
                return
            content = path.read_text(encoding="utf-8")
            date_str = datetime.now().strftime("%Y-%m-%d")
            pattern = re.compile(
                r"^(\s*)- \[ \]\s+" + re.escape(task_text.strip()) + r"(.*)$",
                re.MULTILINE,
            )
            new_content, count = pattern.subn(
                rf"\1- [x] {task_text.strip()}\2 ✅ {date_str}", content, count=1
            )
            if count > 0:
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(new_content, encoding="utf-8")
                tmp.replace(path)
                logger.info(
                    "action_lifecycle.source_synced",
                    path=source_path,
                    task_id=task_id,
                )
        except Exception:
            logger.exception("action_lifecycle.source_sync_failed", task_id=task_id)

    async def get_overdue(
        self, *, hours: int = 72, owner: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._store.get_overdue_actions(hours=hours, owner=owner)

    async def get_by_state(
        self,
        state: str | ActionState,
        *,
        owner: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        value = state.value if isinstance(state, ActionState) else state
        return await self._store.get_actions_by_state(value, owner=owner, limit=limit)

    async def list_self_pending(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return open/in_progress actions owned by self (owner IS NULL)."""
        open_items = await self._store.get_actions_by_state("open", owner=None, limit=limit)
        in_prog = await self._store.get_actions_by_state("in_progress", owner=None, limit=limit)
        combined = [r for r in open_items if not r.get("owner")] + [
            r for r in in_prog if not r.get("owner")
        ]
        return combined[:limit]
