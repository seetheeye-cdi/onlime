"""Base connector ABC and ConnectorResult dataclass."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ConnectorResult:
    """Normalized data returned by all connectors."""

    source_id: str
    source_type: str
    connector_name: str
    timestamp: datetime
    title: str
    content: str = ""
    participants: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_minutes: float | None = None
    raw: dict = field(default_factory=dict, repr=False)
    content_type: str = "message"
    file_path: str | None = None
    hashtags: list[str] = field(default_factory=list)


class BaseConnector(ABC):
    """Abstract base for all data source connectors.

    Supports both sync (fetch) and async (start/stop) lifecycle.
    Push-based connectors override start/stop; pull-based override fetch.
    """

    name: str = ""

    @abstractmethod
    def fetch(self, **kwargs: Any) -> list[ConnectorResult]:
        ...

    async def start(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Start a long-running push-based connector. Override in subclasses."""
        pass

    async def stop(self) -> None:
        """Stop the connector gracefully. Override in subclasses."""
        pass

    async def emit(self, event: dict[str, Any], queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Push an event to the Engine queue."""
        await queue.put(event)
        logger.debug("connector.emitted", connector=self.name, event_id=event.get("id"))

    def is_available(self) -> bool:
        return True
