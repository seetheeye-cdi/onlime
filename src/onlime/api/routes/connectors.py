"""Worker status endpoints."""

from __future__ import annotations

import logging
from fastapi import APIRouter

from onlime.api.models import WorkerStatusResponse
from onlime.connectors.registry import list_connectors, get_connector
from onlime.config.settings import get_settings
from onlime.state.store import SyncState

logger = logging.getLogger(__name__)
router = APIRouter()

WORKER_NAMES = {
    "gcal": "GCal Worker",
    "plaud": "Plaud Worker",
    "daily": "Daily Note Worker",
    "ai": "AI Assistant",
}


def _get_state() -> SyncState:
    settings = get_settings()
    return SyncState(settings.state.state_file)


@router.get("/workers", response_model=list[WorkerStatusResponse])
def get_workers():
    """Return list of all workers with their status."""
    state = _get_state()
    registered = list_connectors()
    workers = []

    for wid, name in WORKER_NAMES.items():
        available = False
        last_sync = None
        error_message = None

        if wid in registered:
            try:
                conn = get_connector(wid)
                available = conn.is_available()
            except Exception as e:
                error_message = str(e)

            # Pull last sync from state
            connector_state = state._data.get("connectors", {}).get(wid, {})
            last_sync = connector_state.get("last_sync")
        elif wid == "daily":
            available = True  # Daily note worker is always available
        elif wid == "ai":
            available = True  # AI worker available if API key set

        workers.append(
            WorkerStatusResponse(
                id=wid,
                name=name,
                status="error" if error_message else "idle",
                last_sync=last_sync,
                error_message=error_message,
                is_available=available,
            )
        )

    return workers


@router.get("/workers/{worker_id}/status", response_model=WorkerStatusResponse)
def get_worker_status(worker_id: str):
    """Return detailed status for a specific worker."""
    state = _get_state()
    name = WORKER_NAMES.get(worker_id, worker_id)
    registered = list_connectors()

    available = False
    last_sync = None
    error_message = None

    if worker_id in registered:
        try:
            conn = get_connector(worker_id)
            available = conn.is_available()
        except Exception as e:
            error_message = str(e)

        connector_state = state._data.get("connectors", {}).get(worker_id, {})
        last_sync = connector_state.get("last_sync")
    elif worker_id in ("daily", "ai"):
        available = True

    return WorkerStatusResponse(
        id=worker_id,
        name=name,
        status="error" if error_message else "idle",
        last_sync=last_sync,
        error_message=error_message,
        is_available=available,
    )
