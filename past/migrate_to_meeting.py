#!/usr/bin/env python3
"""Move matched Plaud recordings from Inbox to proper Meeting notes."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from config import STATE_FILE, TIMEZONE, MEETING_DIR, resolve_name
from gcal_sync import parse_event_time, is_all_day_event, classify_meeting
from vault_io import read_note, write_note, meeting_note_path, note_exists

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("migrate")
tz = ZoneInfo(TIMEZONE)


def main():
    state_path = Path(STATE_FILE)
    state = json.loads(state_path.read_text())
    events = json.load(open('/tmp/gcal_events_full.json'))
    event_map = {e['id']: e for e in events}

    inbox = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc/0. INPUT/COLLECT/00. Inbox")
    moved = 0
    errors = 0

    for rec_id, info in list(state['processed_recordings'].items()):
        evt_id = info.get('matched_event')
        old_path_str = info.get('note_path', '')
        if not evt_id or '/00. Inbox/' not in old_path_str:
            continue

        old_path = Path(old_path_str)
        if not old_path.exists():
            logger.warning(f"Source not found: {old_path.name}")
            continue

        evt = event_map.get(evt_id)
        if not evt:
            logger.warning(f"Event not found: {evt_id}")
            continue

        # Skip all-day events
        if is_all_day_event(evt):
            continue

        # Build meeting note path
        title = evt.get('summary', 'Untitled Meeting')
        start = parse_event_time(evt['start'])
        end = parse_event_time(evt['end'])
        date_str = start.strftime('%Y%m%d')
        new_path = meeting_note_path(MEETING_DIR, date_str, title)

        # Read the Plaud note content
        plaud_fm, plaud_body = read_note(old_path)

        # Extract the useful parts from Plaud note body
        summary_section = ""
        outline_section = ""
        transcript_section = ""
        links_section = ""

        # Parse sections from plaud body
        sections = re.split(r'\n(?=## )', plaud_body)
        for sec in sections:
            if sec.strip().startswith('## AI 요약'):
                summary_section = sec.replace('## AI 요약', '### AI 요약', 1).strip()
            elif sec.strip().startswith('## 주제 목차'):
                outline_section = sec.replace('## 주제 목차', '### 주제 목차', 1).strip()
            elif sec.strip().startswith('## 녹취록'):
                transcript_section = sec.strip()
            elif sec.strip().startswith('## 관련 링크'):
                links_section = sec.strip()

        # Build Plaud content block
        plaud_content = ""
        if summary_section:
            plaud_content += summary_section + "\n\n"
        if outline_section:
            plaud_content += outline_section + "\n\n"
        if transcript_section:
            plaud_content += transcript_section + "\n\n"

        if new_path.exists():
            # Meeting note already exists — append Plaud content
            fm, body = read_note(new_path)

            # Merge participants from Plaud note
            plaud_participants = set(plaud_fm.get('participants', []))
            existing_participants = set(fm.get('participants', []))
            fm['participants'] = sorted(existing_participants | plaud_participants)

            # Insert plaud content after "## 논의 내용"
            heading = "## 논의 내용"
            idx = body.find(heading)
            if idx != -1:
                insert_pos = idx + len(heading)
                if insert_pos < len(body) and body[insert_pos] == '\n':
                    insert_pos += 1
                body = body[:insert_pos] + plaud_content + '\n' + body[insert_pos:]
            else:
                body += f"\n{heading}\n{plaud_content}\n"

            write_note(new_path, fm, body)
        else:
            # Create new meeting note with calendar info + Plaud content
            attendees = []
            for a in evt.get('attendees', []):
                email = a.get('email', '')
                name = resolve_name(email) if email else a.get('displayName', '')
                attendees.append(name)

            # Merge with Plaud-detected participants
            plaud_participants = plaud_fm.get('participants', [])

            fm = {
                'created': start.strftime('%Y-%m-%d %H:%M'),
                'participants': sorted(set(
                    [f'[[{a}]]' for a in attendees if a] + plaud_participants
                )),
                'type': 'meeting',
                'category': classify_meeting(title, [a.get('email', '') for a in evt.get('attendees', [])]),
                'gcal_id': evt['id'],
                'source': 'Plaud.ai',
            }

            # Calendar info block
            gcal_block = (
                f"- 일시: {start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%H:%M')}\n"
                f"- 장소: {evt.get('location', '')}\n"
                f"- 참석자: {', '.join(attendees) if attendees else '(없음)'}"
            )
            desc = evt.get('description', '')
            if desc:
                gcal_block += f"\n- 설명: {desc}"

            body = (
                f"\n# 회의: {title}\n\n"
                f"## 논의 내용\n"
                f"{gcal_block}\n\n"
                f"{plaud_content}"
                f"## 결정사항\n"
                f"- 결정: / 담당:\n\n"
                f"## 액션 아이템\n"
                f"- [ ] @담당자 — due:[[{start.strftime('%Y-%m-%d')}]]\n\n"
                f"## 다음 미팅\n"
                f"- 일정:\n"
                f"- 안건:\n"
            )

            write_note(new_path, fm, body)

        # Delete old Inbox file
        old_path.unlink()

        # Update state
        state['processed_recordings'][rec_id]['note_path'] = str(new_path)

        moved += 1
        logger.info(f"Moved: {old_path.name} → {new_path.name}")

    # Save updated state
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    logger.info(f"=== Done: {moved} moved, {errors} errors ===")


if __name__ == '__main__':
    main()
