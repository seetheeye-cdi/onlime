"""Daily note schedule injection.

Ported from past/daily_note.py with Jinja2 template support.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.gcal import parse_event_time, is_all_day_event
from onlime.vault.io import daily_note_path, read_note, write_note, note_exists

logger = logging.getLogger(__name__)


def build_schedule_block(events: list[dict], target_date: date) -> str:
    """Build a markdown schedule block for the daily note."""
    lines = ["#### 오늘의 일정"]

    all_day = [e for e in events if is_all_day_event(e)]
    timed = [e for e in events if not is_all_day_event(e)]

    if not all_day and not timed:
        lines.append("- (일정 없음)")
        return '\n'.join(lines)

    for evt in all_day:
        title = evt.get('summary', 'Untitled')
        lines.append(f"- (종일) {title}")

    timed.sort(key=lambda e: e['start'].get('dateTime', ''))
    for evt in timed:
        start = parse_event_time(evt['start'])
        end = parse_event_time(evt['end'])
        title = evt.get('summary', 'Untitled')
        location = evt.get('location', '')

        time_str = f"{start.strftime('%H:%M')}~{end.strftime('%H:%M')}"
        loc_str = f" @ {location}" if location else ""

        date_str = target_date.strftime('%Y%m%d')
        safe_title = title.replace('/', '_').replace('\\', '_')
        meeting_note = f"{date_str}_{safe_title}_Meeting"
        lines.append(f"- {time_str} [[{meeting_note}|{title}]]{loc_str}")

    return '\n'.join(lines)


def filter_events_for_date(events: list[dict], target_date: date) -> list[dict]:
    """Filter events that fall on the target date."""
    result = []
    for evt in events:
        if is_all_day_event(evt):
            evt_date_str = evt['start'].get('date', '')
            try:
                evt_date = datetime.strptime(evt_date_str, '%Y-%m-%d').date()
                if evt_date == target_date:
                    result.append(evt)
            except ValueError:
                continue
        else:
            try:
                evt_start = parse_event_time(evt['start'])
                if evt_start.date() == target_date:
                    result.append(evt)
            except (KeyError, ValueError):
                continue
    return result


def inject_schedule(events: list[dict], target_date: date | None = None, dry_run: bool = False) -> None:
    """Insert or update schedule block in the daily note."""
    settings = get_settings()

    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%Y-%m-%d')
    path = daily_note_path(settings.vault.daily_path, date_str)

    today_events = filter_events_for_date(events, target_date)
    schedule_content = build_schedule_block(today_events, target_date)

    if not note_exists(path):
        logger.info(f"Daily note {date_str}.md does not exist, skipping schedule injection")
        return

    fm, body = read_note(path)

    heading = "## ==잡서"
    schedule_heading = "#### 오늘의 일정"
    heading_idx = body.find(heading)

    if heading_idx != -1:
        insert_pos = heading_idx + len(heading)
        if insert_pos < len(body) and body[insert_pos] == '\n':
            insert_pos += 1

        sched_idx = body.find(schedule_heading, insert_pos)
        if sched_idx != -1:
            sched_end = sched_idx + len(schedule_heading)
            rest = body[sched_end:]
            consumed = 0
            for line in rest.split('\n'):
                if consumed == 0 and line == '':
                    consumed += 1
                    continue
                if line.startswith('- ') or line.strip() == '':
                    consumed += len(line) + 1
                else:
                    break
            body = body[:sched_idx] + schedule_content + '\n' + body[sched_end + consumed:]
        else:
            body = body[:insert_pos] + schedule_content + '\n\n' + body[insert_pos:]
    else:
        body = schedule_content + '\n' + body

    if not dry_run:
        write_note(path, fm, body)

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Schedule injected into {path.name} ({len(today_events)} events)")
