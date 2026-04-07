"""Base processor ABC (Phase 2)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from onlime.connectors.base import ConnectorResult


@dataclass
class ProcessedResult:
    """Result of AI processing on a ConnectorResult."""
    original: ConnectorResult
    summary: str = ""
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    wiki_links: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseProcessor(ABC):
    """Abstract base class for AI processing steps."""

    @abstractmethod
    def process(self, result: ConnectorResult, **kwargs) -> ProcessedResult:
        ...
