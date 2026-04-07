"""FastAPI server for Onlime Studio."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from onlime.connectors.registry import load_all as load_connectors

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown logic."""
    # Load all connectors on startup
    load_connectors()
    logger.info("Onlime API server started")
    yield
    logger.info("Onlime API server shutting down")


app = FastAPI(
    title="Onlime Studio API",
    description="AI Workflow Dashboard Backend",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS -- defaults cover the Next.js dev server.
# Set ONLIME_CORS_ORIGINS (comma-separated) to add extra origins.
# WARNING: Using "*" with allow_credentials=True is insecure and rejected
# by browsers.  Use explicit origins instead.
_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
_env_cors = os.environ.get("ONLIME_CORS_ORIGINS", "").strip()
_cors_origins: list[str] = (
    [o.strip() for o in _env_cors.split(",") if o.strip()]
    if _env_cors
    else _DEFAULT_CORS_ORIGINS
)

# When wildcard "*" is in the origin list, credentials must be disabled
# to prevent cross-origin credential theft.
_has_wildcard = "*" in _cors_origins
if _has_wildcard:
    logger.warning(
        "CORS origin wildcard '*' detected. allow_credentials is forced to False. "
        "Use explicit origins if credential support is needed."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _has_wildcard,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# Register routes
from onlime.api.routes.connectors import router as connectors_router
from onlime.api.routes.sync import router as sync_router
from onlime.api.routes.notes import router as notes_router
from onlime.api.routes.calendar import router as calendar_router
from onlime.api.routes.recordings import router as recordings_router
from onlime.api.routes.chat import router as chat_router
from onlime.api.routes.ws import router as ws_router
from onlime.api.routes.ingest import router as ingest_router

app.include_router(connectors_router, prefix="/api", tags=["workers"])
app.include_router(sync_router, prefix="/api", tags=["sync"])
app.include_router(notes_router, prefix="/api", tags=["notes"])
app.include_router(calendar_router, prefix="/api", tags=["calendar"])
app.include_router(recordings_router, prefix="/api", tags=["recordings"])
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(ws_router, prefix="/api", tags=["websocket"])
app.include_router(ingest_router, prefix="/api", tags=["ingest"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "onlime-studio"}


def main():
    """Run the server directly."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)

    # Default to localhost for safety.  Set ONLIME_HOST=0.0.0.0 to listen
    # on all interfaces (requires ONLIME_API_KEY to be set for security).
    host = os.environ.get("ONLIME_HOST", "127.0.0.1")
    port = int(os.environ.get("ONLIME_PORT", "8000"))

    if host == "0.0.0.0" and not os.environ.get("ONLIME_API_KEY"):
        logger.warning(
            "Server binding to 0.0.0.0 without ONLIME_API_KEY set. "
            "The ingest endpoint will reject non-loopback requests. "
            "Set ONLIME_API_KEY for network access."
        )

    uvicorn.run(
        "onlime.api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
