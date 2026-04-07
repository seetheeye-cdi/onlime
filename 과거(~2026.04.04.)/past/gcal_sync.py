"""Google Calendar → Obsidian meeting notes sync."""
from __future__ import annotations

import json
import sys
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from config import (
    GCAL_CREDS_FILE, GCAL_TOKEN_FILE, CALENDAR_IDS,
    TIMEZONE, SYNC_DAYS_BACK, SYNC_DAYS_FORWARD, MEETING_DIR,
    resolve_name,
)
from vault_io import meeting_note_path, note_exists, read_note, write_note

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)


def fetch_events(days_back=SYNC_DAYS_BACK, days_forward=SYNC_DAYS_FORWARD) -> list[dict]:
    """Fetch events from Google Calendar API using OAuth2 credentials."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
    creds = None

    if GCAL_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GCAL_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GCAL_CREDS_FILE.exists():
                logger.error(
                    f"Google credentials not found at {GCAL_CREDS_FILE}. "
                    "Run setup_auth.py first."
                )
                return []
            flow = InstalledAppFlow.from_client_secrets_file(str(GCAL_CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        GCAL_TOKEN_FILE.write_text(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)

    now = datetime.now(tz=tz)
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_forward)).isoformat()

    all_events = []
    for cal_id in CALENDAR_IDS:
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
    # Handle both raw event list and MCP response format
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and 'events' in data:
        return data['events']
    return []


def parse_event_time(time_obj: dict) -> datetime:
    """Parse a Google Calendar start/end time object."""
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


def event_to_meeting_note(event: dict) -> tuple[dict, str]:
    """Convert a Google Calendar event into (frontmatter, body) for a meeting note."""
    start = parse_event_time(event['start'])
    end = parse_event_time(event['end'])
    title = event.get('summary', 'Untitled Meeting')
    attendees = []
    for a in event.get('attendees', []):
        email = a.get('email', '')
        name = resolve_name(email) if email else a.get('displayName', '')
        attendees.append(name)

    # Participants: calendar attendees (Korean names only) + always 최동인
    import re as _re
    participants = ['[[최동인]]']
    for a in attendees:
        if a and not _re.match(r'^[a-zA-Z0-9. _]+$', a) and a != '최동인':
            participants.append(f'[[{a}]]')

    frontmatter = {
        'created': start.strftime('%Y-%m-%d %H:%M'),
        'participants': sorted(set(participants)),
        'type': 'meeting',
        'category': classify_meeting(title, [a.get('email', '') for a in event.get('attendees', [])]),
        'gcal_id': event['id'],
    }

    gcal_block = f"- 일시: {start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%H:%M')}"
    loc = event.get('location', '')
    if loc:
        gcal_block += f"\n- 장소: {loc}"
    if attendees:
        gcal_block += f"\n- 참석자: {', '.join(attendees)}"
    desc = event.get('description', '')
    if desc:
        gcal_block += f"\n- 설명: {desc}"

    body = (
        f"\n# 회의: {title}\n\n"
        f"## 목표\n"
        f"이번 미팅에서 달성할 것\n\n"
        f"## 논의 내용\n"
        f"{gcal_block}\n\n"
        f"## 결정사항\n"
        f"- 결정: / 담당:\n\n"
        f"## 액션 아이템\n"
        f"- [ ] [[담당자]] — due:[[{start.strftime('%Y-%m-%d')}]]\n\n"
        f"## 다음 미팅\n"
        f"- 일정:\n"
        f"- 안건:\n"
    )

    return frontmatter, body


def sync_calendar_events(events: list[dict], state, dry_run=False) -> list[dict]:
    """Create/update meeting notes for calendar events. Returns processed events."""
    processed = []
    for event in events:
        event_id = event.get('id', '')
        if not event_id:
            continue

        # Skip all-day events (not meetings)
        if is_all_day_event(event):
            processed.append(event)
            continue

        # Skip cancelled events
        if event.get('status') == 'cancelled':
            continue

        updated = event.get('updated', '')
        if state.is_event_processed(event_id, updated):
            processed.append(event)
            continue

        title = event.get('summary', 'Untitled Meeting')
        start = parse_event_time(event['start'])
        date_str = start.strftime('%Y%m%d')
        note_path = meeting_note_path(MEETING_DIR, date_str, title)

        if note_exists(note_path):
            # Update frontmatter participants only, preserve user content
            fm, body = read_note(note_path)
            attendee_names = [
                resolve_name(a.get('email', '')) if a.get('email') else a.get('displayName', '')
                for a in event.get('attendees', [])
            ]
            if attendee_names:
                fm['participants'] = [f'[[{n}]]' for n in attendee_names]
            if not dry_run:
                write_note(note_path, fm, body)
            logger.info(f"Updated: {note_path.name}")
        else:
            fm, body = event_to_meeting_note(event)
            if not dry_run:
                write_note(note_path, fm, body)
            logger.info(f"Created: {note_path.name}")

        if not dry_run:
            state.mark_event_processed(event_id, str(note_path), updated)
        processed.append(event)

    return processed
