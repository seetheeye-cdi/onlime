"""Core data models for the Onlime pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    KAKAO = "kakao"
    SLACK = "slack"
    TELEGRAM = "telegram"
    GDRIVE = "gdrive"
    WEB = "web"
    YOUTUBE = "youtube"
    GCAL = "gcal"
    VOICE = "voice"
    MANUAL = "manual"


class ContentType(str, Enum):
    MESSAGE = "message"
    VOICE = "voice"
    FILE = "file"
    LINK = "link"
    CALENDAR = "calendar"
    ARTICLE = "article"
    VIDEO = "video"


@dataclass
class RawEvent:
    """Raw event produced by connectors."""

    id: str
    source: SourceType
    content_type: ContentType
    raw_content: str  # text or file path
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessedEvent:
    """Processed event after pipeline stages."""

    raw_event_id: str
    title: str
    summary: str
    full_text: str
    category: str  # folder mapping
    timestamp: datetime = field(default_factory=datetime.now)
    tags: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    vault_path: str | None = None
