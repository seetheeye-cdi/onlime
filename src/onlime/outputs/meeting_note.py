"""Meeting note formatter — creates/updates Obsidian meeting notes.

Ported from past/gcal_sync.py (note creation logic) + past/main.py (plaud append logic).
"""
from __future__ import annotations

import re
import logging
from pathlib import Path

from onlime.config import get_settings
from onlime.connectors.base import ConnectorResult
from onlime.connectors.gcal import parse_event_time, is_all_day_event
from onlime.outputs.base import BaseOutputFormatter
from onlime.outputs.templates import render_template
from onlime.vault.io import meeting_note_path, note_exists, read_note, write_note

logger = logging.getLogger(__name__)


class MeetingNoteFormatter(BaseOutputFormatter):
    """Format Google Calendar events into Obsidian meeting notes."""

    def format(self, result: ConnectorResult, **kwargs) -> tuple[dict, str]:
        settings = get_settings()
        event = result.raw

        start = result.timestamp
        end_str = result.metadata.get('end_time', '')

        # Build participants with wiki-links
        participants = ['[[최동인]]']
        for name in result.participants:
            if name and not re.match(r'^[a-zA-Z0-9. _]+$', name) and name != '최동인':
                participants.append(f'[[{name}]]')

        frontmatter = {
            'created': start.strftime('%Y-%m-%d %H:%M'),
            'participants': sorted(set(participants)),
            'type': 'meeting',
            'category': result.metadata.get('category', 'external-partner'),
            'gcal_id': result.source_id,
        }

        # Build attendee names for display
        attendees = result.participants

        body = render_template(
            'meeting.md.j2',
            title=result.title,
            start_time=start.strftime('%Y-%m-%d %H:%M'),
            end_time=end_str.split('T')[1][:5] if 'T' in str(end_str) else '',
            location=result.metadata.get('location', ''),
            attendees=attendees,
            description=result.content,
            due_date=start.strftime('%Y-%m-%d'),
            plaud_summary=kwargs.get('plaud_summary'),
            plaud_outline=kwargs.get('plaud_outline'),
            plaud_transcript=kwargs.get('plaud_transcript'),
        )

        return frontmatter, body

    def get_output_path(self, result: ConnectorResult, **kwargs) -> Path:
        settings = get_settings()
        date_str = result.timestamp.strftime('%Y%m%d')
        return meeting_note_path(settings.vault.meeting_path, date_str, result.title)


def sync_calendar_events(events: list[dict], state, dry_run: bool = False) -> list[dict]:
    """Create/update meeting notes for calendar events. Returns processed events."""
    settings = get_settings()
    formatter = MeetingNoteFormatter()
    processed = []

    for event in events:
        event_id = event.get('id', '')
        if not event_id:
            continue

        if is_all_day_event(event):
            processed.append(event)
            continue

        if event.get('status') == 'cancelled':
            continue

        updated = event.get('updated', '')
        if state.is_event_processed(event_id, updated):
            processed.append(event)
            continue

        # Convert raw event to ConnectorResult for formatting
        from onlime.connectors.gcal import _event_to_connector_result
        cr = _event_to_connector_result(event)
        note_path = formatter.get_output_path(cr)

        if note_exists(note_path):
            fm, body = read_note(note_path)
            # Update participants only, preserve user content
            if cr.participants:
                fm['participants'] = sorted(set(
                    f'[[{n}]]' for n in cr.participants
                    if not re.match(r'^[a-zA-Z0-9. _]+$', n)
                ))
                if '[[최동인]]' not in fm['participants']:
                    fm['participants'].insert(0, '[[최동인]]')
            if not dry_run:
                write_note(note_path, fm, body)
            logger.info(f"Updated: {note_path.name}")
        else:
            fm, body = formatter.format(cr)
            if not dry_run:
                write_note(note_path, fm, body)
            logger.info(f"Created: {note_path.name}")

        if not dry_run:
            state.mark_event_processed(event_id, str(note_path), updated)
        processed.append(event)

    return processed


def append_plaud_to_meeting(
    note_path: Path, transcript_md: str,
    summary_md: str | None = None, outline_md: str | None = None,
    dry_run: bool = False,
) -> None:
    """Append Plaud transcription content to an existing meeting note."""
    fm, body = read_note(note_path)

    plaud_content = ""
    if summary_md:
        plaud_content += f"### AI 요약\n{summary_md}\n\n"
    if outline_md:
        plaud_content += outline_md + "\n\n"
    plaud_content += transcript_md

    heading = "## 논의 내용"
    idx = body.find(heading)
    if idx != -1:
        insert_pos = idx + len(heading)
        if insert_pos < len(body) and body[insert_pos] == '\n':
            insert_pos += 1
        body = body[:insert_pos] + plaud_content + '\n' + body[insert_pos:]
    else:
        body += f"\n{heading}\n{plaud_content}\n"

    if not dry_run:
        write_note(note_path, fm, body)
    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Appended transcript to {note_path.name}")
