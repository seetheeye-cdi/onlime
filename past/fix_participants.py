#!/usr/bin/env python3
"""Fix meeting note participants: extract names from title (surname-based) + calendar attendees."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import MEETING_DIR, resolve_name
from vault_io import read_note, write_note

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("fix_participants")

VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
PEOPLE_DIR = VAULT_ROOT / "0. INPUT" / "People"

# Common Korean surnames
SURNAMES = set("김이박최정강조윤장임한오서신권황안송류유홍전고문양손배백허나추하주우곽성차방노하심민진엄원천석")

# Words that look like names but aren't
NOT_NAMES = {
    '박사님', '의원실', '위원장', '국회의원', '대표', '개발자', '변호사',
    '선악의', '넥스트', '디자인', '리브랜딩', '커피챗',
}


def build_name_map() -> dict[str, str]:
    """Build {short_name: vault_note_stem} from People folder."""
    name_map = {}
    for f in PEOPLE_DIR.glob("*.md"):
        stem = f.stem
        if "Template" in stem:
            continue
        clean = re.sub(r'^[🙍‍♂️👤\s]+', '', stem)
        primary = re.split(r'[_(,]', clean)[0].strip()
        if primary and len(primary) >= 2:
            name_map[primary] = stem
    return name_map


def is_korean_name(word: str) -> bool:
    """Check if a word looks like a Korean person name (surname + 2-char given name = 3 chars)."""
    if not word or len(word) != 3:
        return False
    if word in NOT_NAMES:
        return False
    # First char must be a known Korean surname
    if word[0] not in SURNAMES:
        return False
    # All chars must be Korean
    if not all('\uac00' <= c <= '\ud7a3' for c in word):
        return False
    return True


def extract_names_from_title(title: str) -> list[str]:
    """Extract Korean person names from meeting title using surname detection."""
    names = []

    # Split title into words
    words = re.split(r'[\s,/X&()]+', title)

    for word in words:
        word = word.strip()
        if is_korean_name(word):
            names.append(word)

    # Deduplicate
    seen = set()
    result = []
    for n in names:
        if n not in seen:
            seen.add(n)
            result.append(n)

    return result


def name_to_link(name: str, name_map: dict[str, str]) -> str:
    """Convert a name to an Obsidian wiki-link."""
    if name in name_map:
        vault_stem = name_map[name]
        if vault_stem == name:
            return f"[[{name}]]"
        return f"[[{vault_stem}|{name}]]"
    return f"[[{name}]]"


def main():
    events = json.load(open('/tmp/gcal_events_full.json'))
    event_map = {e['id']: e for e in events}
    name_map = build_name_map()
    logger.info(f"Loaded {len(name_map)} vault person names")

    meeting_dir = Path(MEETING_DIR)
    fixed = 0

    for note_path in sorted(meeting_dir.glob('*_Meeting.md')):
        fm, body = read_note(note_path)

        # Get title from filename
        stem = note_path.stem
        parts = stem.split('_', 1)
        if len(parts) < 2:
            continue
        title = parts[1].replace('_Meeting', '').replace('_', ' ')

        # Determine participants
        gcal_id = fm.get('gcal_id', '')
        event = event_map.get(gcal_id)

        participants = set()
        participants.add('[[최동인]]')

        # From calendar attendees (only resolved Korean names)
        if event and event.get('attendees'):
            for a in event['attendees']:
                email = a.get('email', '')
                if email:
                    name = resolve_name(email)
                    # Skip if name looks like email-derived (contains dots, all ASCII, etc.)
                    if re.match(r'^[a-zA-Z0-9. _]+$', name):
                        continue
                    participants.add(name_to_link(name, name_map))

        # From title (surname-based name detection)
        title_names = extract_names_from_title(title)
        for name in title_names:
            if name == '최동인':
                continue
            participants.add(name_to_link(name, name_map))

        participants = sorted(participants)

        # Update if changed
        old_participants = fm.get('participants', [])
        if participants != old_participants:
            fm['participants'] = participants
            write_note(note_path, fm, body)
            fixed += 1
            logger.info(f"Fixed: {note_path.name} → {[p for p in participants if p != '[[최동인]]']}")

    logger.info(f"=== Done: {fixed} notes updated ===")


if __name__ == '__main__':
    main()
