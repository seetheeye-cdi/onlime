"""Background task: proactive meeting briefing via Telegram.

Polls GCal every 5 minutes. When a meeting is 30 minutes away,
gathers related notes + past meetings + graph connections and
sends a briefing to the user via Telegram.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from onlime.briefing import compose_meeting_brief
from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask

logger = structlog.get_logger()


class MeetingBriefTask(BackgroundTask):
    """Send meeting briefings 30 minutes before events."""

    name = "meeting_brief"

    def __init__(self, interval_seconds: int = 300) -> None:
        super().__init__(interval_seconds=interval_seconds)
        self._telegram_app: Any = None
        self._vault_search: Any = None
        self._name_index: Any = None
        self._people_resolver: Any = None
        self._sent_briefs: dict[str, bool] = {}  # event_id+date → True

    def set_telegram_app(self, app: Any) -> None:
        self._telegram_app = app

    def set_vault_search(self, search: Any) -> None:
        self._vault_search = search

    def set_name_index(self, index: Any) -> None:
        self._name_index = index

    def set_people_resolver(self, resolver: Any) -> None:
        self._people_resolver = resolver

    async def run_once(self) -> None:
        settings = get_settings()

        # Skip if GCal not set up
        token_path = Path(settings.gcal.token_file).expanduser()
        if not token_path.exists():
            logger.info("meeting_brief.skipped", reason="no gcal token")
            return

        # Skip if no Telegram app
        if not self._telegram_app:
            return

        from onlime.connectors.gcal import get_events

        tz = ZoneInfo(settings.general.timezone)
        now = datetime.now(tz)
        window_end = now + timedelta(minutes=35)

        events = await get_events(now, window_end)
        date_key = now.strftime("%Y-%m-%d")

        for event in events:
            # Skip all-day events and cancelled
            if event.get("all_day"):
                continue
            if event.get("status") == "cancelled":
                continue

            # Dedup key: event_id + today's date
            brief_key = f"{event['id']}:{date_key}"
            if brief_key in self._sent_briefs:
                continue

            # Gather context and send
            try:
                brief_text = await compose_meeting_brief(
                    event,
                    vault_search=self._vault_search,
                    name_index=self._name_index,
                    people_resolver=self._people_resolver,
                )
                await self._send_telegram(brief_text)
                self._sent_briefs[brief_key] = True
                logger.info(
                    "meeting_brief.sent",
                    event_id=event["id"],
                    summary=event["summary"],
                )
            except Exception:
                logger.exception(
                    "meeting_brief.send_failed",
                    event_id=event["id"],
                )

        # Clean old keys (keep only today's)
        old_keys = [k for k in self._sent_briefs if not k.endswith(f":{date_key}")]
        for k in old_keys:
            del self._sent_briefs[k]

    async def _send_telegram(self, text: str) -> None:
        """Send briefing to the first allowed user via Telegram."""
        settings = get_settings()
        allowed = settings.telegram_bot.allowed_user_ids
        if not allowed:
            logger.warning("meeting_brief.no_allowed_users")
            return

        chat_id = allowed[0]
        await self._telegram_app.bot.send_message(
            chat_id=chat_id,
            text=text,
        )
