"""Inject today's calendar schedule into the daily note."""
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from config import DAILY_DIR, MEETING_DIR, TIMEZONE
from vault_io import daily_note_path, read_note, write_note, note_exists
from gcal_sync import parse_event_time, is_all_day_event

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)


def build_schedule_block(events: list[dict], target_date: date) -> str:
    """Build a markdown schedule block for the daily note."""
    lines = ["#### 오늘의 일정"]

    # Separate all-day and timed events
    all_day = [e for e in events if is_all_day_event(e)]
    timed = [e for e in events if not is_all_day_event(e)]

    if not all_day and not timed:
        lines.append("- (일정 없음)")
        return '\n'.join(lines)

    # All-day events first
    for evt in all_day:
        title = evt.get('summary', 'Untitled')
        lines.append(f"- (종일) {title}")

    # Timed events sorted by start time
    timed.sort(key=lambda e: e['start'].get('dateTime', ''))
    for evt in timed:
        start = parse_event_time(evt['start'])
        end = parse_event_time(evt['end'])
        title = evt.get('summary', 'Untitled')
        location = evt.get('location', '')

        time_str = f"{start.strftime('%H:%M')}~{end.strftime('%H:%M')}"
        loc_str = f" @ {location}" if location else ""

        # Link to meeting note
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


def inject_schedule(events: list[dict], target_date: date = None, dry_run=False):
    """Insert or update schedule block in the daily note."""
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%Y-%m-%d')
    path = daily_note_path(DAILY_DIR, date_str)

    today_events = filter_events_for_date(events, target_date)
    schedule_content = build_schedule_block(today_events, target_date)

    if not note_exists(path):
        logger.info(f"Daily note {date_str}.md does not exist, skipping schedule injection")
        return

    fm, body = read_note(path)

    # Insert/replace schedule block after "## ==잡서" heading
    heading = "## ==잡서"
    schedule_heading = "#### 오늘의 일정"
    heading_idx = body.find(heading)

    if heading_idx != -1:
        insert_pos = heading_idx + len(heading)
        if insert_pos < len(body) and body[insert_pos] == '\n':
            insert_pos += 1

        # Check if "#### 오늘의 일정" already exists — replace just that block
        sched_idx = body.find(schedule_heading, insert_pos)
        if sched_idx != -1:
            # Find end of schedule block: consecutive "- " lines after the heading
            sched_end = sched_idx + len(schedule_heading)
            rest = body[sched_end:]
            consumed = 0
            for line in rest.split('\n'):
                if consumed == 0 and line == '':
                    consumed += 1  # skip first newline after heading
                    continue
                if line.startswith('- ') or line.strip() == '':
                    consumed += len(line) + 1
                else:
                    break
            body = body[:sched_idx] + schedule_content + '\n' + body[sched_end + consumed:]
        else:
            # Insert right after "## ==잡서"
            body = body[:insert_pos] + schedule_content + '\n\n' + body[insert_pos:]
    else:
        body = schedule_content + '\n' + body

    if not dry_run:
        write_note(path, fm, body)

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Schedule injected into {path.name} ({len(today_events)} events)")
