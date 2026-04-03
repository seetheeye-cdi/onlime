#!/usr/bin/env python3
"""Process ALL Plaud recordings → Obsidian notes with vault linking."""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    STATE_FILE, TIMEZONE, MEETING_DIR, INBOX_DIR, STATE_DIR, LOG_FILE,
    resolve_name,
)
from state import SyncState
from gcal_sync import fetch_events_from_json, parse_event_time, sync_calendar_events
from plaud_sync import (
    fetch_recordings, fetch_transcription, fetch_summary, fetch_outline,
    format_transcription, format_outline, get_recording_id,
    parse_recording_time, get_recording_end_time,
    create_standalone_transcript_note,
)
from matcher import match_recordings_to_events
from vault_io import (
    read_note, write_note, meeting_note_path, note_exists,
)

# ── Logging ──────────────────────────────────────────────────────────
STATE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
    ],
)
logger = logging.getLogger("process_all_plaud")
tz = ZoneInfo(TIMEZONE)

# ── Vault knowledge base ─────────────────────────────────────────────
VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
PEOPLE_DIR = VAULT_ROOT / "0. INPUT" / "People"

def load_vault_people() -> dict[str, str]:
    """Load people notes → {short_name: vault_note_stem}."""
    people = {}
    if not PEOPLE_DIR.exists():
        return people
    for f in PEOPLE_DIR.glob("*.md"):
        stem = f.stem
        if stem.startswith("인물 Template"):
            continue
        # Extract clean name: remove emoji prefixes and suffixes like _description
        clean = re.sub(r'^[🙍‍♂️👤\s]+', '', stem)
        # Primary name (before first underscore/parenthesis)
        primary = re.split(r'[_(]', clean)[0].strip()
        if primary and len(primary) >= 2:
            people[primary] = stem
    return people


# Key projects and their vault note names
PROJECTS = {
    '참치': '참치상사',
    '참치상사': '참치상사',
    '민심맨': '참치_민심맨',
    '에이아이당': '에이아이당',
    'AI당': '에이아이당',
    '더해커톤': '더해커톤 THEHACKATHON',
    '해커톤': '더해커톤 THEHACKATHON',
    '넥스트노벨': '넥스트노벨 NEXTNOBEL.org',
    '이준석': '🙍‍♂️이준석',
    '개혁신당': '개혁신당',
    '한성': '한성',
    'VMC': 'VMC',
    '옥소폴리틱스': '유호현_옥소폴리틱스 대표',
}


def find_vault_links(text: str, people: dict[str, str]) -> tuple[list[str], list[str]]:
    """Scan text for people and project mentions. Return (people_links, project_links)."""
    found_people = []
    found_projects = []

    # Check people (longer names first to avoid partial matches)
    for name in sorted(people.keys(), key=len, reverse=True):
        if len(name) < 2:
            continue
        if name in text:
            vault_name = people[name]
            link = f"[[{vault_name}|{name}]]" if vault_name != name else f"[[{name}]]"
            if link not in found_people:
                found_people.append(link)

    # Check projects
    for keyword, vault_name in PROJECTS.items():
        if keyword in text:
            link = f"[[{vault_name}]]"
            if link not in found_projects:
                found_projects.append(link)

    return found_people, found_projects


def process_recording(rec, matched_event, state, people_map, dry_run=False) -> Path | None:
    """Process a single Plaud recording into a note."""
    rec_id = get_recording_id(rec)
    if not rec_id:
        return None

    if state.is_recording_processed(rec_id):
        return None

    # Fetch transcription
    segments = fetch_transcription(rec_id)
    if not segments:
        logger.debug(f"No transcription for {rec_id}, skipping")
        return None

    transcript_md = format_transcription(segments)

    # Fetch summary and outline
    summary_md = fetch_summary(rec_id) if rec.get("is_summary") else None
    outline = fetch_outline(rec_id)
    outline_md = format_outline(outline) if outline else None

    # Build full transcript text for vault linking
    full_text = ""
    if summary_md:
        full_text += summary_md
    for seg in segments:
        full_text += " " + seg.get("content", "")

    people_links, project_links = find_vault_links(full_text, people_map)

    note_path = None

    if matched_event:
        # Insert into matched meeting note
        title = matched_event.get('summary', 'Untitled Meeting')
        start = parse_event_time(matched_event['start'])
        date_str = start.strftime('%Y%m%d')
        note_path = meeting_note_path(MEETING_DIR, date_str, title)

        if note_exists(note_path):
            fm, body = read_note(note_path)

            plaud_content = ""
            if summary_md:
                plaud_content += f"### AI 요약\n{summary_md}\n\n"
            if outline_md:
                plaud_content += outline_md + "\n\n"
            plaud_content += transcript_md

            # Add vault links to frontmatter
            if people_links:
                existing = set(fm.get('participants', []))
                for link in people_links:
                    if link not in existing:
                        existing.add(link)
                fm['participants'] = sorted(existing)

            if project_links:
                existing_tags = set(fm.get('tags', []) or [])
                for link in project_links:
                    existing_tags.add(link)
                fm['tags'] = sorted(existing_tags)

            # Insert after "## 논의 내용"
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
            logger.info(f"{'[DRY] ' if dry_run else ''}Appended transcript → {note_path.name}")
        else:
            logger.warning(f"Meeting note not found for {title}, creating standalone")
            note_path = _create_enhanced_standalone(
                rec, transcript_md, summary_md, outline_md,
                people_links, project_links, dry_run,
            )
    else:
        note_path = _create_enhanced_standalone(
            rec, transcript_md, summary_md, outline_md,
            people_links, project_links, dry_run,
        )

    if not dry_run and note_path:
        state.mark_recording_processed(
            rec_id,
            matched_event=matched_event.get('id') if matched_event else None,
            note_path=str(note_path),
        )

    return note_path


