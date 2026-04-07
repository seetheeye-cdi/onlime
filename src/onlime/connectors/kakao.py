"""KakaoTalk connector — watches a folder for '대화 내보내기' .txt exports.

Supports two export formats:
  - Desktop (macOS app): `[발신자] [오후 3:20] 메시지`, dashed date separators
  - Mobile (iOS/Android): `2023. 2. 8. 오후 3:20, 발신자 : 메시지`, plain date lines
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector
from onlime.connectors.registry import register
from onlime.models import ContentType, SourceType

logger = structlog.get_logger()

# --- Format A: Desktop (macOS KakaoTalk app) ---
_DESKTOP_DATE_RE = re.compile(r"^-+ (\d{4}년 \d{1,2}월 \d{1,2}일 \S+요일) -+$")
_DESKTOP_MSG_RE = re.compile(r"^\[(.+?)\] \[(오전|오후) (\d{1,2}:\d{2})\] (.+)")
_DESKTOP_HEADER_RE = re.compile(r"^(.+?) (?:카카오톡 대화|님과 카카오톡 대화)$")

# --- Format B: Mobile (iOS/Android) ---
_MOBILE_DATE_RE = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 \S+요일$")
_MOBILE_MSG_RE = re.compile(
    r"^(\d{4})\. (\d{1,2})\. (\d{1,2})\. (오전|오후) (\d{1,2}):(\d{2}), (.+?) : (.+)"
)

_SAVE_DATE_RE = re.compile(r"^저장한 날짜\s*:\s*(.+)$")
_FOLDER_ROOM_RE = re.compile(r"Kakaotalk_Chat_(.+)")


def _parse_kr_date(text: str) -> str | None:
    """Parse '2026년 4월 5일 토요일' → '2026-04-05'."""
    m = re.match(r"(\d{4})년\s+(\d{1,2})월\s+(\d{1,2})일", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _parse_kr_time(ampm: str, time_str: str) -> str:
    """Parse '오후 3:20' → '15:20'."""
    h, m = time_str.split(":")
    hour = int(h)
    if ampm == "오후" and hour != 12:
        hour += 12
    elif ampm == "오전" and hour == 12:
        hour = 0
    return f"{hour:02d}:{m}"


def _detect_format(lines: list[str]) -> str:
    """Detect export format by scanning the first ~20 content lines."""
    for line in lines[:30]:
        if _DESKTOP_DATE_RE.match(line) or _DESKTOP_MSG_RE.match(line):
            return "desktop"
        if _MOBILE_DATE_RE.match(line) or _MOBILE_MSG_RE.match(line):
            return "mobile"
    return "unknown"


def _extract_room_name(lines: list[str], path: Path) -> str:
    """Extract room name from header line, folder name, or filename."""
    # Try desktop header: "방이름 카카오톡 대화"
    if lines:
        header_m = _DESKTOP_HEADER_RE.match(lines[0])
        if header_m:
            return header_m.group(1).strip()
    # Try folder name: "Kakaotalk_Chat_송현아"
    folder_m = _FOLDER_ROOM_RE.match(path.parent.name)
    if folder_m:
        return folder_m.group(1)
    # Fallback to filename stem
    return path.stem


def _parse_desktop(lines: list[str], nickname_map: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    """Parse desktop format lines into {date: [messages]}."""
    current_date: str | None = None
    days: dict[str, list[dict[str, str]]] = {}
    last_msg: dict[str, str] | None = None

    for line in lines:
        line = line.rstrip()

        date_m = _DESKTOP_DATE_RE.match(line)
        if date_m:
            current_date = _parse_kr_date(date_m.group(1))
            last_msg = None
            continue

        if current_date is None:
            continue

        msg_m = _DESKTOP_MSG_RE.match(line)
        if msg_m:
            raw_sender = msg_m.group(1)
            time_str = _parse_kr_time(msg_m.group(2), msg_m.group(3))
            text_body = msg_m.group(4)
            sender = nickname_map.get(raw_sender, raw_sender)
            msg = {"sender": sender, "time": time_str, "text": text_body}
            days.setdefault(current_date, []).append(msg)
            last_msg = msg
            continue

        if line and last_msg is not None:
            last_msg["text"] += "\n" + line

    return days


def _parse_mobile(lines: list[str], nickname_map: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    """Parse mobile format lines into {date: [messages]}."""
    current_date: str | None = None
    days: dict[str, list[dict[str, str]]] = {}
    last_msg: dict[str, str] | None = None

    for line in lines:
        line = line.rstrip()

        # Date line: "2023년 2월 8일 수요일"
        date_m = _MOBILE_DATE_RE.match(line)
        if date_m:
            y, mo, d = date_m.group(1), date_m.group(2), date_m.group(3)
            current_date = f"{y}-{int(mo):02d}-{int(d):02d}"
            last_msg = None
            continue

        if current_date is None:
            continue

        # Message: "2023. 2. 8. 오전 11:16, 송현아 : 안녕하세요"
        msg_m = _MOBILE_MSG_RE.match(line)
        if msg_m:
            ampm = msg_m.group(4)
            hour = int(msg_m.group(5))
            minute = msg_m.group(6)
            if ampm == "오후" and hour != 12:
                hour += 12
            elif ampm == "오전" and hour == 12:
                hour = 0
            time_str = f"{hour:02d}:{minute}"

            raw_sender = msg_m.group(7)
            text_body = msg_m.group(8)
            sender = nickname_map.get(raw_sender, raw_sender)
            msg = {"sender": sender, "time": time_str, "text": text_body}
            days.setdefault(current_date, []).append(msg)
            last_msg = msg
            continue

        # System messages (삭제, 입장 등) — skip but break continuation
        if line and not line.startswith(" ") and "," in line and ("님이" in line or "삭제" in line):
            last_msg = None
            continue

        # Continuation line
        if line and last_msg is not None:
            last_msg["text"] += "\n" + line

    return days


def parse_kakao_txt(path: Path) -> list[dict[str, Any]]:
    """Parse a KakaoTalk export .txt file (desktop or mobile format).

    Returns a list of day-grouped dicts:
    [{"room": str, "date": str, "messages": [{"sender": str, "time": str, "text": str}]}]
    """
    raw_bytes = path.read_bytes()
    # Strip BOM if present
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]
    text = raw_bytes.decode("utf-8")
    text = unicodedata.normalize("NFC", text)
    lines = text.splitlines()

    if not lines:
        return []

    room_name = _extract_room_name(lines, path)

    settings = get_settings()
    nickname_map = settings.kakao.nickname_to_name

    fmt = _detect_format(lines)
    if fmt == "desktop":
        days = _parse_desktop(lines, nickname_map)
    elif fmt == "mobile":
        days = _parse_mobile(lines, nickname_map)
    else:
        logger.warning("kakao.unknown_format", path=str(path))
        return []

    logger.info("kakao.parsed", path=path.name, format=fmt, room=room_name, days=len(days))

    results = []
    for date_str in sorted(days.keys()):
        messages = days[date_str]
        if messages:
            results.append({"room": room_name, "date": date_str, "messages": messages})
    return results


def _format_messages(messages: list[dict[str, str]]) -> str:
    """Format parsed messages into readable text."""
    lines = []
    for msg in messages:
        lines.append(f"[{msg['time']}] {msg['sender']}: {msg['text']}")
    return "\n".join(lines)


def _participants(messages: list[dict[str, str]]) -> list[str]:
    """Extract unique participants in order of appearance."""
    seen: set[str] = set()
    result: list[str] = []
    for msg in messages:
        s = msg["sender"]
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


class _TxtHandler(FileSystemEventHandler):
    """Watchdog handler that pushes new .txt KakaoTalk exports to the engine queue."""

    def __init__(self, queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop) -> None:
        self._queue = queue
        self._loop = loop

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".txt":
            return
        asyncio.run_coroutine_threadsafe(self._handle_file(path), self._loop)

    async def _handle_file(self, path: Path) -> None:
        await asyncio.sleep(2.0)  # stability delay
        if not path.exists():
            return
        try:
            await _process_export_file(path, self._queue)
        except Exception:
            logger.exception("kakao.parse_failed", path=str(path))


async def _process_export_file(
    path: Path, queue: asyncio.Queue[dict[str, Any]]
) -> None:
    """Parse a KakaoTalk export file and emit events."""
    settings = get_settings()
    tz = ZoneInfo(settings.general.timezone)

    days = await asyncio.to_thread(parse_kakao_txt, path)
    if not days:
        logger.warning("kakao.empty_export", path=str(path))
        return

    exclude = set(settings.kakao.exclude_rooms)

    for day in days:
        room = day["room"]
        if room in exclude:
            continue
        date_str = day["date"]
        messages = day["messages"]
        if not messages:
            continue

        raw_content = f"[카카오톡] {room} — {date_str}\n\n" + _format_messages(messages)
        event_id = f"kakao:{room}:{date_str}"

        event_dict: dict[str, Any] = {
            "id": event_id,
            "source": SourceType.KAKAO.value,
            "content_type": ContentType.MESSAGE.value,
            "raw_content": raw_content,
            "timestamp": datetime.strptime(date_str, "%Y-%m-%d")
            .replace(tzinfo=tz)
            .isoformat(),
            "metadata": {
                "room": room,
                "participants": _participants(messages),
                "message_count": len(messages),
                "export_file": path.name,
            },
        }

        await queue.put(event_dict)
        logger.info("kakao.emitted", room=room, date=date_str, messages=len(messages))


# ---------- kakaocli DB polling ----------

import json
import shutil
import subprocess


def _find_kakaocli() -> str | None:
    """Find the kakaocli binary."""
    return shutil.which("kakaocli")


def _kakaocli_db_args() -> list[str]:
    """Build --db and --key args from Keychain secrets."""
    from onlime.security.secrets import get_secret_or_env

    user_id = get_secret_or_env("kakao-user-id", "KAKAO_USER_ID")
    db_key = get_secret_or_env("kakao-db-key", "KAKAO_DB_KEY")
    if not user_id or not db_key:
        raise RuntimeError("kakao-user-id or kakao-db-key not found in Keychain")

    # Derive DB path from user ID + UUID
    import hashlib, base64

    uuid_bytes = subprocess.check_output(
        ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True,
    )
    import re as _re
    uuid_m = _re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', uuid_bytes)
    if not uuid_m:
        raise RuntimeError("Could not read IOPlatformUUID")
    uuid = uuid_m.group(1)

    # databaseName derivation (matches KeyDerivation.swift)
    data = uuid.encode("utf-8")
    sha1 = hashlib.sha1(data).digest()
    sha256 = hashlib.sha256(data).digest()
    hashed = base64.b64encode(sha1 + sha256).decode()

    hawawa = ".".join([".", "F", user_id, "A", "F", uuid[::-1], ".", "|"])
    salt = hashed[::-1]
    derived = hashlib.pbkdf2_hmac("sha256", hawawa.encode(), salt.encode(), 100000, dklen=128)
    db_name = derived.hex()[28:28 + 78]

    container = Path.home() / "Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Application Support/com.kakao.KakaoTalkMac"
    db_path = container / db_name

    if not db_path.exists():
        raise RuntimeError(f"KakaoTalk DB not found: {db_path}")

    return ["--db", str(db_path), "--key", db_key]


async def _kakaocli_chats(binary: str, db_args: list[str]) -> list[dict[str, Any]]:
    """Get chat list via kakaocli."""
    cmd = [binary, "chats", "--limit", "100", "--json"] + db_args
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"kakaocli chats failed: {stderr.decode()}")
    return json.loads(stdout.decode())


async def _kakaocli_messages(
    binary: str, db_args: list[str], chat_name: str, since_days: int,
) -> list[dict[str, Any]]:
    """Get messages for a chat via kakaocli."""
    cmd = [
        binary, "messages",
        "--chat", chat_name,
        "--since", f"{since_days}d",
        "--json",
    ] + db_args
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("kakao.cli_messages_failed", chat=chat_name, err=stderr.decode()[:200])
        return []
    return json.loads(stdout.decode())


def _group_messages_by_date(
    messages: list[dict[str, Any]], tz: ZoneInfo,
) -> dict[str, list[dict[str, str]]]:
    """Group kakaocli JSON messages by date."""
    by_date: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for msg in messages:
        if msg.get("type") == "system":
            continue
        text = msg.get("text", "")
        if not text:
            continue
        ts_str = msg.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(tz)
        except (ValueError, TypeError):
            continue
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
        sender = msg.get("sender", "?")
        entry = {"sender": sender, "time": time_str, "text": text}
        by_date.setdefault(date_str, []).append((ts_str, entry))

    # Sort each day by timestamp
    result: dict[str, list[dict[str, str]]] = {}
    for date_str in sorted(by_date.keys()):
        entries = sorted(by_date[date_str], key=lambda x: x[0])
        result[date_str] = [e for _, e in entries]
    return result


# ---------- connector ----------


@register
class KakaoConnector(BaseConnector):
    """KakaoTalk connector: kakaocli DB polling (preferred) or .txt watcher (fallback)."""

    name = "kakao"

    def __init__(self) -> None:
        self._observer: Observer | None = None
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._mode: str = "none"  # "kakaocli" or "txt"

    def fetch(self, **kwargs: Any) -> list:
        return []

    async def start(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        settings = get_settings()
        self._queue = queue

        # Try kakaocli mode first
        if settings.kakao.use_kakaocli:
            binary = _find_kakaocli()
            if binary:
                try:
                    db_args = await asyncio.to_thread(_kakaocli_db_args)
                    # Quick test: list chats
                    chats = await _kakaocli_chats(binary, db_args)
                    self._mode = "kakaocli"
                    self._poll_task = asyncio.create_task(
                        self._kakaocli_poll_loop(binary, db_args)
                    )
                    logger.info("kakao.started", mode="kakaocli", chats=len(chats))
                    return
                except Exception as exc:
                    logger.warning("kakao.kakaocli_init_failed", error=str(exc))

        # Fallback: .txt watcher
        if settings.kakao.export_dir:
            export_dir = Path(settings.kakao.export_dir).expanduser()
            if not export_dir.exists():
                export_dir.mkdir(parents=True, exist_ok=True)
            loop = asyncio.get_running_loop()
            handler = _TxtHandler(queue, loop)
            self._observer = Observer()
            self._observer.schedule(handler, str(export_dir), recursive=True)
            self._observer.start()
            await self._initial_scan(export_dir)
            self._mode = "txt"
            logger.info("kakao.started", mode="txt", export_dir=str(export_dir))
        else:
            logger.warning("kakao.no_mode_available")

    async def _initial_scan(self, export_dir: Path) -> None:
        count = 0
        for path in sorted(export_dir.rglob("*.txt")):
            try:
                await _process_export_file(path, self._queue)
                count += 1
            except Exception:
                logger.exception("kakao.initial_scan_failed", path=str(path))
        if count:
            logger.info("kakao.initial_scan", files=count)

    async def _kakaocli_poll_loop(self, binary: str, db_args: list[str]) -> None:
        """Poll kakaocli for new messages periodically."""
        settings = get_settings()
        tz = ZoneInfo(settings.general.timezone)
        poll_seconds = settings.kakao.poll_interval_minutes * 60
        exclude = set(settings.kakao.exclude_rooms)
        nickname_map = settings.kakao.nickname_to_name

        first_run = True
        while True:
            try:
                days_back = settings.kakao.sync_days_back if first_run else 1
                await self._kakaocli_poll_once(binary, db_args, tz, days_back, exclude, nickname_map)
                first_run = False
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("kakao.poll_failed")

            await asyncio.sleep(poll_seconds)

    async def _kakaocli_poll_once(
        self,
        binary: str,
        db_args: list[str],
        tz: ZoneInfo,
        days_back: int,
        exclude: set[str],
        nickname_map: dict[str, str],
    ) -> None:
        chats = await _kakaocli_chats(binary, db_args)
        logger.info("kakao.poll", chats=len(chats))

        for chat in chats:
            chat_name = chat.get("display_name") or "(unknown)"
            if chat_name in exclude or chat_name == "(unknown)":
                continue

            messages = await _kakaocli_messages(binary, db_args, chat_name, days_back)
            if not messages:
                continue

            by_date = _group_messages_by_date(messages, tz)

            for date_str, day_msgs in by_date.items():
                # Apply nickname mapping
                for m in day_msgs:
                    m["sender"] = nickname_map.get(m["sender"], m["sender"])

                raw_content = f"[카카오톡] {chat_name} — {date_str}\n\n" + _format_messages(day_msgs)
                event_id = f"kakao:{chat_name}:{date_str}"

                event_dict: dict[str, Any] = {
                    "id": event_id,
                    "source": SourceType.KAKAO.value,
                    "content_type": ContentType.MESSAGE.value,
                    "raw_content": raw_content,
                    "timestamp": datetime.strptime(date_str, "%Y-%m-%d")
                    .replace(tzinfo=tz)
                    .isoformat(),
                    "metadata": {
                        "room": chat_name,
                        "participants": _participants(day_msgs),
                        "message_count": len(day_msgs),
                        "source_mode": "kakaocli",
                    },
                }

                await self.emit(event_dict, self._queue)

            logger.info("kakao.chat_done", chat=chat_name, days=len(by_date))
            await asyncio.sleep(0.5)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        logger.info("kakao.stopped", mode=self._mode)

    def is_available(self) -> bool:
        settings = get_settings()
        return bool(settings.kakao.enabled)
