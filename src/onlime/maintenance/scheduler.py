"""Scheduled Telegram notifications: Morning Brief + Daily Summary.

- Morning Brief (default 08:00 KST): today's calendar + pending retries
- Daily Summary (default 23:00 KST): processed/failed event counts

Runs as a BackgroundTask with a 5-minute polling interval, checking
whether it's time to send each notification (at most once per day).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask

logger = structlog.get_logger()


class SchedulerTask(BackgroundTask):
    """Background task for scheduled Telegram notifications."""

    name = "scheduler"

    def __init__(self, interval_seconds: int = 300) -> None:
        super().__init__(interval_seconds)
        self._sent_today: dict[str, str] = {}  # {"morning": "2026-04-08", ...}
        self._telegram_app: Any = None

    def set_telegram_app(self, app: Any) -> None:
        """Inject the Telegram Application for sending messages."""
        self._telegram_app = app

    async def run_once(self) -> None:
        if self._telegram_app is None:
            return

        settings = get_settings()
        tz = ZoneInfo(settings.general.timezone)
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")

        # Morning Brief
        if (
            now.hour == settings.scheduler.morning_brief_hour
            and self._sent_today.get("morning") != today
        ):
            await self._send_morning_brief(settings, tz, today)
            self._sent_today["morning"] = today

        # Daily Summary
        if (
            now.hour == settings.scheduler.daily_summary_hour
            and self._sent_today.get("evening") != today
        ):
            await self._send_daily_summary(settings, today)
            self._sent_today["evening"] = today

    async def _send_morning_brief(self, settings: Any, tz: ZoneInfo, today: str) -> None:
        parts = [f"☀️ {today} 모닝 브리프\n"]

        # 1. Today's calendar
        if settings.gcal.enabled:
            try:
                from pathlib import Path

                token_path = Path(settings.gcal.token_file).expanduser()
                if token_path.exists():
                    from onlime.connectors.gcal import format_events_text, get_events

                    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
                    end = start + timedelta(days=1)
                    events = await get_events(start, end)
                    if events:
                        parts.append("📅 오늘 일정")
                        parts.append(format_events_text(events))
                    else:
                        parts.append("📅 오늘 일정 없음")
            except Exception:
                logger.warning("scheduler.gcal_failed")

        # 2. Pending retries
        if self._store:
            try:
                failed = await self._store.get_retryable_events(max_retries=3)
                if failed:
                    parts.append(f"\n⚠️ 미처리 항목 {len(failed)}건")
            except Exception:
                pass

        await self._send_telegram("\n".join(parts))
        logger.info("scheduler.morning_brief_sent")

    async def _send_daily_summary(self, settings: Any, today: str) -> None:
        if self._store is None:
            return

        parts = [f"🌙 {today} 하루 요약\n"]

        try:
            # Events processed today
            cursor = await self._store.db.execute(
                "SELECT COUNT(*) FROM events WHERE date(created_at)=? AND status='done'",
                (today,),
            )
            count = (await cursor.fetchone())[0]
            parts.append(f"📝 오늘 저장한 노트: {count}건")

            # Failed today
            cursor = await self._store.db.execute(
                "SELECT COUNT(*) FROM events WHERE date(created_at)=? AND status='failed'",
                (today,),
            )
            fail_count = (await cursor.fetchone())[0]
            if fail_count:
                parts.append(f"⚠️ 실패: {fail_count}건")
        except Exception:
            logger.warning("scheduler.summary_query_failed")

        await self._send_telegram("\n".join(parts))
        logger.info("scheduler.daily_summary_sent")

    async def _send_telegram(self, text: str) -> None:
        """Send a message to the primary Telegram user."""
        settings = get_settings()
        user_ids = settings.telegram_bot.allowed_user_ids
        if not user_ids or not self._telegram_app:
            return
        try:
            await self._telegram_app.bot.send_message(
                chat_id=user_ids[0],
                text=text,
            )
        except Exception:
            logger.warning("scheduler.telegram_send_failed")
