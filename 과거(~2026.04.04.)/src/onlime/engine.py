"""Pipeline orchestrator — coordinates connectors, matching, and output formatting.

Ported from past/main.py with registry-based connector orchestration.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.gcal import (
    fetch_events, fetch_events_from_json, parse_event_time,
)
from onlime.connectors.plaud import (
    fetch_recordings, fetch_transcription, fetch_summary, fetch_outline,
    format_transcription, format_outline, get_recording_id, parse_recording_time,
)
from onlime.connectors.registry import load_all, get_connector
from onlime.outputs.meeting_note import sync_calendar_events, append_plaud_to_meeting
from onlime.outputs.daily_note import inject_schedule, filter_events_for_date
from onlime.outputs.kakao_digest import inject_kakao_digest
from onlime.outputs.standalone_note import create_standalone_transcript_note
from onlime.outputs.recording_note import create_recording_note
from onlime.state.store import SyncState
from onlime.vault.io import meeting_note_path, note_exists, read_note
from onlime.vault.matcher import match_recordings_to_events

logger = logging.getLogger("onlime")


def sync_plaud_to_notes(
    recordings: list[dict], events: list[dict],
    state: SyncState, dry_run: bool = False,
) -> None:
    """Match Plaud recordings to events and append transcriptions."""
    settings = get_settings()

    if not recordings:
        logger.info("No Plaud recordings to process")
        return

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

        segments = fetch_transcription(rec_id)
        if not segments:
            logger.debug(f"No transcription for recording {rec_id}, skipping")
            continue

        transcript_md = format_transcription(segments)
        summary_md = fetch_summary(rec_id) if rec.get("is_summary") else None
        outline = fetch_outline(rec_id)
        outline_md = format_outline(outline) if outline else None

        note_path = None

        if matched_event:
            title = matched_event.get('summary', 'Untitled Meeting')
            start = parse_event_time(matched_event['start'])
            date_str = start.strftime('%Y%m%d')
            note_path = meeting_note_path(settings.vault.meeting_path, date_str, title)

            if note_exists(note_path):
                append_plaud_to_meeting(
                    note_path, transcript_md, summary_md, outline_md, dry_run=dry_run,
                )
            else:
                logger.warning(f"Meeting note not found for {title}, creating standalone note")
                note_path = create_standalone_transcript_note(
                    rec, transcript_md, summary_md, outline_md, dry_run=dry_run,
                )
        else:
            note_path = create_standalone_transcript_note(
                rec, transcript_md, summary_md, outline_md, dry_run=dry_run,
            )

        if not dry_run:
            state.mark_recording_processed(
                rec_id,
                matched_event=matched_event.get('id') if matched_event else None,
                note_path=str(note_path) if note_path else None,
            )


def run_sync(
    *,
    only: list[str] | None = None,
    target_date: date | None = None,
    gcal_json: str | None = None,
    days: int = 7,
    dry_run: bool = False,
) -> None:
    """Run the full sync pipeline.

    Args:
        only: List of connector names to run (None = all)
        target_date: Specific date for daily note injection
        gcal_json: Path to JSON file with calendar events
        days: Number of days of recordings to process
        dry_run: Preview mode (no file changes)
    """
    settings = get_settings()
    load_all()

    if dry_run:
        logger.info("=== DRY-RUN MODE (파일 변경 없음) ===")

    state = SyncState(settings.state.state_file)
    events: list[dict] = []

    run_gcal = only is None or 'gcal' in only
    run_plaud = only is None or 'plaud' in only
    run_daily = only is None or 'daily' in only
    run_kakao = only is None or 'kakao' in only
    run_slack = only is None or 'slack' in only
    run_telegram = only is None or 'telegram' in only
    run_recording_sync = only is None or 'recording_sync' in only

    try:
        # Step 1: Google Calendar sync
        if run_gcal:
            logger.info("--- Google Calendar 동기화 ---")
            if gcal_json:
                events = fetch_events_from_json(gcal_json)
            else:
                events = fetch_events()

            if not (only and only == ['daily']):
                sync_calendar_events(events, state, dry_run=dry_run)
                if not dry_run:
                    state.update_last_gcal_sync()

        # Step 2: Plaud sync
        if run_plaud:
            logger.info("--- Plaud.ai 동기화 ---")
            tz = ZoneInfo(settings.general.timezone)
            recordings = fetch_recordings()

            if recordings and days:
                cutoff = datetime.now(tz) - timedelta(days=days)
                before = len(recordings)
                recordings = [
                    r for r in recordings
                    if (t := parse_recording_time(r)) and t >= cutoff
                ]
                logger.info(f"Filtered to {len(recordings)}/{before} recordings (last {days} days)")

            if recordings:
                if not events and run_gcal:
                    events = fetch_events()
                sync_plaud_to_notes(recordings, events, state, dry_run=dry_run)
                if not dry_run:
                    state.update_last_plaud_sync()

        # Step 3: Daily note schedule
        if run_daily:
            logger.info("--- 데일리노트 일정 삽입 ---")
            if not events:
                events = fetch_events()
            td = target_date or date.today()
            inject_schedule(events, td, dry_run=dry_run)

        # Step 4: KakaoTalk digest
        if run_kakao:
            logger.info("--- 메시지 다이제스트 ---")
            try:
                kakao = get_connector("kakao")
                messages = kakao.fetch()
                td = target_date or date.today()
                inject_kakao_digest(messages, td, dry_run=dry_run)
                if not dry_run:
                    for msg in messages:
                        if not state.is_processed("kakao", msg.source_id):
                            state.mark_processed("kakao", msg.source_id)
                    state.update_last_sync("kakao")
            except Exception as e:
                logger.error(f"카카오톡 동기화 실패: {e}", exc_info=True)

        # Step 5: Slack API sync
        if run_slack:
            logger.info("--- Slack 동기화 ---")
            try:
                slack_conn = get_connector("slack")
                if slack_conn.is_available():
                    slack_messages = slack_conn.fetch()
                    td = target_date or date.today()
                    inject_kakao_digest(slack_messages, td, dry_run=dry_run)
                    if not dry_run:
                        for msg in slack_messages:
                            if not state.is_processed("slack", msg.source_id):
                                state.mark_processed("slack", msg.source_id)
                        state.update_last_sync("slack")
                else:
                    logger.info("Slack not configured, skipping")
            except Exception as e:
                logger.error(f"Slack 동기화 실패: {e}", exc_info=True)

        # Step 6: Telegram API sync
        if run_telegram:
            logger.info("--- Telegram 동기화 ---")
            try:
                tg_conn = get_connector("telegram")
                if tg_conn.is_available():
                    tg_messages = tg_conn.fetch()
                    td = target_date or date.today()
                    inject_kakao_digest(tg_messages, td, dry_run=dry_run)
                    if not dry_run:
                        for msg in tg_messages:
                            if not state.is_processed("telegram", msg.source_id):
                                state.mark_processed("telegram", msg.source_id)
                        state.update_last_sync("telegram")
                else:
                    logger.info("Telegram not configured, skipping")
            except Exception as e:
                logger.error(f"Telegram 동기화 실패: {e}", exc_info=True)

        # Step 7: Phone recording sync
        if run_recording_sync:
            logger.info("--- 폰 녹음 동기화 ---")
            try:
                rec_conn = get_connector("recording_sync")
                if rec_conn.is_available():
                    rec_results = rec_conn.fetch()
                    for r in rec_results:
                        if not state.is_processed("recording_sync", r.source_id):
                            note_path = create_recording_note(r, dry_run=dry_run)
                            if not dry_run:
                                state.mark_processed(
                                    "recording_sync", r.source_id,
                                    note_path=str(note_path),
                                )
                    if not dry_run:
                        state.update_last_sync("recording_sync")
                else:
                    logger.info("Recording sync not enabled, skipping")
            except Exception as e:
                logger.error(f"폰 녹음 동기화 실패: {e}", exc_info=True)

        # Save state
        if not dry_run:
            state.save()

        logger.info("=== 동기화 완료 ===")

    except Exception as e:
        logger.error(f"동기화 실패: {e}", exc_info=True)
        raise
