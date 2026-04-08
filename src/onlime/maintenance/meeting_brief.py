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
        self._vault_graph: Any = None
        self._name_index: Any = None
        self._sent_briefs: dict[str, bool] = {}  # event_id+date → True

    def set_telegram_app(self, app: Any) -> None:
        self._telegram_app = app

    def set_vault_search(self, search: Any) -> None:
        self._vault_search = search

    def set_vault_graph(self, graph: Any) -> None:
        self._vault_graph = graph

    def set_name_index(self, index: Any) -> None:
        self._name_index = index

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

        for event in events:
            # Skip all-day events and cancelled
            if event.get("all_day"):
                continue
            if event.get("status") == "cancelled":
                continue

            # Dedup key: event_id + today's date
            date_key = now.strftime("%Y-%m-%d")
            brief_key = f"{event['id']}:{date_key}"
            if brief_key in self._sent_briefs:
                continue

            # Gather context and send
            try:
                context = await self._gather_context(event)
                brief_text = self._format_brief(event, context)
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

    async def _gather_context(self, event: dict[str, Any]) -> dict[str, Any]:
        """Gather related notes, graph connections, past meetings."""
        context: dict[str, Any] = {
            "related_notes": [],
            "graph_connections": [],
            "past_meetings": [],
        }

        summary = event.get("summary", "")
        attendees = event.get("attendees", [])

        # Build search query from summary + attendee names
        search_terms = [summary]
        for att in attendees[:3]:  # limit to 3 attendees
            # Extract name from email (before @)
            name_part = att.split("@")[0].replace(".", " ")
            search_terms.append(name_part)
        query = " ".join(search_terms)

        # Search related notes
        if self._vault_search:
            try:
                results = await self._vault_search.search(query, limit=5)
                context["related_notes"] = results
            except Exception:
                logger.warning("meeting_brief.search_failed", query=query[:50])

        # Search past meetings/recordings
        if self._vault_search:
            try:
                past = await self._vault_search.search(
                    f"{summary} 음성 미팅", limit=3,
                )
                context["past_meetings"] = past
            except Exception:
                pass

        # Graph connections
        if self._vault_graph:
            try:
                result = self._vault_graph.neighbors(summary, direction="both", depth=1)
                if "error" not in result:
                    context["graph_connections"] = [
                        nb["name"] for nb in result.get("neighbors", [])[:10]
                    ]
            except Exception:
                pass

        return context

    def _format_brief(self, event: dict[str, Any], context: dict[str, Any]) -> str:
        """Format briefing message for Telegram (plain text, 4096 char limit)."""
        lines: list[str] = []

        # Header
        summary = event.get("summary", "(제목 없음)")
        lines.append(f"회의 브리핑: {summary}")

        # Time & location
        start_str = event.get("start", "")
        try:
            dt = datetime.fromisoformat(start_str)
            time_part = dt.strftime("%H:%M")
        except (ValueError, TypeError):
            time_part = start_str
        location = event.get("location", "")
        time_line = f"  {time_part}"
        if location:
            time_line += f" | {location}"
        lines.append(time_line)

        # Attendees
        attendees = event.get("attendees", [])
        if attendees:
            att_str = ", ".join(a.split("@")[0] for a in attendees[:5])
            lines.append(f"  참석자: {att_str}")

        # Related notes
        related = context.get("related_notes", [])
        if related:
            lines.append("")
            lines.append("관련 노트:")
            for r in related[:5]:
                title = r.get("title", r.get("path", ""))
                snippet = r.get("snippet", "")
                line = f"  - {title}"
                if snippet:
                    line += f" -- {snippet[:60]}"
                lines.append(line)

        # Graph connections
        connections = context.get("graph_connections", [])
        if connections:
            lines.append("")
            lines.append(f"연결: {', '.join(connections[:8])}")

        # Past meetings
        past = context.get("past_meetings", [])
        if past:
            lines.append("")
            lines.append("과거 기록:")
            for p in past[:3]:
                title = p.get("title", p.get("path", ""))
                lines.append(f"  - {title}")

        text = "\n".join(lines)
        if len(text) > 4096:
            text = text[:4090] + "\n..."
        return text

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
