"""Periodic digest of Telegram group messages → vault markdown."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from onlime.config import get_settings
from onlime.llm import LLMError, call_llm
from onlime.maintenance.base import BackgroundTask
from onlime.outputs.vault import atomic_write

logger = structlog.get_logger()

_DIGEST_PROMPT = (
    "다음은 텔레그램 그룹 대화 내용입니다.\n"
    "핵심 논의/결정사항을 1~3줄로 요약해주세요.\n"
    "잡담/인사는 생략하세요.\n"
    "한 문장당 한 줄로 작성하세요.\n\n"
    "{text}"
)


def _upsert_date_section(content: str, date_str: str, summary: str) -> str:
    """Insert or replace a ## YYYY-MM-DD section in the digest note."""
    section_header = f"## {date_str}"

    if section_header in content:
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
                i += 1
                while i < len(lines) and not lines[i].startswith("## "):
                    i += 1
                replaced = True
                continue
            new_lines.append(lines[i])
            i += 1
        return "\n".join(new_lines)
    else:
        lines = content.split("\n")
        fm_end = 0
        fm_count = 0
        for idx, line in enumerate(lines):
            if line.strip() == "---":
                fm_count += 1
                if fm_count == 2:
                    fm_end = idx + 1
                    break

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


class TelegramGroupDigestTask(BackgroundTask):
    """Summarize buffered Telegram group messages into vault digest files."""

    name = "telegram_group_digest"

    def __init__(
        self,
        interval_seconds: int,
        group_ids: list[int] | None = None,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds)
        self._group_ids = group_ids or []

    async def run_once(self) -> None:
        if not self._store or not self._group_ids:
            return

        settings = get_settings()
        tz = ZoneInfo(settings.general.timezone)
        vault_root = settings.vault.root.expanduser()
        digest_dir = vault_root / "1.INPUT" / "Telegram"
        digest_dir.mkdir(parents=True, exist_ok=True)

        for group_id in self._group_ids:
            try:
                await self._digest_group(group_id, digest_dir, tz)
            except Exception:
                logger.exception("telegram_group_digest.group_failed", group_id=group_id)

    async def _digest_group(
        self,
        group_id: int,
        digest_dir: Any,
        tz: ZoneInfo,
    ) -> None:
        messages = await self._store.get_undigested_messages(group_id)
        if not messages:
            return

        group_name = messages[0]["group_name"]

        # Group by date
        by_date: dict[str, list[dict]] = defaultdict(list)
        for msg in messages:
            ts = msg["message_ts"]
            try:
                dt = datetime.fromisoformat(ts).astimezone(tz)
            except (ValueError, TypeError):
                dt = datetime.now(tz)
            date_str = dt.strftime("%Y-%m-%d")
            by_date[date_str].append(msg)

        # Sanitize group name for filename
        safe_name = group_name
        for ch in '?":*|<>\\':
            safe_name = safe_name.replace(ch, " ")
        safe_name = safe_name.strip().rstrip(".")

        digest_path = digest_dir / f"{safe_name}.md"

        if digest_path.exists():
            content = digest_path.read_text(encoding="utf-8")
        else:
            content = (
                f"---\ntitle: {group_name}\ntype: telegram-group-digest\n---\n"
            )

        last_ts = None
        for date_str in sorted(by_date.keys()):
            day_msgs = by_date[date_str]
            raw_text = self._format_day_text(day_msgs, tz)
            if not raw_text.strip():
                continue

            summary = await self._summarize_day(raw_text, len(day_msgs))
            content = _upsert_date_section(content, date_str, summary)

            # Track the latest message ts for marking
            for m in day_msgs:
                if last_ts is None or m["message_ts"] > last_ts:
                    last_ts = m["message_ts"]

        atomic_write(digest_path, content)

        if last_ts:
            await self._store.mark_messages_digested(group_id, last_ts)

        logger.info(
            "telegram_group_digest.written",
            group=group_name,
            dates=len(by_date),
            messages=len(messages),
        )

    @staticmethod
    def _format_day_text(messages: list[dict], tz: ZoneInfo) -> str:
        lines: list[str] = []
        for msg in messages:
            ts = msg["message_ts"]
            try:
                dt = datetime.fromisoformat(ts).astimezone(tz)
                time_str = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                time_str = "??:??"
            lines.append(f"[{time_str}] {msg['user_name']}: {msg['message_text']}")
        return "\n".join(lines[:100])  # cap to control tokens

    @staticmethod
    async def _summarize_day(raw_text: str, msg_count: int) -> str:
        prompt = _DIGEST_PROMPT.format(text=raw_text[:6000])
        try:
            return await call_llm(prompt, max_tokens=512, caller="tg_group_digest")
        except LLMError:
            logger.warning("telegram_group_digest.summarize_failed")
            return f"- {msg_count}건 대화 (요약 실패)"
