"""Connector health checks."""
from __future__ import annotations

import logging

from onlime.connectors.registry import load_all, list_connectors, get_connector

logger = logging.getLogger(__name__)


def check_all() -> dict[str, bool]:
    """Check availability of all registered connectors.

    Returns dict of connector_name → is_available.
    """
    load_all()
    results = {}
    for name in list_connectors():
        try:
            conn = get_connector(name)
            results[name] = conn.is_available()
        except Exception as e:
            logger.warning(f"Health check failed for {name}: {e}")
            results[name] = False
    return results
