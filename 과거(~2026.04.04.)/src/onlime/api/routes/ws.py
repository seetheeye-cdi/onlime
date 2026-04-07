"""WebSocket endpoint for real-time updates."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

# Connected clients
_clients: set[WebSocket] = set()


async def broadcast(data: dict):
    """Broadcast a message to all connected WebSocket clients."""
    if not _clients:
        return
    msg = json.dumps(data)
    disconnected = set()
    for ws in _clients:
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.add(ws)
    _clients -= disconnected


def broadcast_sync(data: dict):
    """Synchronous wrapper to broadcast from non-async code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast(data))
        else:
            loop.run_until_complete(broadcast(data))
    except RuntimeError:
        pass


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(_clients))

    try:
        # Send initial connection message
        await ws.send_text(
            json.dumps(
                {
                    "type": "connected",
                    "timestamp": datetime.now().isoformat(),
                    "message": "Connected to Onlime Studio",
                }
            )
        )

        # Keep connection alive and listen for messages
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                msg = json.loads(data)
                # Handle ping/pong
                if msg.get("type") == "ping":
                    await ws.send_text(
                        json.dumps({"type": "pong", "timestamp": datetime.now().isoformat()})
                    )
            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await ws.send_text(
                        json.dumps({"type": "heartbeat", "timestamp": datetime.now().isoformat()})
                    )
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        _clients.discard(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(_clients))
