"""Categorizer: route events to vault subfolders via hashtags or source rules."""

from __future__ import annotations

import re

import structlog

from onlime.config import get_settings
from onlime.models import ContentType, RawEvent, SourceType

logger = structlog.get_logger()

# Source-based fallback mapping
_SOURCE_DEFAULTS: dict[str, str] = {
    SourceType.KAKAO: "1.INPUT/Inbox",
    SourceType.SLACK: "1.INPUT/Inbox",
    SourceType.TELEGRAM: "1.INPUT/Inbox",
    SourceType.GCAL: "1.INPUT/Meeting",
    SourceType.WEB: "1.INPUT/Article",
    SourceType.YOUTUBE: "1.INPUT/Media",
    SourceType.VOICE: "1.INPUT/Recording",
    SourceType.GDRIVE: "1.INPUT/Recording",
    SourceType.MANUAL: "1.INPUT/Inbox",
}

# Content-type overrides (applied after source default, before hashtag)
_CONTENT_DEFAULTS: dict[str, str] = {
    ContentType.ARTICLE: "1.INPUT/Article",
    ContentType.VIDEO: "1.INPUT/Media",
    ContentType.CALENDAR: "1.INPUT/Meeting",
    ContentType.VOICE: "1.INPUT/Recording",
    # LINK stays Inbox — community posts and unclassified URLs land here
    ContentType.LINK: "1.INPUT/Inbox",
}

_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def extract_hashtags(text: str) -> list[str]:
    """Extract hashtags from text, lowercased with # prefix."""
    return [f"#{m.group(1).lower()}" for m in _HASHTAG_RE.finditer(text)]


def categorize(event: RawEvent) -> str:
    """Determine vault subfolder for an event.

    Priority: hashtag route > content-type default > source default > inbox.
    """
    settings = get_settings()
    routes = settings.routing.routes

    # 1. Check hashtags in raw_content + metadata
    hashtags = extract_hashtags(event.raw_content)
    hashtags.extend(event.metadata.get("hashtags", []))

    for tag in hashtags:
        tag_lower = tag.lower()
        if tag_lower in routes:
            folder = routes[tag_lower]
            logger.info("categorizer.hashtag_match", tag=tag_lower, folder=folder)
            return folder

    # 2. Content-type default
    if event.content_type in _CONTENT_DEFAULTS:
        return _CONTENT_DEFAULTS[event.content_type]

    # 3. Source-based default
    if event.source in _SOURCE_DEFAULTS:
        return _SOURCE_DEFAULTS[event.source]

    # 4. Fallback
    return "1.INPUT/Inbox"
