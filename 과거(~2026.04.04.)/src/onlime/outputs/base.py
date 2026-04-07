"""Base output formatter ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from onlime.connectors.base import ConnectorResult


class BaseOutputFormatter(ABC):
    """Abstract base class for Obsidian output formatters."""

    @abstractmethod
    def format(self, result: ConnectorResult, **kwargs) -> tuple[dict, str]:
        """Format a ConnectorResult into (frontmatter, body) for an Obsidian note."""
        ...

    @abstractmethod
    def get_output_path(self, result: ConnectorResult, **kwargs) -> Path:
        """Determine the output file path for this result."""
        ...
