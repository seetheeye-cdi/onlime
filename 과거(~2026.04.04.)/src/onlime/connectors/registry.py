"""Connector auto-registration and discovery."""
from __future__ import annotations

from onlime.connectors.base import BaseConnector

_REGISTRY: dict[str, type[BaseConnector]] = {}
_INSTANCES: dict[str, BaseConnector] = {}


def register(cls: type[BaseConnector]) -> type[BaseConnector]:
    """Decorator to register a connector class."""
    _REGISTRY[cls.name] = cls
    return cls


def get_connector(name: str) -> BaseConnector:
    """Return the singleton instance for a registered connector.

    The instance is created on first call and cached so that all
    consumers (API routes, engine, etc.) share the same state.
    """
    if name not in _REGISTRY:
        raise KeyError(f"Unknown connector: {name}. Available: {list(_REGISTRY.keys())}")
    if name not in _INSTANCES:
        _INSTANCES[name] = _REGISTRY[name]()
    return _INSTANCES[name]


def list_connectors() -> list[str]:
    """Return names of all registered connectors."""
    return list(_REGISTRY.keys())


def load_all() -> None:
    """Import all connector modules to trigger registration."""
    from onlime.connectors import gcal, plaud, kakao, slack, telegram_conn, recording_sync  # noqa: F401
