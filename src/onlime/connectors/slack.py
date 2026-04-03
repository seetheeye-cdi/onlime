"""Slack Web API connector — fetches full message history via bot token."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector, ConnectorResult
from onlime.connectors.registry import register

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5


def _strip_mrkdwn(text: str) -> str:
    """Convert Slack mrkdwn to plain text."""
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<([^>]+)>", r"\1", text)
    return text


def _call_with_retry(func, *args, **kwargs):
    """Call a Slack API method with automatic rate-limit retry."""
    for attempt in range(_MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_str = str(e)
            if "ratelimited" in err_str.lower():
                # Extract Retry-After from the SlackApiError response
                retry_after = 5  # default
                try:
                    retry_after = int(e.response.headers.get("Retry-After", 5))
                except (AttributeError, ValueError, TypeError):
                    pass
                wait = max(retry_after, 2) + 1
                logger.info("Rate limited, waiting %ds (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
                continue
            raise
    # Final attempt without catching
    return func(*args, **kwargs)


@register
class SlackConnector(BaseConnector):
    """Connector that pulls messages from Slack via the Web API."""

    name = "slack"

    def __init__(self) -> None:
        self._user_cache: dict[str, str] = {}

    def is_available(self) -> bool:
        settings = get_settings()
        return bool(settings.slack.bot_token)

    def _get_client(self):
        from slack_sdk import WebClient

        settings = get_settings()
        return WebClient(token=settings.slack.bot_token)

    def _resolve_user(self, client, user_id: str) -> str:
        """Resolve a Slack user ID to a display name, with caching."""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            resp = _call_with_retry(client.users_info, user=user_id)
            if resp["ok"]:
                profile = resp["user"].get("profile", {})
                name = (
                    profile.get("display_name")
                    or profile.get("real_name")
                    or resp["user"].get("name", user_id)
                )
                self._user_cache[user_id] = name
                return name
        except Exception:
            logger.debug("Failed to resolve user %s", user_id)
        self._user_cache[user_id] = user_id
        return user_id

    def _fetch_channels(self, client, sync_channels: list[str]) -> list[dict]:
        """Get list of joined channels/DMs to sync."""
        channels = []
        cursor = None
        while True:
            kwargs = {
                "types": "public_channel,private_channel,mpim,im",
                "exclude_archived": True,
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor
            resp = _call_with_retry(client.conversations_list, **kwargs)
            if not resp["ok"]:
                logger.error("conversations_list failed: %s", resp.get("error"))
                break
            for ch in resp["channels"]:
                if ch.get("is_member") or ch.get("is_im") or ch.get("is_mpim"):
                    if sync_channels:
                        ch_name = ch.get("name") or ch.get("id")
                        if ch_name not in sync_channels and ch["id"] not in sync_channels:
                            continue
                    channels.append(ch)
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return channels

    def _channel_display_name(self, client, ch: dict) -> tuple[str, bool]:
        """Return (display_name, is_group) for a channel dict."""
        if ch.get("is_im"):
            user_id = ch.get("user", "")
            name = self._resolve_user(client, user_id)
            return name, False
        if ch.get("is_mpim"):
            return ch.get("name", ch["id"]), True
        return f"#{ch.get('name', ch['id'])}", True

    def _fetch_history(self, client, channel_id: str, oldest_ts: float) -> list[dict]:
        """Fetch message history for a channel with pagination."""
        messages = []
        cursor = None
        while True:
            kwargs = {
                "channel": channel_id,
                "oldest": str(oldest_ts),
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = _call_with_retry(client.conversations_history, **kwargs)
            except Exception as e:
                logger.warning("conversations_history failed for %s: %s", channel_id, e)
                break
            if not resp["ok"]:
                logger.warning("conversations_history error for %s: %s", channel_id, resp.get("error"))
                break
            messages.extend(resp.get("messages", []))
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(1)
        return messages

    def _fetch_thread_replies(self, client, channel_id: str, thread_ts: str, oldest_ts: float) -> list[dict]:
        """Fetch all replies in a thread (excluding the parent message)."""
        replies = []
        cursor = None
        while True:
            kwargs = {
                "channel": channel_id,
                "ts": thread_ts,
                "oldest": str(oldest_ts),
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor
            try:
                resp = _call_with_retry(client.conversations_replies, **kwargs)
            except Exception as e:
                logger.warning("conversations_replies failed for thread %s: %s", thread_ts, e)
                break
            if not resp["ok"]:
                break
            for msg in resp.get("messages", []):
                if msg.get("ts") == thread_ts:
                    continue
                msg["_thread_ts"] = thread_ts
                replies.append(msg)
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(1)
        return replies

    def fetch(self, **kwargs) -> list[ConnectorResult]:
        settings = get_settings()
        if not self.is_available():
            logger.warning("Slack bot_token not configured, skipping")
            return []

        client = self._get_client()
        tz = ZoneInfo(settings.general.timezone)
        days_back = settings.slack.sync_days_back
        oldest = datetime.now(tz) - timedelta(days=days_back)
        oldest_ts = oldest.timestamp()

        channels = self._fetch_channels(client, settings.slack.sync_channels)
        logger.info("Slack: syncing %d channels", len(channels))

        results: list[ConnectorResult] = []

        for ch_idx, ch in enumerate(channels):
            ch_id = ch["id"]
            room_name, is_group = self._channel_display_name(client, ch)
            logger.info("Slack: [%d/%d] %s", ch_idx + 1, len(channels), room_name)

            top_messages = self._fetch_history(client, ch_id, oldest_ts)
            logger.info("  본문 %d건, 스레드 수집 중...", len(top_messages))

            messages = list(top_messages)
            thread_count = 0
            for msg in top_messages:
                reply_count = msg.get("reply_count", 0)
                thread_ts = msg.get("thread_ts") or msg.get("ts")
                if reply_count and reply_count > 0:
                    replies = self._fetch_thread_replies(client, ch_id, thread_ts, oldest_ts)
                    messages.extend(replies)
                    thread_count += len(replies)
                    # Pace between thread fetches
                    time.sleep(1.2)

            logger.info("  스레드 답글 %d건 추가", thread_count)

            for msg in messages:
                subtype = msg.get("subtype", "")
                if subtype in (
                    "channel_join", "channel_leave", "channel_topic",
                    "channel_purpose", "channel_name", "bot_add", "bot_remove",
                ):
                    continue

                text = msg.get("text", "")
                if not text and not msg.get("files"):
                    continue

                msg_ts = msg.get("ts", "0")
                try:
                    ts = datetime.fromtimestamp(float(msg_ts), tz=tz)
                except (ValueError, OSError):
                    ts = datetime.now(tz=tz)

                user_id = msg.get("user", "")
                sender = self._resolve_user(client, user_id) if user_id else (msg.get("username") or "bot")

                content = _strip_mrkdwn(text)
                source_id = f"slack_{hashlib.sha256(f'{ch_id}_{msg_ts}'.encode()).hexdigest()[:16]}"

                is_thread_reply = bool(msg.get("_thread_ts"))
                metadata: dict = {
                    "app": "slack",
                    "room": room_name,
                    "is_group": is_group,
                    "raw_sender": sender,
                    "is_thread_reply": is_thread_reply,
                }
                if is_thread_reply:
                    metadata["thread_ts"] = msg["_thread_ts"]

                files = msg.get("files", [])
                if files:
                    metadata["files"] = [
                        {"name": f.get("name", ""), "url": f.get("url_private", "")}
                        for f in files
                    ]

                results.append(ConnectorResult(
                    source_id=source_id,
                    source_type="message",
                    connector_name="slack",
                    timestamp=ts,
                    title=room_name,
                    content=content,
                    participants=[sender],
                    metadata=metadata,
                    raw=msg,
                ))

            time.sleep(1)

        logger.info("Slack: fetched %d messages from %d channels", len(results), len(channels))
        return results
