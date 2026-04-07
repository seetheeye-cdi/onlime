"""Slack Web API connector — push-based poller using bot token."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector
from onlime.connectors.registry import register
from onlime.models import ContentType, SourceType
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()

_MAX_RETRIES = 5
_SYSTEM_SUBTYPES = frozenset({
    "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "bot_add", "bot_remove",
})


# ---------- helpers (reused from archived slack.py) ----------


def _strip_mrkdwn(text: str) -> str:
    """Convert Slack mrkdwn to plain text."""
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<([^>]+)>", r"\1", text)
    return text


def _call_with_retry(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a Slack API method with automatic rate-limit retry."""
    for attempt in range(_MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "ratelimited" in str(e).lower():
                retry_after = 5
                try:
                    retry_after = int(e.response.headers.get("Retry-After", 5))
                except (AttributeError, ValueError, TypeError):
                    pass
                wait = max(retry_after, 2) + 1
                logger.info("slack.rate_limited", wait=wait, attempt=attempt + 1)
                time.sleep(wait)
                continue
            raise
    return func(*args, **kwargs)


# ---------- sync API wrappers (run in thread) ----------


def _resolve_user(client: Any, user_id: str, cache: dict[str, str]) -> str:
    """Resolve a Slack user ID to display name, with caching."""
    if user_id in cache:
        return cache[user_id]
    try:
        resp = _call_with_retry(client.users_info, user=user_id)
        if resp["ok"]:
            profile = resp["user"].get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or resp["user"].get("name", user_id)
            )
            cache[user_id] = name
            return name
    except Exception:
        logger.debug("slack.resolve_user_failed", user_id=user_id)
    cache[user_id] = user_id
    return user_id


def _fetch_channels(client: Any, sync_channels: list[str]) -> list[dict]:
    """Get list of joined channels/DMs."""
    channels: list[dict] = []
    cursor = None
    while True:
        kwargs: dict[str, Any] = {
            "types": "public_channel,private_channel,mpim,im",
            "exclude_archived": True,
            "limit": 200,
        }
        if cursor:
            kwargs["cursor"] = cursor
        resp = _call_with_retry(client.conversations_list, **kwargs)
        if not resp["ok"]:
            logger.error("slack.conversations_list_failed", error=resp.get("error"))
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


def _channel_display_name(client: Any, ch: dict, user_cache: dict[str, str]) -> str:
    """Return display name for a channel dict."""
    if ch.get("is_im"):
        user_id = ch.get("user", "")
        return _resolve_user(client, user_id, user_cache)
    if ch.get("is_mpim"):
        return ch.get("name", ch["id"])
    return f"#{ch.get('name', ch['id'])}"


