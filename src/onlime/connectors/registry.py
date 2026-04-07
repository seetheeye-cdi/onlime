"""Connector registry with @register decorator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onlime.connectors.base import BaseConnector

_registry: dict[str, type[BaseConnector]] = {}
_instances: dict[str, BaseConnector] = {}


def register(cls: type[BaseConnector]) -> type[BaseConnector]:
    """Class decorator to register a connector."""
    name = cls.name or cls.__name__.lower().replace("connector", "")
    _registry[name] = cls
    return cls


def get_connector(name: str) -> BaseConnector:
    """Get or create a singleton connector instance."""
    if name not in _instances:
        if name not in _registry:
            raise KeyError(f"Unknown connector: {name}")
        _instances[name] = _registry[name]()
    return _instances[name]


def list_connectors() -> list[str]:
    return list(_registry.keys())