def _create_enhanced_standalone(
    rec, transcript_md, summary_md, outline_md,
    people_links, project_links, dry_run,
) -> Path | None:
    """Create standalone Plaud note with vault links."""
    rec_time = parse_recording_time(rec)
    if not rec_time:
        return None

    filename = rec.get("filename", "녹음")
    # Extract title from AI summary first line or filename
    title = filename
    if summary_md:
        first_line = summary_md.strip().split('\n')[0]
        # Remove markdown heading markers
        clean_title = re.sub(r'^#+\s*', '', first_line).strip()
        if clean_title and len(clean_title) < 80:
            title = clean_title

    date_str = rec_time.strftime('%Y%m%d')
    date_short = rec_time.strftime('%m-%d')
    safe_title = re.sub(r'[/\\:*?"<>|]', '', title).strip()
    safe_title = re.sub(r'\s+', ' ', safe_title)
    # Truncate long titles
    if len(safe_title) > 60:
        safe_title = safe_title[:57] + "..."

    note_name = f"{date_str}_{date_short} {safe_title}_Plaud.md"
    note_path = INBOX_DIR / note_name

    # Build frontmatter
    fm = {
        'created': rec_time.strftime('%Y-%m-%d %H:%M'),
        'type': 'plaud-transcript',
        'source': 'Plaud.ai',
    }
    if people_links:
        fm['participants'] = people_links
    if project_links:
        fm['tags'] = project_links

    # Build body
    body = f"\n# {title}\n\n"

    if summary_md:
        body += f"## AI 요약\n{summary_md}\n\n"

    if outline_md:
        body += f"## 주제 목차\n{outline_md}\n\n"

    # Related links section
    if people_links or project_links:
        body += "## 관련 링크\n"
        if people_links:
            body += "- 인물: " + ", ".join(people_links) + "\n"
        if project_links:
            body += "- 프로젝트: " + ", ".join(project_links) + "\n"
        body += "\n"

    body += f"## 녹취록\n{transcript_md}\n"

    if not dry_run:
        note_path.parent.mkdir(parents=True, exist_ok=True)
        write_note(note_path, fm, body)

    logger.info(f"{'[DRY] ' if dry_run else ''}Created: {note_path.name}")
    return note_path


def main():
    logger.info("=== 전체 Plaud 녹음 처리 시작 ===")

    # Load vault people
    people_map = load_vault_people()
    logger.info(f"Loaded {len(people_map)} people from vault")

    # Load calendar events (Jan 1 ~ now)
    events = fetch_events_from_json('/tmp/gcal_events_full.json')
    logger.info(f"Loaded {len(events)} calendar events")

    # Load state
    state = SyncState(STATE_FILE)
    already_done = len(state.data.get('processed_recordings', {}))
    logger.info(f"Already processed: {already_done} recordings")

    # Fetch ALL Plaud recordings
    recordings = fetch_recordings()
    logger.info(f"Total Plaud recordings: {len(recordings)}")

    # Filter to only transcribed ones
    trans_recs = [r for r in recordings if r.get("is_trans")]
    logger.info(f"Transcribed recordings: {len(trans_recs)}")

    # Skip already processed
    to_process = []
    for r in trans_recs:
        rid = get_recording_id(r)
        if rid and not state.is_recording_processed(rid):
            to_process.append(r)
    logger.info(f"To process: {len(to_process)} recordings")

    if not to_process:
        logger.info("Nothing new to process!")
        return

    # Match ALL recordings to events
    matches = match_recordings_to_events(to_process, events)
    matched_count = sum(1 for _, evt, _ in matches if evt)
    logger.info(f"Matched to calendar events: {matched_count}/{len(matches)}")

    # Process each recording
    created = 0
    errors = 0
    for i, (rec, matched_event, overlap) in enumerate(matches, 1):
        rec_id = get_recording_id(rec)
        rec_time = parse_recording_time(rec)
        time_str = rec_time.strftime('%Y-%m-%d %H:%M') if rec_time else '?'
        fname = rec.get('filename', '?')

        logger.info(f"[{i}/{len(matches)}] {time_str} — {fname}")

        try:
            note_path = process_recording(rec, matched_event, state, people_map)
            if note_path:
                created += 1
        except Exception as e:
            logger.error(f"  Error: {e}", exc_info=True)
            errors += 1

        # Save state periodically (every 5 recordings)
        if i % 5 == 0:
            state.save()
            logger.info(f"  [checkpoint] State saved ({created} created, {errors} errors)")

        # Small delay to avoid rate limiting
        time.sleep(0.3)

    # Final save
    state.save()
    logger.info(f"=== 완료: {created} notes created, {errors} errors, {len(matches) - created - errors} skipped ===")


if __name__ == '__main__':
    main()
