"""Google Calendar API async wrapper.

All Google API calls are wrapped in asyncio.to_thread() since the
google-api-python-client is synchronous.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from onlime.config import get_settings

logger = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_credentials() -> Credentials:
    """Load credentials from token.json with auto-refresh.

    Raises RuntimeError if token.json doesn't exist (run setup_gcal.py first).
    """
    settings = get_settings()
    token_path = Path(settings.gcal.token_file).expanduser()

    if not token_path.exists():
        raise RuntimeError(
            f"GCal token not found at {token_path}. "
            "Run: python scripts/setup_gcal.py"
        )

    creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        logger.info("gcal.token_refreshed")

    return creds


def _build_service() -> Any:
    """Build a Calendar API service object."""
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _normalize_event(item: dict[str, Any], calendar_id: str) -> dict[str, Any]:
    """Normalize a Google Calendar event to a flat dict."""
    start_raw = item.get("start", {})
    end_raw = item.get("end", {})

    # All-day events use 'date', timed events use 'dateTime'
    all_day = "date" in start_raw and "dateTime" not in start_raw
    start_str = start_raw.get("dateTime") or start_raw.get("date", "")
    end_str = end_raw.get("dateTime") or end_raw.get("date", "")

    attendees = [
        a.get("email", "")
        for a in item.get("attendees", [])
        if not a.get("self")
    ]

    return {
        "id": item["id"],
        "calendar_id": calendar_id,
        "summary": item.get("summary", "(제목 없음)"),
        "start": start_str,
        "end": end_str,
        "all_day": all_day,
        "location": item.get("location", ""),
        "description": item.get("description", ""),
        "attendees": attendees,
        "status": item.get("status", "confirmed"),
        "html_link": item.get("htmlLink", ""),
    }


async def get_events(
    start: datetime,
    end: datetime,
    calendar_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch events from Google Calendar within [start, end)."""
    settings = get_settings()
    cal_ids = calendar_ids or settings.gcal.calendar_ids

    def _fetch() -> list[dict[str, Any]]:
        service = _build_service()
        all_events: list[dict[str, Any]] = []
        for cal_id in cal_ids:
            result = (
                service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=start.isoformat() + "Z" if not start.tzinfo else start.isoformat(),
                    timeMax=end.isoformat() + "Z" if not end.tzinfo else end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute()
            )
            for item in result.get("items", []):
                all_events.append(_normalize_event(item, cal_id))
        all_events.sort(key=lambda e: e["start"])
        return all_events

    events = await asyncio.to_thread(_fetch)
    logger.info("gcal.fetched", count=len(events))
    return events


async def create_event(
    summary: str,
    start: datetime,
    end: datetime | None = None,
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Create a new calendar event."""
    if end is None:
        end = start + timedelta(hours=1)

    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Seoul"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Seoul"},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location

    def _create() -> dict[str, Any]:
        service = _build_service()
        return service.events().insert(calendarId=calendar_id, body=body).execute()

    result = await asyncio.to_thread(_create)
    logger.info("gcal.created", event_id=result["id"], summary=summary)
    return _normalize_event(result, calendar_id)


async def update_event(
    event_id: str,
    calendar_id: str = "primary",
    **updates: Any,
) -> dict[str, Any]:
    """Update an existing calendar event."""

    def _update() -> dict[str, Any]:
        service = _build_service()
        # Fetch current event
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        # Apply updates
        for key, val in updates.items():
            if key in ("start", "end") and isinstance(val, datetime):
                event[key] = {"dateTime": val.isoformat(), "timeZone": "Asia/Seoul"}
            else:
                event[key] = val
        return service.events().update(
            calendarId=calendar_id, eventId=event_id, body=event
        ).execute()

    result = await asyncio.to_thread(_update)
    logger.info("gcal.updated", event_id=event_id)
    return _normalize_event(result, calendar_id)


async def delete_event(
    event_id: str,
    calendar_id: str = "primary",
) -> bool:
    """Delete a calendar event."""

    def _delete() -> bool:
        service = _build_service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True

    result = await asyncio.to_thread(_delete)
    logger.info("gcal.deleted", event_id=event_id)
    return result


async def find_overlapping_event(
    recorded_at: datetime,
    buffer_minutes: int = 15,
) -> dict[str, Any] | None:
    """Find a calendar event overlapping the recording timestamp (±buffer).

    Returns the closest normalized event dict with an added "project" key,
    or None if no overlapping event is found.
    """
    try:
        start = recorded_at - timedelta(minutes=buffer_minutes)
        end = recorded_at + timedelta(minutes=buffer_minutes)
        events = await get_events(start, end)
    except Exception:
        logger.warning("gcal.overlap_lookup_failed", recorded_at=recorded_at.isoformat())
        return None

    if not events:
        return None

    # Filter out all-day events (not meetings)
    timed = [e for e in events if not e["all_day"]]
    if not timed:
        return None

    # Pick the event whose start is closest to recorded_at
    def _distance(ev: dict[str, Any]) -> float:
        try:
            ev_start = datetime.fromisoformat(ev["start"])
            # Strip tzinfo for comparison if recorded_at is naive
            if ev_start.tzinfo and not recorded_at.tzinfo:
                ev_start = ev_start.replace(tzinfo=None)
            return abs((ev_start - recorded_at).total_seconds())
        except (ValueError, TypeError):
            return float("inf")

    best = min(timed, key=_distance)
    best["project"] = _detect_project(best)
    logger.info(
        "gcal.overlap_found",
        summary=best["summary"],
        project=best["project"],
        recorded_at=recorded_at.isoformat(),
    )
    return best


def _detect_project(ev: dict[str, Any]) -> str | None:
    """Detect project from calendar_id or event summary keywords."""
    settings = get_settings()

    # 1. Calendar-level label
    cal_label = settings.gcal.calendar_labels.get(ev.get("calendar_id", ""))
    if cal_label:
        return cal_label

    # 2. Keyword match in summary
    summary = ev.get("summary", "")
    for keyword, project in settings.gcal.project_keywords.items():
        if keyword.lower() in summary.lower():
            return project

    return None


def format_events_text(events: list[dict[str, Any]]) -> str:
    """Format events list as Korean text for daily note / Telegram."""
    if not events:
        return "일정이 없습니다."

    lines: list[str] = []
    for ev in events:
        start_str = ev["start"]
        if ev["all_day"]:
            time_part = "종일"
        else:
            try:
                dt = datetime.fromisoformat(start_str)
                time_part = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                time_part = start_str

        line = f"- {time_part} {ev['summary']}"
        if ev.get("location"):
            line += f" ({ev['location']})"

        project = _detect_project(ev)
        if project:
            line += f" — [[{project}]]"

        lines.append(line)

    return "\n".join(lines)
