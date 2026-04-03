#!/usr/bin/env python3
"""
obsidian-sync: Google Calendar + Plaud.ai → Obsidian vault 자동 동기화.

Usage:
    python main.py                    # 전체 동기화 (캘린더 + Plaud + 데일리노트)
    python main.py --calendar-only    # 캘린더만
    python main.py --plaud-only       # Plaud만
    python main.py --daily-only       # 데일리노트만
    python main.py --date 2026-03-15  # 특정 날짜
    python main.py --gcal-json FILE   # JSON 파일에서 캘린더 이벤트 읽기
    python main.py --dry-run          # 미리보기 (파일 변경 없음)
"""
import argparse
import logging
import sys
import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure project dir is in path
sys.path.insert(0, str(Path(__file__).parent))

from config import STATE_FILE, TIMEZONE, MEETING_DIR, LOG_FILE, STATE_DIR
from state import SyncState
from gcal_sync import fetch_events, fetch_events_from_json, sync_calendar_events, parse_event_time
from plaud_sync import (
    fetch_recordings, fetch_transcription, fetch_summary, fetch_outline,
    format_transcription, format_outline, get_recording_id,
    parse_recording_time, create_standalone_transcript_note,
)
from matcher import match_recordings_to_events
from daily_note import inject_schedule, filter_events_for_date
from vault_io import read_note, write_note, meeting_note_path, note_exists

logger = logging.getLogger("obsidian-sync")
tz = ZoneInfo(TIMEZONE)


def setup_logging(verbose: bool = False):
    """Configure logging to both console and file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    # File handler
    file_handler = logging.FileHandler(str(LOG_FILE), encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)


def notify_error(message: str):
    """Send macOS notification on error."""
    try:
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "obsidian-sync 오류"'
        ], capture_output=True, timeout=5)
    except Exception:
        pass


def sync_plaud_to_notes(recordings, events, state, dry_run=False):
    """Match Plaud recordings to events and append transcriptions."""
    if not recordings:
        logger.info("No Plaud recordings to process")
        return

    # Only process recordings that have transcription
    trans_recordings = [r for r in recordings if r.get("is_trans")]
    if not trans_recordings:
        logger.info("No transcribed recordings to process")
        return

    matches = match_recordings_to_events(trans_recordings, events)

    for rec, matched_event, overlap in matches:
        rec_id = get_recording_id(rec)
        if not rec_id:
            continue

        if state.is_recording_processed(rec_id):
            continue

        # Fetch transcription segments from S3
        segments = fetch_transcription(rec_id)
        if not segments:
            logger.debug(f"No transcription for recording {rec_id}, skipping")
            continue

        transcript_md = format_transcription(segments)

        # Fetch summary and outline
        summary_md = fetch_summary(rec_id) if rec.get("is_summary") else None
        outline = fetch_outline(rec_id)
        outline_md = format_outline(outline) if outline else None

        note_path = None

        if matched_event:
            # Append transcription to the matched meeting note
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

                # Insert after "## 논의 내용" heading
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
            else:
                logger.warning(f"Meeting note not found for {title}, creating standalone note")
                note_path = create_standalone_transcript_note(
                    rec, transcript_md, summary_md, outline_md, dry_run=dry_run,
                )
        else:
            # No match → standalone note in Inbox
            note_path = create_standalone_transcript_note(
                rec, transcript_md, summary_md, outline_md, dry_run=dry_run,
            )

        if not dry_run:
            state.mark_recording_processed(
                rec_id,
                matched_event=matched_event.get('id') if matched_event else None,
                note_path=str(note_path) if note_path else None,
            )


def main():
    parser = argparse.ArgumentParser(description='Obsidian Calendar + Plaud Sync')
    parser.add_argument('--calendar-only', action='store_true', help='캘린더만 동기화')
    parser.add_argument('--plaud-only', action='store_true', help='Plaud만 동기화')
    parser.add_argument('--daily-only', action='store_true', help='데일리노트만 업데이트')
    parser.add_argument('--date', type=str, help='대상 날짜 (YYYY-MM-DD)')
    parser.add_argument('--gcal-json', type=str, help='JSON 파일에서 캘린더 이벤트 읽기')
    parser.add_argument('--dry-run', action='store_true', help='미리보기 (파일 변경 없음)')
    parser.add_argument('--days', type=int, default=7, help='최근 N일 녹음만 처리 (기본: 7)')
    parser.add_argument('--verbose', '-v', action='store_true', help='상세 로그')
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.dry_run:
        logger.info("=== DRY-RUN MODE (파일 변경 없음) ===")

    state = SyncState(STATE_FILE)
    events = []

    try:
        # Step 1: Google Calendar sync
        if not args.plaud_only:
            logger.info("--- Google Calendar 동기화 ---")
            if args.gcal_json:
                events = fetch_events_from_json(args.gcal_json)
            else:
                events = fetch_events()

            if not args.daily_only:
                sync_calendar_events(events, state, dry_run=args.dry_run)
                if not args.dry_run:
                    state.update_last_gcal_sync()

        # Step 2: Plaud sync
        if not args.calendar_only and not args.daily_only:
            logger.info("--- Plaud.ai 동기화 ---")
            recordings = fetch_recordings()
            # Filter to recent recordings only
            if recordings and args.days:
                from datetime import timedelta as td
                cutoff = datetime.now(tz) - td(days=args.days)
                before = len(recordings)
                recordings = [
                    r for r in recordings
                    if (t := parse_recording_time(r)) and t >= cutoff
                ]
                logger.info(f"Filtered to {len(recordings)}/{before} recordings (last {args.days} days)")
            if recordings:
                # Need events for matching
                if not events and not args.plaud_only:
                    events = fetch_events()
                sync_plaud_to_notes(recordings, events, state, dry_run=args.dry_run)
                if not args.dry_run:
                    state.update_last_plaud_sync()

        # Step 3: Daily note schedule
        if not args.plaud_only and not args.calendar_only or args.daily_only:
            logger.info("--- 데일리노트 일정 삽입 ---")
            if not events:
                events = fetch_events()
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date() if args.date else date.today()
            inject_schedule(events, target_date, dry_run=args.dry_run)

        # Save state
        if not args.dry_run:
            state.save()

        logger.info("=== 동기화 완료 ===")

    except Exception as e:
        logger.error(f"동기화 실패: {e}", exc_info=True)
        notify_error(str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
