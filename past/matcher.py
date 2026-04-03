"""Match Plaud recordings to Google Calendar events by time overlap."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import MIN_OVERLAP_RATIO, TIMEZONE
from gcal_sync import parse_event_time, is_all_day_event
from plaud_sync import parse_recording_time, get_recording_end_time, get_recording_duration

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)


def match_recordings_to_events(
    recordings: list[dict],
    events: list[dict],
) -> list[tuple[dict, dict | None, float]]:
    """
    Match Plaud recordings to Google Calendar events by time overlap.

    Returns: list of (recording, matched_event_or_None, overlap_seconds)
    """
    # Filter out all-day events (they can't be matched to recordings)
    timed_events = [e for e in events if not is_all_day_event(e)]

    matches = []

    for rec in recordings:
        rec_start = parse_recording_time(rec)
        if not rec_start:
            logger.warning(f"Cannot parse time for recording, skipping match")
            matches.append((rec, None, 0))
            continue

        rec_end = get_recording_end_time(rec)
        if not rec_end:
            rec_end = rec_start + get_recording_duration(rec)
        rec_duration = get_recording_duration(rec)

        best_match = None
        best_overlap = 0

        for evt in timed_events:
            try:
                evt_start = parse_event_time(evt['start'])
                evt_end = parse_event_time(evt['end'])
            except (KeyError, ValueError):
                continue

            # Calculate overlap
            overlap_start = max(rec_start, evt_start)
            overlap_end = min(rec_end, evt_end)
            overlap_secs = (overlap_end - overlap_start).total_seconds()

            if overlap_secs <= 0:
                continue

            # Check minimum overlap ratio
            rec_secs = rec_duration.total_seconds()
            evt_secs = (evt_end - evt_start).total_seconds()
            min_duration = min(rec_secs, evt_secs)

            if min_duration > 0 and overlap_secs >= MIN_OVERLAP_RATIO * min_duration:
                if overlap_secs > best_overlap:
                    best_overlap = overlap_secs
                    best_match = evt

        if best_match:
            logger.info(
                f"Matched recording to event '{best_match.get('summary', '?')}' "
                f"(overlap: {best_overlap:.0f}s)"
            )
        else:
            logger.debug("No calendar match for recording")

        matches.append((rec, best_match, best_overlap))

    return matches
