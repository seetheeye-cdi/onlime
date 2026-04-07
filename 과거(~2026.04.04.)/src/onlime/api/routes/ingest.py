"""Notification ingest endpoint for Android push data."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from onlime.api.auth import require_api_key
from onlime.api.models import IngestRequest, IngestResponse
from onlime.config import get_settings
from onlime.connectors.registry import get_connector

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ingest/notifications", response_model=IngestResponse)
def ingest_notifications(
    req: IngestRequest,
    _: None = Depends(require_api_key),
) -> IngestResponse:
    """Receive a batch of Android notifications from a Termux device.

    Accepts notifications from all configured messaging apps (kakao, slack,
    telegram, instagram).  Unconfigured packages are skipped.
    """
    settings = get_settings()
    allowed = set(settings.messaging.apps)

    matching = [n for n in req.notifications if n.package in allowed]

    total = len(req.notifications)
    matched_count = len(matching)
    skipped = total - matched_count

    if skipped:
        logger.debug(
            "device=%s: skipped %d notifications from non-configured apps",
            req.device_id,
            skipped,
        )

    # Convert Pydantic models to plain dicts as expected by connector.ingest().
    raw_payloads = [
        {
            "package": n.package,
            "title": n.title,
            "text": n.text,
            "timestamp": n.timestamp,
            "extras": n.extras,
        }
        for n in matching
    ]

    connector = get_connector("kakao")
    accepted = connector.ingest(raw_payloads)
    duplicates = matched_count - accepted

    logger.info(
        "device=%s: received=%d matched=%d accepted=%d duplicates=%d",
        req.device_id,
        total,
        matched_count,
        accepted,
        duplicates,
    )

    # Inject digest into daily note immediately after successful ingest.
    if accepted > 0:
        try:
            from onlime.outputs.kakao_digest import inject_kakao_digest
            messages = connector.fetch()
            inject_kakao_digest(messages)
        except Exception as exc:
            logger.warning("Failed to inject digest into daily note: %s", exc)

    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        message=(
            f"Accepted {accepted} notification(s), "
            f"{duplicates} duplicate(s) ignored."
        ),
    )
