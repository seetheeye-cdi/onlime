"""ActionEscalator — 1h cycle, marks overdue as escalated + sends digest."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

import structlog

from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask

if TYPE_CHECKING:
    from onlime.processors.action_lifecycle import ActionLifecycle
    from onlime.state.store import StateStore

logger = structlog.get_logger()

ESCALATION_HOURS = 72
TELEGRAM_MIN_COUNT = 3
TELEGRAM_COOLDOWN_HOURS = 24
NUDGE_STATE_KEY = "action_escalator_last_nudge"


class ActionEscalatorTask(BackgroundTask):
    name = "action_escalator"
    interval_seconds = 3600  # 1h

    def __init__(
        self,
        store: "StateStore",
        lifecycle: "ActionLifecycle",
        vault_root: Path,
        telegram_sender: Any = None,
    ) -> None:
        super().__init__(interval_seconds=3600)
        self._store = store
        self._lifecycle = lifecycle
        self._vault_root = vault_root
        self._tg = telegram_sender

    async def run_once(self) -> None:
        settings = get_settings()
        flags = getattr(settings, "feature_flags", None)
        if not (flags and getattr(flags, "action_lifecycle", False)):
            return
        overdue = await self._store.get_overdue_actions(hours=ESCALATION_HOURS)
        if not overdue:
            logger.debug("action_escalator.nothing_overdue")
            return
        escalated: list[dict[str, Any]] = []
        for row in overdue:
            task_id = row["task_id"]
            try:
                ok = await self._lifecycle.transition(
                    task_id,
                    new_state="escalated",
                    expected_prior="open",
                    actor="escalator",
                )
                if ok:
                    escalated.append(row)
            except Exception:
                logger.exception("action_escalator.transition_failed", task_id=task_id)
        if not escalated:
            return
        logger.info("action_escalator.marked", count=len(escalated))
        await self._append_daily_note(escalated)
        self_owned = [r for r in escalated if not r.get("owner")]
        if len(self_owned) >= TELEGRAM_MIN_COUNT and await self._cooldown_elapsed():
            await self._send_telegram_digest(self_owned)
            await self._store.save_connector_state(
                NUDGE_STATE_KEY, {"last_nudge": datetime.now().isoformat()}
            )

    async def _cooldown_elapsed(self) -> bool:
        state = await self._store.get_connector_state(NUDGE_STATE_KEY)
        if not state or not state.get("last_nudge"):
            return True
        try:
            last = datetime.fromisoformat(state["last_nudge"])
            return datetime.now() - last > timedelta(hours=TELEGRAM_COOLDOWN_HOURS)
        except Exception:
            return True

    async def _append_daily_note(self, escalated: list[dict[str, Any]]) -> None:
        try:
            daily_dir = self._vault_root / "2.OUTPUT" / "Daily"
            daily_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            daily_path = daily_dir / f"{today}.md"
            lines = [f"\n## ⚠️ 에스컬레이션 (72h 초과)\n"]
            for row in escalated:
                owner = row.get("owner") or "나"
                task = row.get("task_text", "")
                due = row.get("due_at") or ""
                lines.append(
                    f"- [ ] {task} (@{owner})" + (f" — due {due}" if due else "")
                )
            lines.append("")
            existing = (
                daily_path.read_text(encoding="utf-8")
                if daily_path.exists()
                else f"# {today}\n"
            )
            daily_path.write_text(existing + "\n".join(lines), encoding="utf-8")
        except Exception:
            logger.exception("action_escalator.daily_note_failed")

    async def _send_telegram_digest(self, self_owned: list[dict[str, Any]]) -> None:
        if self._tg is None:
            return
        try:
            lines = [f"⚠️ 72시간 넘은 내 할 일 {len(self_owned)}건"]
            for row in self_owned[:10]:
                lines.append(f"• {row.get('task_text', '')}")
            text = "\n".join(lines)
            # Support both protocols: bare async callable or object with .send_message
            sender = self._tg
            if callable(sender) and not hasattr(sender, "send_message"):
                await sender(text)
            else:
                await sender.send_message(text)
            logger.info("action_escalator.telegram_sent", count=len(self_owned))
        except Exception:
            logger.exception("action_escalator.telegram_failed")
