"""Periodic KakaoTalk sync — consolidated per-chat vault files.

Runs as a background asyncio task inside the Onlime daemon. Every interval it:

1. Fetches all DM chats and configured group chats via kakaocli.
2. Creates/updates ONE .md file per chat room in 1.INPUT/Inbox/.
3. Each file shows participants, message counts, and recent conversation.

This bypasses the engine pipeline (no summarisation) — the user explicitly
requested consolidated raw-message files, not daily fragment notes.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from onlime.config import get_settings
from onlime.maintenance.base import BackgroundTask

logger = structlog.get_logger()

# Characters forbidden by Obsidian Sync on mobile
_FORBIDDEN_CHARS = set('?"*|<>:\\')


def _sanitize_filename(name: str) -> str:
    """Remove Obsidian-forbidden chars from filename."""
    out = "".join(" " if c in _FORBIDDEN_CHARS else c for c in name)
    out = out.replace("/", "-")
    # Collapse whitespace, strip trailing dots/spaces
    out = " ".join(out.split())
    out = out.rstrip(". ")
    return out or "unnamed"


def _find_kakaocli() -> str | None:
    return shutil.which("kakaocli")


def _get_key() -> str:
    """Get the DB key from Keychain."""
    from onlime.security.secrets import get_secret_or_env

    key = get_secret_or_env("kakao-db-key", "KAKAO_DB_KEY")
    if not key:
        raise RuntimeError("kakao-db-key not found in Keychain")
    return key


async def _run_kakaocli(binary: str, args: list[str]) -> str:
    """Run kakaocli and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        binary, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"kakaocli {args[0]} failed: {stderr.decode()[:200]}")
    return stdout.decode()


async def _fetch_chats(binary: str, key: str) -> list[dict[str, Any]]:
    """Fetch all chats."""
    out = await _run_kakaocli(binary, ["chats", "--limit", "200", "--json", "--key", key])
    return json.loads(out)


async def _fetch_messages(
    binary: str, key: str, chat_id: int, limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch recent messages for a chat."""
    try:
        out = await _run_kakaocli(binary, [
            "messages", "--chat-id", str(chat_id),
            "--limit", str(limit), "--json", "--key", key,
        ])
        return json.loads(out)
    except Exception:
        return []


def _format_messages(messages: list[dict[str, Any]]) -> str:
    """Format messages grouped by date."""
    by_date: dict[str, list[str]] = defaultdict(list)
    for m in messages:
        ts = m.get("timestamp", "")
        date = ts[:10] if ts else "unknown"
        time = ts[11:16] if ts else "??:??"
        sender = m.get("sender", "(me)")
        content = m.get("text", "").strip()
        if not content:
            msg_type = m.get("type", "")
            content = f"[{msg_type}]" if msg_type else ""
        by_date[date].append(f"- **{time}** {sender}: {content}")

    lines = []
    for date in sorted(by_date.keys(), reverse=True):
        lines.append(f"\n### {date}")
        for msg in by_date[date]:
            lines.append(msg)
    return "\n".join(lines)


def _participant_stats(messages: list[dict[str, Any]]) -> dict[str, int]:
    """Count messages per sender."""
    counts: dict[str, int] = defaultdict(int)
    for m in messages:
        counts[m.get("sender", "(me)")] += 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def _write_chat_file(
    out_dir: Path,
    chat_id: int,
    name: str,
    chat_type: str,
    messages: list[dict[str, Any]],
) -> Path | None:
    """Write a consolidated .md file for one chat."""
    if not messages:
        return None

    stats = _participant_stats(messages)
    dates = [m.get("timestamp", "")[:10] for m in messages if m.get("timestamp")]
    date_range = f"{min(dates)} ~ {max(dates)}" if dates else "N/A"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    content = f"""---
type: kakao-{"group" if chat_type != "direct" else "dm"}
room: "{name}"
chat_id: {chat_id}
participants: {len(stats)}
message_count: {len(messages)}
date_range: "{date_range}"
updated: "{now}"
---

# {name}

"""
    if len(stats) > 1:
        content += f"## 참여자 ({len(stats)}명)\n"
        for sender, count in stats.items():
            content += f"- **{sender}**: {count}건\n"
        content += "\n"

    content += f"## 대화 ({date_range})\n"
    content += _format_messages(messages)

    filepath = out_dir / f"{_sanitize_filename(name)}.md"
    filepath.write_text(content, encoding="utf-8")
    return filepath


class KakaoSync(BackgroundTask):
    """Periodic KakaoTalk sync maintenance task."""

    name = "kakao_sync"

    def __init__(self, interval_seconds: int = 1800) -> None:
        super().__init__(interval_seconds)
        self._binary: str | None = None
        self._key: str | None = None
        self._first_run: bool = True

    async def start(self, store=None) -> None:
        binary = _find_kakaocli()
        if not binary:
            logger.warning("kakao_sync.no_binary")
            return
        # Verify key works
        key = await asyncio.to_thread(_get_key)
        chats = await _fetch_chats(binary, key)
        logger.info("kakao_sync.verified", chats=len(chats))
        self._binary = binary
        self._key = key
        await super().start(store)

    async def run_once(self) -> None:
        await self._sync_once(self._binary, self._key, first_run=self._first_run)
        self._first_run = False

    async def _sync_once(self, binary: str, key: str, first_run: bool = False) -> None:
        """One full sync cycle."""
        settings = get_settings()
        vault_root = settings.vault.root.expanduser()
        out_dir = vault_root / settings.vault.inbox_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        exclude = set(settings.kakao.exclude_rooms)

        chats = await _fetch_chats(binary, key)

        dm_count = 0
        group_count = 0
        msg_total = 0

        for chat in chats:
            name = chat.get("display_name", "")
            chat_type = chat.get("type", "")
            chat_id = chat.get("id")

            if not name or name == "(unknown)":
                continue
            if name in exclude:
                continue

            # DMs: all of them. Groups: only small ones (avoid spam from large open chats).
            member_count = chat.get("member_count", 0)
            if chat_type == "group" and member_count > 50:
                continue  # skip large open chats

            # Determine message limit
            limit = 500 if first_run else 200

            messages = await _fetch_messages(binary, key, chat_id, limit=limit)
            if not messages:
                continue

            filepath = _write_chat_file(out_dir, chat_id, name, chat_type, messages)
            if filepath:
                msg_total += len(messages)
                if chat_type == "direct":
                    dm_count += 1
                else:
                    group_count += 1

            # Small delay to avoid overloading kakaocli
            await asyncio.sleep(0.3)

        logger.info(
            "kakao_sync.cycle",
            dms=dm_count,
            groups=group_count,
            messages=msg_total,
        )

    # stop() inherited from BackgroundTask
