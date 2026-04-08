"""Slack Web API connector — polls channels and writes daily digest note."""

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
from onlime.llm import LLMError, call_llm
from onlime.outputs.vault import atomic_write
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()

_MAX_RETRIES = 5
_SYSTEM_SUBTYPES = frozenset({
    "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "bot_add", "bot_remove",
})

# Digest: backfill at most 7 days on first run
_DIGEST_BACKFILL_DAYS = 7

_DIGEST_PROMPT = (
    "다음은 Slack 워크스페이스의 하루 대화 내용입니다.\n"
    "채널별로 핵심 업무/논의 내용을 1~2줄로 요약해주세요.\n"
    "잡담/인사 등 중요하지 않은 대화는 과감히 생략하세요.\n"
    "형식: `- **#채널명**: 요약 내용`\n"
    "한 문장당 한 줄로 작성하세요.\n\n"
    "{text}"
)


# ---------- helpers ----------


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


# ---------- digest note helpers ----------


def _upsert_date_section(content: str, date_str: str, summary: str) -> str:
    """Insert or replace a ## YYYY-MM-DD section in the digest note."""
    section_header = f"## {date_str}"

    if section_header in content:
        # Replace existing section
        lines = content.split("\n")
        new_lines: list[str] = []
        i = 0
        replaced = False
        while i < len(lines):
            if lines[i].strip() == section_header and not replaced:
                new_lines.append(section_header)
                new_lines.append("")
                new_lines.append(summary)
                new_lines.append("")
                # Skip old section body
                i += 1
                while i < len(lines) and not lines[i].startswith("## "):
                    i += 1
                replaced = True
                continue
            new_lines.append(lines[i])
            i += 1
        return "\n".join(new_lines)
    else:
        # Insert in reverse-chronological order (newest first, after frontmatter)
        lines = content.split("\n")

        # Find end of frontmatter
        fm_end = 0
        fm_count = 0
        for idx, line in enumerate(lines):
            if line.strip() == "---":
                fm_count += 1
                if fm_count == 2:
                    fm_end = idx + 1
                    break

        # Find insertion point: before first ## with an older date
        insert_at = len(lines)
        for idx in range(fm_end, len(lines)):
            if lines[idx].startswith("## "):
                existing_date = lines[idx].strip()[3:]
                if existing_date < date_str:
                    insert_at = idx
                    break

        new_section = ["", section_header, "", summary, ""]
        lines[insert_at:insert_at] = new_section
        return "\n".join(lines)


# ---------- connector ----------


@register
class SlackConnector(BaseConnector):
    """Slack connector that writes daily digest notes per workspace."""

    name = "slack"

    def __init__(self) -> None:
        self._user_cache: dict[str, str] = {}
        self._poll_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._workspace_name: str = "Slack"

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

        first_run = True
        while True:
            try:
                await self._poll_once(token, settings, tz, first_run)
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
        first_run: bool = False,
    ) -> None:
        """Poll all channels, summarize by date, write digest note."""
        from slack_sdk import WebClient

        client = WebClient(token=token)

        # Resolve workspace name once
        try:
            auth = await asyncio.to_thread(client.auth_test)
            if auth["ok"]:
                self._workspace_name = auth.get("team", "Slack")
        except Exception:
            pass

        channels = await asyncio.to_thread(
            _fetch_channels, client, settings.slack.sync_channels,
        )
        logger.info("slack.poll", channels=len(channels))

        now = datetime.now(tz)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if first_run:
            # Backfill last N days (cap regardless of sync_days_back)
            oldest_ts = (now - timedelta(days=_DIGEST_BACKFILL_DAYS)).timestamp()
        else:
            # Re-fetch full today for up-to-date digest
            oldest_ts = today_midnight.timestamp()

        # Collect messages from all channels
        all_data: dict[str, dict[str, list[str]]] = {}  # date -> channel -> lines
        sem = asyncio.Semaphore(5)

        async def _collect_channel(ch: dict) -> tuple[str, dict[str, list[str]]]:
            async with sem:
                thread_client = WebClient(token=token)
                by_date = await asyncio.to_thread(
                    _collect_channel_messages, thread_client, ch,
                    oldest_ts, self._user_cache, tz,
                )
                room_name = _channel_display_name(thread_client, ch, self._user_cache)
                return room_name, by_date

        results = await asyncio.gather(*[_collect_channel(ch) for ch in channels])

        for room_name, by_date in results:
            for date_str, lines in by_date.items():
                if lines:
                    all_data.setdefault(date_str, {})[room_name] = lines

        if not all_data:
            logger.info("slack.no_messages")
            return

        await self._write_digest(all_data, settings, tz)
        logger.info(
            "slack.digest_written",
            dates=len(all_data),
            workspace=self._workspace_name,
        )

    # ---------- digest writing ----------

    async def _write_digest(
        self,
        data: dict[str, dict[str, list[str]]],
        settings: Any,
        tz: ZoneInfo,
    ) -> None:
        """Write/update the single digest note with date sections."""
        vault_root = settings.vault.root.expanduser()
        digest_dir = vault_root / "1.INPUT" / "Slack"
        ws = self._workspace_name
        digest_path = digest_dir / f"{ws}.md"

        today_str = datetime.now(tz).strftime("%Y-%m-%d")

        if digest_path.exists():
            content = digest_path.read_text(encoding="utf-8")
        else:
            content = (
                f"---\ntitle: {ws} Slack\ntype: slack-digest\n---\n"
            )

        for date_str in sorted(data.keys(), reverse=True):
            section_header = f"## {date_str}"

            # Skip existing past dates (already finalized)
            if section_header in content and date_str != today_str:
                continue

            channels = data[date_str]
            raw_text = self._format_day_text(channels)
            if not raw_text.strip():
                continue

            summary = await self._summarize_day(raw_text, channels)
            content = _upsert_date_section(content, date_str, summary)

        atomic_write(digest_path, content)

    @staticmethod
    def _format_day_text(channels: dict[str, list[str]]) -> str:
        """Format all channels' messages into text for LLM summarization."""
        parts: list[str] = []
        for ch_name, lines in sorted(channels.items()):
            parts.append(f"### {ch_name}")
            parts.extend(lines[:50])  # cap per channel to control tokens
            parts.append("")
        return "\n".join(parts)

    @staticmethod
    async def _summarize_day(
        raw_text: str, channels: dict[str, list[str]],
    ) -> str:
        """Summarize a day's Slack conversations with LLM."""
        prompt = _DIGEST_PROMPT.format(text=raw_text[:6000])
        try:
            return await call_llm(prompt, max_tokens=1024, caller="slack_digest")
        except LLMError:
            logger.warning("slack.digest_summarize_failed")
            # Fallback: list channels with message counts
            lines = []
            for ch_name, msgs in sorted(channels.items()):
                lines.append(f"- **{ch_name}**: {len(msgs)}건 대화")
            return "\n".join(lines)
