"""Calendar events endpoint."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Query

from onlime.api.models import CalendarEventResponse
from onlime.connectors.gcal import fetch_events
from onlime.config.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/calendar/events", response_model=list[CalendarEventResponse])
def get_calendar_events(days: int = Query(7, ge=1, le=60)):
    """Return upcoming calendar events."""
    try:
        events = fetch_events(days_back=0, days_forward=days)
    except Exception:
        logger.exception("Failed to fetch calendar events")
        return []

    settings = get_settings()
    result = []
    for ev in events:
        start = ev.get("start", {})
        end = ev.get("end", {})
        attendees_raw = ev.get("attendees", [])

        attendee_names = []
        for a in attendees_raw:
            email = a.get("email", "")
            name = settings.names.resolve_name(email)
            attendee_names.append(name)

        result.append(
            CalendarEventResponse(
                id=ev.get("id", ""),
                summary=ev.get("summary", "(제목 없음)"),
                start=start.get("dateTime", start.get("date", "")),
                end=end.get("dateTime", end.get("date", "")),
                location=ev.get("location"),
                attendees=attendee_names,
            )
        )

    return result
