#!/usr/bin/env python3
"""Fix all meeting notes: correct participants + unified format."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from config import TIMEZONE, MEETING_DIR, resolve_name
from gcal_sync import parse_event_time, classify_meeting
from vault_io import read_note, write_note

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("fix_notes")
tz = ZoneInfo(TIMEZONE)


def get_correct_participants(event: dict | None, title: str) -> list[str]:
    """Determine correct participants from calendar event only."""
    participants = []

    if event and event.get('attendees'):
        for a in event['attendees']:
            email = a.get('email', '')
            if not email:
                continue
            name = resolve_name(email)
            participants.append(f'[[{name}]]')
    else:
        # No attendees list — extract person from meeting title + 최동인
        participants.append('[[최동인]]')
        # The title often IS the person's name or "person + topic"
        # Don't try to parse — just leave 최동인 as sole participant

    return sorted(set(participants))


def extract_plaud_content(body: str) -> str:
    """Extract Plaud content (AI summary, outline, transcript) from body."""
    content_parts = []

    # Find ### AI 요약 section
    ai_idx = body.find('### AI 요약')
    if ai_idx == -1:
        ai_idx = body.find('## AI 요약')

    # Find ### 주제 목차 or ## 주제 목차
    outline_idx = body.find('### 주제 목차')
    if outline_idx == -1:
        outline_idx = body.find('## 주제 목차')
    if outline_idx == -1:
        outline_idx = body.find('## 주요 주제')

    # Find ## 녹취록
    trans_idx = body.find('## 녹취록')

    # Collect all Plaud-generated content
    plaud_text = ""

    if ai_idx != -1:
        # Find end of AI summary (next ## or ### heading)
        end = len(body)
        for marker in ['### 주제 목차', '## 주제 목차', '## 주요 주제', '## 녹취록', '## 결정사항', '## 액션', '## 다음']:
            idx = body.find(marker, ai_idx + 10)
            if idx != -1 and idx < end:
                end = idx
        summary = body[ai_idx:end].strip()
        # Normalize to ### level
        summary = re.sub(r'^## AI 요약', '### AI 요약', summary)
        plaud_text += summary + "\n\n"

    if outline_idx != -1:
        end = len(body)
        for marker in ['## 녹취록', '## 결정사항', '## 액션', '## 다음']:
            idx = body.find(marker, outline_idx + 10)
            if idx != -1 and idx < end:
                end = idx
        outline = body[outline_idx:end].strip()
        # Normalize to ### level
        outline = re.sub(r'^## (주제 목차|주요 주제)', '### 주제 목차', outline)
        plaud_text += outline + "\n\n"

    if trans_idx != -1:
        end = len(body)
        for marker in ['## 결정사항', '## 액션', '## 다음 미팅']:
            idx = body.find(marker, trans_idx + 10)
            if idx != -1 and idx < end:
                end = idx
        transcript = body[trans_idx:end].strip()
        plaud_text += transcript + "\n\n"

    return plaud_text.strip()


def build_calendar_info(event: dict) -> str:
    """Build calendar info block."""
    if not event:
        return ""

    start = parse_event_time(event['start'])
    end = parse_event_time(event['end'])

    attendees = []
    for a in event.get('attendees', []):
        email = a.get('email', '')
        if email:
            attendees.append(resolve_name(email))

    info = f"- 일시: {start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%H:%M')}"
    loc = event.get('location', '')
    if loc:
        info += f"\n- 장소: {loc}"
    if attendees:
        info += f"\n- 참석자: {', '.join(attendees)}"
    desc = event.get('description', '')
    if desc:
        info += f"\n- 설명: {desc}"

    return info


def rebuild_note(fm: dict, body: str, event: dict | None, title: str) -> tuple[dict, str]:
    """Rebuild meeting note with correct participants and unified format."""
    # Fix participants
    fm['participants'] = get_correct_participants(event, title)

    # Remove tags that were incorrectly added from transcription scanning
    if 'tags' in fm:
        del fm['tags']

    # Extract Plaud content from existing body
    plaud_content = extract_plaud_content(body)

    # Build calendar info
    cal_info = build_calendar_info(event) if event else ""

    # Get date for action items
    if event:
        start = parse_event_time(event['start'])
        date_str = start.strftime('%Y-%m-%d')
    else:
        date_str = fm.get('created', 'YYYY-MM-DD')[:10]

    # Build clean body
    new_body = f"\n# 회의: {title}\n\n"
    new_body += "## 목표\n"
    new_body += "이번 미팅에서 달성할 것\n\n"
    new_body += "## 논의 내용\n"
    if cal_info:
        new_body += cal_info + "\n\n"
    if plaud_content:
        new_body += plaud_content + "\n\n"
    new_body += "## 결정사항\n"
    new_body += "- 결정: / 담당:\n\n"
    new_body += "## 액션 아이템\n"
    new_body += f"- [ ] [[담당자]] — due:[[{date_str}]]\n\n"
    new_body += "## 다음 미팅\n"
    new_body += "- 일정:\n"
    new_body += "- 안건:\n"

    return fm, new_body


def main():
    events = json.load(open('/tmp/gcal_events_full.json'))
    event_map = {e['id']: e for e in events}

    meeting_dir = Path(MEETING_DIR)
    fixed = 0

    for note_path in sorted(meeting_dir.glob('*_Meeting.md')):
        fm, body = read_note(note_path)
        title = note_path.stem.split('_', 1)[1] if '_' in note_path.stem else note_path.stem
        title = title.replace('_Meeting', '')

        # Find matching calendar event
        gcal_id = fm.get('gcal_id', '')
        event = event_map.get(gcal_id)

        new_fm, new_body = rebuild_note(fm, body, event, title)
        write_note(note_path, new_fm, new_body)
        fixed += 1

        n_participants = len(new_fm.get('participants', []))
        logger.info(f"Fixed: {note_path.name} ({n_participants} participants)")

    logger.info(f"=== Done: {fixed} notes fixed ===")


if __name__ == '__main__':
    main()
