"""Base connector ABC and ConnectorResult dataclass."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ConnectorResult:
    """Normalized data returned by all connectors."""
    source_id: str
    source_type: str  # calendar, recording, message, activity
    connector_name: str
    timestamp: datetime
    title: str
    content: str = ""
    participants: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_minutes: float | None = None
    raw: dict = field(default_factory=dict, repr=False)


class BaseConnector(ABC):
    """Abstract base class for all data source connectors."""

    name: str = ""

    @abstractmethod
    def fetch(self, **kwargs) -> list[ConnectorResult]:
        """Fetch data from the source and return normalized results."""
        ...

    def is_available(self) -> bool:
        """Check if this connector is properly configured and ready."""
        return True
