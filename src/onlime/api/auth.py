"""API key authentication dependency."""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import Header, HTTPException, Request

logger = logging.getLogger(__name__)

_API_KEY: str | None = os.environ.get("ONLIME_API_KEY")

# Minimum key length to prevent trivially guessable keys.
_MIN_KEY_LENGTH = 16

if not _API_KEY:
    logger.warning(
        "ONLIME_API_KEY is not set -- authentication is DISABLED. "
        "Set ONLIME_API_KEY (>= %d chars) before exposing the server on a network.",
        _MIN_KEY_LENGTH,
    )
elif len(_API_KEY) < _MIN_KEY_LENGTH:
    logger.warning(
        "ONLIME_API_KEY is only %d characters. Use >= %d characters for adequate security.",
        len(_API_KEY),
        _MIN_KEY_LENGTH,
    )


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    """FastAPI dependency that validates the X-API-Key header.

    When ONLIME_API_KEY env var is unset, only requests from loopback
    addresses (127.0.0.1 / ::1) are allowed (safe dev mode).
    Raises HTTP 401 when the key is present in env but the request key
    is missing or does not match.
    """
    if not _API_KEY:
        # Dev mode: allow only loopback connections when no key is set.
        client_host = request.client.host if request.client else ""
        if client_host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "ONLIME_API_KEY is not configured and request is from "
                    "a non-loopback address. Set ONLIME_API_KEY to allow "
                    "remote connections."
                ),
            )
        return

    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    if not secrets.compare_digest(_API_KEY, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
