"""Messaging digest injection into the daily note (KakaoTalk, Slack, Telegram, Instagram)."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from onlime.config import get_settings
from onlime.connectors.base import ConnectorResult
from onlime.vault.io import daily_note_path, read_note, write_note, note_exists, upsert_sync_block

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")
_PREVIEW_LIMIT = 3


def _sanitize_md(text: str) -> str:
    """Sanitize untrusted text before embedding in Obsidian markdown.

    Prevents:
    - Sync-block marker injection (<!-- SYNC:... --> / <!-- /SYNC:... -->)
    - YAML frontmatter injection (--- at line start)
    - Wikilink/embed injection ([[...]] / ![[...]])
    - HTML tag injection
    """
    # Strip HTML comments that could break sync-block markers.
    text = re.sub(r"<!--.*?-->", "", text)
    # Strip HTML tags to prevent injection into Obsidian rendering.
    text = re.sub(r"<[^>]+>", "", text)
    # Neutralize Obsidian wikilinks and embeds.
    text = text.replace("[[", "[\\[").replace("]]", "]\\]")
    # Neutralize YAML frontmatter delimiter at start of string.
    if text.lstrip().startswith("---"):
        text = text.replace("---", "\\-\\-\\-", 1)
    return text


def filter_messages_for_date(
    messages: list[ConnectorResult],
    target_date: date,
) -> list[ConnectorResult]:
    """Return only messages whose timestamp falls on target_date (Asia/Seoul)."""
    result = []
    for msg in messages:
        ts = msg.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_KST)
        else:
            ts = ts.astimezone(_KST)
        if ts.date() == target_date:
            result.append(msg)
    return result


_APP_LABELS = {
    "kakao": "카카오톡",
    "slack": "Slack",
    "telegram": "Telegram",
    "instagram": "Instagram DM",
}


def _kst(ts: datetime) -> datetime:
    """Normalise a timestamp to KST for display."""
    return ts.astimezone(_KST) if ts.tzinfo else ts.replace(tzinfo=_KST)


def _latest_ts(msgs: list[ConnectorResult]) -> datetime:
    return max(_kst(m.timestamp) for m in msgs)


def _build_room_lines(room_name: str, room_msgs: list[ConnectorResult]) -> list[str]:
    """Build markdown lines for a single chat room."""
    lines: list[str] = []
    sorted_msgs = sorted(room_msgs, key=lambda m: _kst(m.timestamp))
    count = len(sorted_msgs)
    first_ts = _kst(sorted_msgs[0].timestamp)
    last_ts = _kst(sorted_msgs[-1].timestamp)
    time_range = f"{first_ts.strftime('%H:%M')}~{last_ts.strftime('%H:%M')}"

    safe_room = _sanitize_md(room_name)
    lines.append(f"**{safe_room}** ({count}건, {time_range})")

    participants: list[str] = []
    seen: set[str] = set()
    for m in sorted_msgs:
        sender = m.metadata.get("raw_sender", "")
        if sender and sender not in seen:
            participants.append(_sanitize_md(sender))
            seen.add(sender)
    if participants:
        lines.append(f"- 참여자: {', '.join(participants)}")

    preview_msgs = sorted_msgs[-_PREVIEW_LIMIT:]
    for m in reversed(preview_msgs):
        sender = _sanitize_md(m.metadata.get("raw_sender", ""))
        ts_str = _kst(m.timestamp).strftime("%H:%M")
        text = _sanitize_md((m.content or "").replace("\n", " ").strip())
        if len(text) > 60:
            text = text[:57] + "..."
        sender_part = f"{sender}, {ts_str}" if sender else ts_str
        lines.append(f'- 최근: "{text}" ({sender_part})')

    return lines


def build_kakao_digest(messages: list[ConnectorResult], target_date: date) -> str:
    """Build a markdown messaging digest block for the daily note.

    Groups messages by app then by chat room, with brief previews
    of the most recent messages per room.
    """
    lines = ["#### 메시지 요약"]

    if not messages:
        lines.append("- (메시지 없음)")
        return "\n".join(lines)

    # Group by app, then by room
    apps: dict[str, dict[str, list[ConnectorResult]]] = defaultdict(lambda: defaultdict(list))
    for msg in messages:
        app = msg.metadata.get("app", "kakao")
        room = msg.metadata.get("room", msg.title or "알 수 없는 채팅방")
        apps[app][room].append(msg)

    # Sort apps by label order: kakao first, then alphabetical
    app_order = ["kakao", "slack", "telegram", "instagram"]
    sorted_apps = sorted(apps.keys(), key=lambda a: (app_order.index(a) if a in app_order else 99, a))

    for app in sorted_apps:
        rooms = apps[app]
        label = _APP_LABELS.get(app, app)
        lines.append("")
        lines.append(f"##### {label}")

        sorted_rooms = sorted(rooms.items(), key=lambda kv: _latest_ts(kv[1]), reverse=True)
        for room_name, room_msgs in sorted_rooms:
            lines.append("")
            lines.extend(_build_room_lines(room_name, room_msgs))

    return "\n".join(lines)


def inject_kakao_digest(
    messages: list[ConnectorResult],
    target_date: date | None = None,
    dry_run: bool = False,
) -> None:
    """Insert or update kakao digest sync block in the daily note."""
    settings = get_settings()

    if target_date is None:
        target_date = datetime.now(tz=_KST).date()

    date_str = target_date.strftime("%Y-%m-%d")
    path = daily_note_path(settings.vault.daily_path, date_str)

    today_messages = filter_messages_for_date(messages, target_date)

    if not today_messages:
        logger.info("메시지 없음 (%s), 삽입 건너뜀", date_str)
        return

    if not note_exists(path):
        logger.info("데일리 노트 %s.md 없음, 메시지 다이제스트 삽입 건너뜀", date_str)
        return

    fm, body = read_note(path)

    digest_content = build_kakao_digest(today_messages, target_date)

    # Migrate old kakao-digest block to new message-digest block
    if "<!-- SYNC:kakao-digest -->" in body:
        import re as _re
        body = _re.sub(
            r"<!-- SYNC:kakao-digest -->.*?<!-- /SYNC:kakao-digest -->",
            "",
            body,
            flags=_re.DOTALL,
        )

    body = upsert_sync_block(
        body,
        marker_id="message-digest",
        content=digest_content,
        after_heading="## ==잡서",
    )

    if not dry_run:
        write_note(path, fm, body)

    logger.info(
        "%s메시지 다이제스트 삽입 완료: %s (%d건)",
        "[DRY-RUN] " if dry_run else "",
        path.name,
        len(today_messages),
    )
