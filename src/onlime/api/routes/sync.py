"""Sync execution endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks

from onlime.api.models import SyncRequest, SyncResult, SyncEventOut
from onlime.engine import run_sync

logger = logging.getLogger(__name__)
router = APIRouter()

# Track running syncs
_running_syncs: dict[str, bool] = {}


def _run_sync_task(connectors: list[str] | None):
    """Run sync in background thread."""
    key = ",".join(connectors) if connectors else "all"
    _running_syncs[key] = True
    try:
        run_sync(only=connectors)
    except Exception:
        logger.exception("Sync failed")
    finally:
        _running_syncs.pop(key, None)


@router.post("/sync/run", response_model=SyncResult)
def trigger_sync(req: SyncRequest, bg: BackgroundTasks):
    """Trigger a sync run (async in background)."""
    key = ",".join(req.connectors) if req.connectors else "all"

    if _running_syncs.get(key):
        return SyncResult(
            success=False,
            message="Sync already in progress",
        )

    bg.add_task(_run_sync_task, req.connectors)

    return SyncResult(
        success=True,
        message=f"Sync started for: {key}",
        events=[
            SyncEventOut(
                action="sync_started",
                detail=f"Connectors: {key}",
                timestamp=datetime.now().isoformat(),
            )
        ],
    )
