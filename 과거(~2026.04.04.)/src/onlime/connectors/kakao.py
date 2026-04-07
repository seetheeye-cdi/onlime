"""KakaoTalk notification connector.

Receives notification data pushed from an Android phone via Termux,
parses it, and returns normalized ConnectorResult objects.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector, ConnectorResult
from onlime.connectors.registry import register

logger = logging.getLogger(__name__)

# Package name → app label mapping
PACKAGE_TO_APP = {
    "com.kakao.talk": "kakao",
    "com.Slack": "slack",
    "org.telegram.messenger": "telegram",
    "com.instagram.android": "instagram",
}

# Safety limits to prevent unbounded memory growth from sustained ingestion.
_MAX_SEEN_IDS = 50_000
_MAX_STORED_MESSAGES = 10_000


def _get_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().general.timezone)


def _message_hash(title: str, text: str, timestamp_ms: int) -> str:
    """Compute a stable deduplication key from title + text + timestamp.

    Matches the client-side fingerprint in termux_capture.py which uses
    title + content + when — keeping them aligned prevents false duplicates.
    """
    payload = f"{title}\x00{text}\x00{timestamp_ms}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _parse_notification(notification: dict, ignore_rooms: set[str] | None = None) -> ConnectorResult | None:
    """Convert a single Android notification dict to a ConnectorResult.

    Returns None if the notification cannot be parsed, has no text body,
    or belongs to an ignored room.
    """
    tz = _get_tz()

    package: str = notification.get("package", "")
    app = PACKAGE_TO_APP.get(package, "unknown")

    title: str = notification.get("title", "").strip()
    text: str = notification.get("text", "").strip()
    timestamp_ms: int = int(notification.get("timestamp", 0))
    extras: dict = notification.get("extras", {})

    if not text:
        logger.debug("Skipping notification with empty text: title=%r", title)
        return None

    # Resolve timestamp — fall back to now if missing / zero.
    if timestamp_ms:
        try:
            ts = datetime.fromtimestamp(timestamp_ms / 1000, tz=tz)
        except (ValueError, OSError):
            logger.warning("Invalid timestamp %d, using now", timestamp_ms)
            ts = datetime.now(tz=tz)
    else:
        ts = datetime.now(tz=tz)

    # App-specific room/sender parsing
    sub_text: str = extras.get("android.subText", "").strip()

    if app == "kakao":
        is_group = bool(sub_text)
        if is_group:
            room_name = sub_text
            raw_sender = title
        else:
            room_name = title
            raw_sender = title
    elif app == "slack":
        # Slack: title = "#channel" or "DM with Name", subText = workspace
        is_group = title.startswith("#")
        room_name = title
        raw_sender = sub_text or title
    elif app == "telegram":
        # Telegram: title = chat/group name, subText = sender in groups
        is_group = bool(sub_text)
        if is_group:
            room_name = title
            raw_sender = sub_text
        else:
            room_name = title
            raw_sender = title
    elif app == "instagram":
        # Instagram DM: title = sender name
        is_group = bool(sub_text)
        room_name = sub_text if is_group else title
        raw_sender = title
    else:
        is_group = bool(sub_text)
        room_name = sub_text if is_group else title
        raw_sender = title

    # Filter ignored rooms
    if ignore_rooms and room_name in ignore_rooms:
        logger.debug("Ignoring room %r (in ignore list)", room_name)
        return None

    # Prefer the full message body when available.
    big_text: str = extras.get("android.bigText", "").strip()
    content = big_text if big_text else text

    msg_hash = _message_hash(title, text, timestamp_ms)
    source_id = f"{app}_{msg_hash}"

    return ConnectorResult(
        source_id=source_id,
        source_type="message",
        connector_name=app,
        timestamp=ts,
        title=room_name,
        content=content,
        participants=[],
        metadata={
            "app": app,
            "room": room_name,
            "is_group": is_group,
            "raw_sender": raw_sender,
        },
        raw=notification,
    )


@register
class KakaoConnector(BaseConnector):
    """Connector for KakaoTalk notifications pushed from Android via Termux."""

    name = "kakao"

    def __init__(self) -> None:
        # In-memory store for notifications delivered via ingest().
        self._messages: list[dict] = []
        self._seen_ids: set[str] = set()
        self._lock = Lock()

        # Nickname → real name mapping.  Populated from config; can also be
        # patched directly for tests or runtime reconfiguration.
        settings = get_settings()
        self.nickname_to_name: dict[str, str] = {}

        # Seed from known_contacts list: treat each entry as both key and
        # value so that real names pass through unchanged.
        for contact in settings.names.known_contacts:
            self.nickname_to_name[contact] = contact

        # Apply explicit nickname → real name mappings from [kakao.nickname_to_name].
        self.nickname_to_name.update(settings.kakao.nickname_to_name)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def ingest(self, notifications: list[dict]) -> int:
        """Receive pushed notification dicts and store new ones.

        Accepts notifications from all configured messaging apps.
        Duplicates are silently dropped.  Returns the count of newly stored messages.

        Safety: evicts oldest entries when internal stores exceed size limits
        to prevent unbounded memory growth.
        """
        settings = get_settings()
        allowed_packages = set(settings.messaging.apps)

        added = 0
        with self._lock:
            for n in notifications:
                pkg = n.get("package", "")
                if pkg not in allowed_packages:
                    logger.debug(
                        "Ignoring notification from non-configured app: package=%r",
                        pkg,
                    )
                    continue

                title = n.get("title", "").strip()
                text = n.get("text", "").strip()
                ts_ms = int(n.get("timestamp", 0))
                msg_id = _message_hash(title, text, ts_ms)

                if msg_id in self._seen_ids:
                    logger.debug("Duplicate notification dropped: id=%s", msg_id)
                    continue

                self._seen_ids.add(msg_id)
                self._messages.append(n)
                added += 1

            # Evict oldest entries if stores exceed safety limits.
            if len(self._messages) > _MAX_STORED_MESSAGES:
                overflow = len(self._messages) - _MAX_STORED_MESSAGES
                self._messages = self._messages[overflow:]
                logger.warning(
                    "Message store exceeded %d limit, evicted %d oldest entries",
                    _MAX_STORED_MESSAGES,
                    overflow,
                )
            if len(self._seen_ids) > _MAX_SEEN_IDS:
                # Clear and rebuild from current messages to keep memory bounded.
                self._seen_ids.clear()
                for m in self._messages:
                    t = m.get("title", "").strip()
                    tx = m.get("text", "").strip()
                    ts = int(m.get("timestamp", 0))
                    self._seen_ids.add(_message_hash(t, tx, ts))
                logger.warning(
                    "Seen-ID set exceeded %d limit, rebuilt from %d stored messages",
                    _MAX_SEEN_IDS,
                    len(self._messages),
                )

        logger.info("ingest: accepted %d / %d notifications", added, len(notifications))
        return added

    def resolve_sender(self, nickname: str) -> str:
        """Map a KakaoTalk display name to a canonical real name.

        Uses NameResolver which auto-matches against:
        - contacts.csv (Google 연락처)
        - Obsidian People 폴더
        - onlime.toml 설정 (email_to_name, known_contacts)
        - [kakao.nickname_to_name] 수동 매핑 (최우선)

        Matching: 정확 매칭 → 존칭 제거 → 이름(성 제외) 매칭 → 부분 매칭
        """
        from onlime.names_resolver import get_resolver
        return get_resolver().resolve(nickname)

    def fetch(self, **kwargs) -> list[ConnectorResult]:
        """Return ConnectorResult objects for all ingested messages.

        The internal store is NOT cleared on fetch so that multiple consumers
        (e.g. the engine and an ad-hoc CLI call) both see the full history.
        Deduplication is handled at ingest time.
        """
        with self._lock:
            snapshot = list(self._messages)

        settings = get_settings()
        ignore_rooms = set(settings.messaging.ignore_rooms)

        results: list[ConnectorResult] = []
        for notification in snapshot:
            result = _parse_notification(notification, ignore_rooms=ignore_rooms)
            if result is None:
                continue

            # Resolve the raw sender to a canonical name and attach as
            # the sole participant.
            raw_sender = result.metadata.get("raw_sender", "")
            resolved = self.resolve_sender(raw_sender)
            result.participants = [resolved]

            results.append(result)

        logger.info("fetch: returning %d messages", len(results))
        return results

    def is_available(self) -> bool:
        """KakaoTalk connector is always available; it needs no external creds."""
        return True