def _fetch_history(client: Any, channel_id: str, oldest_ts: float) -> list[dict]:
    """Fetch message history for a channel with pagination."""
    messages: list[dict] = []
    cursor = None
    while True:
        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "oldest": str(oldest_ts),
            "limit": 200,
        }
        if cursor:
            kwargs["cursor"] = cursor
        try:
            resp = _call_with_retry(client.conversations_history, **kwargs)
        except Exception as e:
            logger.warning("slack.history_failed", channel=channel_id, error=str(e))
            break
        if not resp["ok"]:
            break
        messages.extend(resp.get("messages", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(1)
    return messages


def _fetch_thread_replies(client: Any, channel_id: str, thread_ts: str, oldest_ts: float) -> list[dict]:
    """Fetch all replies in a thread (excluding parent)."""
    replies: list[dict] = []
    cursor = None
    while True:
        kwargs: dict[str, Any] = {
            "channel": channel_id,
            "ts": thread_ts,
            "oldest": str(oldest_ts),
            "limit": 200,
        }
        if cursor:
            kwargs["cursor"] = cursor
        try:
            resp = _call_with_retry(client.conversations_replies, **kwargs)
        except Exception:
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


def _collect_channel_messages(
    client: Any,
    ch: dict,
    oldest_ts: float,
    user_cache: dict[str, str],
    tz: ZoneInfo,
) -> dict[str, list[str]]:
    """Collect all messages for a channel, grouped by date string (YYYY-MM-DD).

    Returns {date_str: [formatted_lines]}.
    """
    ch_id = ch["id"]
    room_name = _channel_display_name(client, ch, user_cache)

    top_messages = _fetch_history(client, ch_id, oldest_ts)
    all_messages = list(top_messages)

    # Fetch thread replies
    for msg in top_messages:
        reply_count = msg.get("reply_count", 0)
        if reply_count and reply_count > 0:
            thread_ts = msg.get("thread_ts") or msg.get("ts")
            replies = _fetch_thread_replies(client, ch_id, thread_ts, oldest_ts)
            all_messages.extend(replies)
            time.sleep(1.2)

    # Group by date
    by_date: dict[str, list[tuple[float, str]]] = {}
    for msg in all_messages:
        subtype = msg.get("subtype", "")
        if subtype in _SYSTEM_SUBTYPES:
            continue
        text = msg.get("text", "")
        if not text:
            continue

        msg_ts = float(msg.get("ts", "0"))
        dt = datetime.fromtimestamp(msg_ts, tz=tz)
        date_str = dt.strftime("%Y-%m-%d")

        user_id = msg.get("user", "")
        sender = _resolve_user(client, user_id, user_cache) if user_id else (msg.get("username") or "bot")
        content = _strip_mrkdwn(text)
        time_str = dt.strftime("%H:%M")

        thread_marker = " (thread)" if msg.get("_thread_ts") else ""
        line = f"[{time_str}] {sender}{thread_marker}: {content}"

        by_date.setdefault(date_str, []).append((msg_ts, line))

    # Sort each date's messages by timestamp, return formatted lines
    result: dict[str, list[str]] = {}
    for date_str, entries in by_date.items():
        entries.sort(key=lambda x: x[0])
        result[date_str] = [line for _, line in entries]

    return result


# ---------- connector ----------


@register
class SlackConnector(BaseConnector):
    """Push-based Slack connector that polls channels on an interval."""

    name = "slack"

    def __init__(self) -> None:
        self._user_cache: dict[str, str] = {}
        self._channel_last_ts: dict[str, float] = {}
        self._poll_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None

    def fetch(self, **kwargs: Any) -> list:
        return []

    async def start(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        token = get_secret_or_env("slack-bot-token", "SLACK_BOT_TOKEN")
        if not token:
            raise RuntimeError("Slack bot token not found in Keychain or env")
        self._queue = queue
        self._poll_task = asyncio.create_task(self._poll_loop(token))
        logger.info("slack.started")

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("slack.stopped")

    async def _poll_loop(self, token: str) -> None:
        settings = get_settings()
        tz = ZoneInfo(settings.general.timezone)
        poll_seconds = settings.slack.poll_interval_minutes * 60

        # First run: look back sync_days_back
        oldest = datetime.now(tz) - timedelta(days=settings.slack.sync_days_back)
        initial_oldest_ts = oldest.timestamp()

        first_run = True
        while True:
            try:
                await self._poll_once(token, settings, tz, initial_oldest_ts if first_run else None)
                first_run = False
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("slack.poll_failed")

            await asyncio.sleep(poll_seconds)

    async def _poll_once(
        self,
        token: str,
        settings: Any,
        tz: ZoneInfo,
        override_oldest_ts: float | None = None,
    ) -> None:
        """Run one poll cycle — channels processed concurrently (5 at a time)."""
        from slack_sdk import WebClient

        client = WebClient(token=token)

        channels = await asyncio.to_thread(
            _fetch_channels, client, settings.slack.sync_channels,
        )
        logger.info("slack.poll", channels=len(channels))

        sem = asyncio.Semaphore(5)

        async def _process_channel(ch: dict) -> None:
            async with sem:
                ch_id = ch["id"]
                oldest_ts = override_oldest_ts or self._channel_last_ts.get(ch_id, 0)

                # Each thread gets its own client to avoid contention
                thread_client = WebClient(token=token)
                by_date = await asyncio.to_thread(
                    _collect_channel_messages, thread_client, ch, oldest_ts, self._user_cache, tz,
                )

                room_name = _channel_display_name(thread_client, ch, self._user_cache)

                for date_str, lines in by_date.items():
                    if not lines:
                        continue

                    raw_content = f"[Slack] {room_name} — {date_str}\n\n" + "\n".join(lines)
                    event_id = f"slack:{ch_id}:{date_str}"

                    event_dict: dict[str, Any] = {
                        "id": event_id,
                        "source": SourceType.SLACK.value,
                        "content_type": ContentType.MESSAGE.value,
                        "raw_content": raw_content,
                        "timestamp": datetime.strptime(date_str, "%Y-%m-%d")
                        .replace(tzinfo=tz)
                        .isoformat(),
                        "metadata": {
                            "room": room_name,
                            "channel_id": ch_id,
                            "message_count": len(lines),
                        },
                    }

                    await self.emit(event_dict, self._queue)

                self._channel_last_ts[ch_id] = datetime.now(tz).timestamp()
                logger.info("slack.channel_done", channel=room_name)

        await asyncio.gather(*[_process_channel(ch) for ch in channels])
