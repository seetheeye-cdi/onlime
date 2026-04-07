"""Match Plaud recordings to Google Calendar events by time overlap.

Ported from past/matcher.py with settings integration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from onlime.config import get_settings

logger = logging.getLogger(__name__)


def match_recordings_to_events(
    recordings: list[dict],
    events: list[dict],
) -> list[tuple[dict, dict | None, float]]:
    """
    Match Plaud recordings to Google Calendar events by time overlap.

    Returns: list of (recording, matched_event_or_None, overlap_seconds)
    """
    from onlime.connectors.gcal import parse_event_time, is_all_day_event
    from onlime.connectors.plaud import parse_recording_time, get_recording_end_time, get_recording_duration

    settings = get_settings()
    min_overlap_ratio = settings.general.min_overlap_ratio

    timed_events = [e for e in events if not is_all_day_event(e)]
    matches = []

    for rec in recordings:
        rec_start = parse_recording_time(rec)
        if not rec_start:
            logger.warning("Cannot parse time for recording, skipping match")
            matches.append((rec, None, 0))
            continue

        rec_end = get_recording_end_time(rec)
        if not rec_end:
            rec_end = rec_start + get_recording_duration(rec)
        rec_duration = get_recording_duration(rec)

        best_match = None
        best_overlap = 0.0

        for evt in timed_events:
            try:
                evt_start = parse_event_time(evt['start'])
                evt_end = parse_event_time(evt['end'])
            except (KeyError, ValueError):
                continue

            overlap_start = max(rec_start, evt_start)
            overlap_end = min(rec_end, evt_end)
            overlap_secs = (overlap_end - overlap_start).total_seconds()

            if overlap_secs <= 0:
                continue

            rec_secs = rec_duration.total_seconds()
            evt_secs = (evt_end - evt_start).total_seconds()
            min_duration = min(rec_secs, evt_secs)

            if min_duration > 0 and overlap_secs >= min_overlap_ratio * min_duration:
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
