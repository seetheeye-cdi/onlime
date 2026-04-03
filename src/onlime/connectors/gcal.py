"""Google Calendar connector — fetch logic only.

Ported from past/gcal_sync.py. Note formatting moved to outputs/meeting_note.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector, ConnectorResult
from onlime.connectors.registry import register

logger = logging.getLogger(__name__)


def _get_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().general.timezone)


def parse_event_time(time_obj: dict) -> datetime:
    """Parse a Google Calendar start/end time object."""
    tz = _get_tz()
    if 'dateTime' in time_obj:
        dt = datetime.fromisoformat(time_obj['dateTime'])
        return dt.astimezone(tz)
    if 'date' in time_obj:
        return datetime.strptime(time_obj['date'], '%Y-%m-%d').replace(tzinfo=tz)
    return datetime.now(tz=tz)


def is_all_day_event(event: dict) -> bool:
    return 'date' in event.get('start', {})


def classify_meeting(summary: str, attendees: list[str]) -> str:
    """Classify meeting category based on title and attendees."""
    s = summary.lower()
    if any(kw in s for kw in ['투자', 'ir', 'investor', '피칭', 'pitch']):
        return 'investor-update'
    if any(kw in s for kw in ['1on1', '1:1', '원온원']):
        return '1on1'
    if any(kw in s for kw in ['내부', 'internal', '스탠드업', 'standup']):
        return 'internal'
    return 'external-partner'


def _build_credentials():
    """Build Google OAuth2 credentials, refreshing if needed."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    settings = get_settings()
    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
    creds_file = settings.gcal.resolved_creds_file
    token_file = settings.gcal.resolved_token_file
    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_file.exists():
                logger.error(
                    f"Google credentials not found at {creds_file}. "
                    "Run: onlime setup gcal"
                )
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(port=0)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())

    return creds


def fetch_events(
    days_back: int | None = None,
    days_forward: int | None = None,
) -> list[dict]:
    """Fetch events from Google Calendar API using OAuth2 credentials."""
    from googleapiclient.discovery import build

    settings = get_settings()
    tz = _get_tz()
    days_back = days_back or settings.gcal.sync_days_back
    days_forward = days_forward or settings.gcal.sync_days_forward

    creds = _build_credentials()
    if not creds:
        return []

    service = build('calendar', 'v3', credentials=creds)

    now = datetime.now(tz=tz)
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_forward)).isoformat()

    all_events = []
    for cal_id in settings.gcal.calendar_ids:
        page_token = None
        while True:
            result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime',
                pageToken=page_token,
            ).execute()
            all_events.extend(result.get('items', []))
            page_token = result.get('nextPageToken')
            if not page_token:
                break

    # Deduplicate by event ID
    seen = set()
    events = []
    for e in all_events:
        eid = e.get('id', '')
        if eid not in seen:
            seen.add(eid)
            events.append(e)

    logger.info(f"Fetched {len(events)} events from Google Calendar")
    return events


def fetch_events_from_json(json_path: str) -> list[dict]:
    """Load events from a JSON file (for MCP/Claude Code integration)."""
    with open(json_path, 'r') as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and 'events' in data:
        return data['events']
    return []


def _event_to_connector_result(event: dict) -> ConnectorResult:
    """Convert a raw Google Calendar event to ConnectorResult."""
    settings = get_settings()
    tz = _get_tz()

    start = parse_event_time(event['start'])
    end = parse_event_time(event['end'])
    title = event.get('summary', 'Untitled Meeting')

    attendees = []
    for a in event.get('attendees', []):
        email = a.get('email', '')
        name = settings.names.resolve_name(email) if email else a.get('displayName', '')
        if name:
            attendees.append(name)

    duration = (end - start).total_seconds() / 60 if not is_all_day_event(event) else None

    return ConnectorResult(
        source_id=event.get('id', ''),
        source_type='calendar',
        connector_name='gcal',
        timestamp=start,
        title=title,
        content=event.get('description', ''),
        participants=attendees,
        duration_minutes=duration,
        metadata={
            'location': event.get('location', ''),
            'category': classify_meeting(title, [a.get('email', '') for a in event.get('attendees', [])]),
            'updated': event.get('updated', ''),
            'status': event.get('status', ''),
            'all_day': is_all_day_event(event),
            'end_time': end.isoformat(),
        },
        raw=event,
    )


@register
class GoogleCalendarConnector(BaseConnector):
    name = "gcal"

    def fetch(self, *, days_back: int | None = None, days_forward: int | None = None,
              json_path: str | None = None, **kwargs) -> list[ConnectorResult]:
        if json_path:
            raw_events = fetch_events_from_json(json_path)
        else:
            raw_events = fetch_events(days_back=days_back, days_forward=days_forward)

        return [_event_to_connector_result(e) for e in raw_events]

    def is_available(self) -> bool:
        settings = get_settings()
        return settings.gcal.resolved_creds_file.exists() or settings.gcal.resolved_token_file.exists()
