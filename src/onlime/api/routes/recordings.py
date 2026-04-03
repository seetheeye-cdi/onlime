"""Plaud recordings endpoint."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Query

from onlime.api.models import RecordingResponse
from onlime.connectors.plaud import (
    fetch_recordings,
    parse_recording_time,
    get_recording_duration,
    get_recording_id,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/recordings/recent", response_model=list[RecordingResponse])
def get_recent_recordings(limit: int = Query(20, ge=1, le=100)):
    """Return recent Plaud recordings."""
    try:
        recordings = fetch_recordings(limit=limit)
    except Exception:
        logger.exception("Failed to fetch recordings")
        return []

    result = []
    for rec in recordings:
        ts = parse_recording_time(rec)
        duration = get_recording_duration(rec)
        file_id = get_recording_id(rec)

        # Check if it has a transcript
        data_list = rec.get("dataList", [])
        has_transcript = any(
            d.get("dataType") == "transaction" for d in data_list
        )

        result.append(
            RecordingResponse(
                id=file_id,
                title=rec.get("fileName", "Untitled"),
                duration_minutes=duration.total_seconds() / 60,
                created_at=ts.isoformat() if ts else "",
                has_transcript=has_transcript,
            )
        )

    return result
