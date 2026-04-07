"""Plaud.ai → Obsidian transcription sync."""
from __future__ import annotations

import gzip
import json
import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import httpx

from config import PLAUD_CONFIG_PATHS, TIMEZONE, INBOX_DIR
from vault_io import write_note, upsert_sync_block

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)

PLAUD_API_BASE = "https://api-apne1.plaud.ai"

# obsidian-sync config (extract_plaud_token.py가 저장하는 위치)
_OBSIDIAN_SYNC_PLAUD = Path.home() / ".config" / "obsidian-sync" / "plaud_config.json"
_OBSIDIAN_SYNC_TOKEN = Path.home() / ".config" / "obsidian-sync" / "plaud_token.txt"


def _get_api_domain() -> str:
    """Get the correct API domain for this user's region."""
    if _OBSIDIAN_SYNC_PLAUD.exists():
        try:
            cfg = json.loads(_OBSIDIAN_SYNC_PLAUD.read_text())
            domain = cfg.get("api_domain")
            if domain:
                return domain
        except (json.JSONDecodeError, KeyError):
            pass
    app_config = Path.home() / "Library" / "Application Support" / "Plaud" / "config.json"
    if app_config.exists():
        try:
            cfg = json.loads(app_config.read_text())
            domain = cfg.get("apiDomain")
            if domain:
                return domain
        except (json.JSONDecodeError, KeyError):
            pass
    return PLAUD_API_BASE


def get_plaud_token() -> str | None:
    """Resolve Plaud auth token from multiple sources."""
    if _OBSIDIAN_SYNC_TOKEN.exists():
        token = _OBSIDIAN_SYNC_TOKEN.read_text().strip()
        if token:
            logger.info("Using Plaud token from obsidian-sync config")
            return token

    if _OBSIDIAN_SYNC_PLAUD.exists():
        try:
            cfg = json.loads(_OBSIDIAN_SYNC_PLAUD.read_text())
            token = cfg.get("token")
            if token:
                logger.info("Using Plaud token from obsidian-sync plaud_config")
                return token
        except (json.JSONDecodeError, KeyError):
            pass

    toolkit_config = PLAUD_CONFIG_PATHS[0]
    if toolkit_config.exists():
        try:
            cfg = json.loads(toolkit_config.read_text())
            token = cfg.get("token") or cfg.get("accessToken") or cfg.get("access_token")
            if token:
                logger.info("Using Plaud token from plaud-toolkit config")
                return token
        except (json.JSONDecodeError, KeyError):
            pass

    if len(PLAUD_CONFIG_PATHS) > 1:
        token_file = PLAUD_CONFIG_PATHS[1]
        if token_file.exists():
            token = token_file.read_text().strip()
            if token:
                logger.info("Using Plaud token from token file")
                return token

    token = os.environ.get("PLAUD_TOKEN")
    if token:
        logger.info("Using Plaud token from environment variable")
        return token

    logger.warning(
        "No Plaud token found. Run extract_plaud_token.py or set PLAUD_TOKEN env var. "
        "Skipping Plaud sync."
    )
    return None


def _headers(token: str) -> dict:
    return {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "Origin": "https://web.plaud.ai",
        "Referer": "https://web.plaud.ai/",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }


def _download_s3_content(url: str) -> bytes | None:
    """Download and decompress gzipped content from S3 presigned URL."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url)
            resp.raise_for_status()
            raw = resp.content
            try:
                return gzip.decompress(raw)
            except (gzip.BadGzipFile, OSError):
                return raw
    except httpx.HTTPError as e:
        logger.error(f"S3 download failed: {e}")
        return None


def fetch_recordings(limit: int = 50) -> list[dict]:
    """Fetch recent recordings from Plaud API.

    Returns list of recording dicts with keys:
      id, filename, start_time (ms), end_time (ms), duration (ms),
      is_trans, is_summary, scene, serial_number, etc.
    """
    token = get_plaud_token()
    if not token:
        return []

    api = _get_api_domain()
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{api}/file/simple/web",
                params={"page": 1, "pageSize": limit},
                headers=_headers(token),
            )
            resp.raise_for_status()
            data = resp.json()
            recordings = data.get("data_file_list", [])
            total = data.get("data_file_total", len(recordings))
            logger.info(f"Fetched {len(recordings)}/{total} recordings from Plaud")
            return recordings
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            logger.error("Plaud token expired or invalid. Re-run extract_plaud_token.py.")
        else:
            logger.error(f"Plaud API error: {e.response.status_code}")
        return []
    except httpx.RequestError as e:
        logger.error(f"Plaud API request failed: {e}")
        return []


def _get_content_link(file_id: str, data_type: str) -> str | None:
    """Get S3 presigned URL for a specific content type from file detail."""
    token = get_plaud_token()
    if not token:
        return None

    api = _get_api_domain()
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{api}/file/detail/{file_id}",
                headers=_headers(token),
            )
            resp.raise_for_status()
            detail = resp.json()
            for item in detail.get("data", {}).get("content_list", []):
                if item.get("data_type") == data_type and item.get("task_status") == 1:
                    link = item.get("data_link")
                    if link:
                        return link
    except httpx.HTTPError as e:
        logger.error(f"Failed to get detail for {file_id}: {e}")
    return None


def fetch_transcription(file_id: str) -> list[dict] | None:
    """Fetch transcription segments for a recording.

    Returns list of segments: [{"start_time", "end_time", "content", "speaker"}, ...]
    """
    link = _get_content_link(file_id, "transaction")
    if not link:
        logger.debug(f"No transcription available for {file_id}")
        return None

    raw = _download_s3_content(link)
    if not raw:
        return None

    try:
        segments = json.loads(raw)
        if isinstance(segments, list):
            logger.info(f"Fetched transcription for {file_id}: {len(segments)} segments")
            return segments
    except json.JSONDecodeError:
        logger.error(f"Failed to parse transcription JSON for {file_id}")
    return None


def fetch_summary(file_id: str) -> str | None:
    """Fetch AI summary markdown for a recording."""
    link = _get_content_link(file_id, "auto_sum_note")
    if not link:
        logger.debug(f"No summary available for {file_id}")
        return None

    raw = _download_s3_content(link)
    if not raw:
        return None

    text = raw.decode("utf-8", errors="replace")

    # Some summaries are JSON with ai_content field
    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "ai_content" in data:
                text = data["ai_content"]
        except json.JSONDecodeError:
            pass

    # Strip the Plaud poster image line if present
    lines = text.split("\n")
    filtered = [l for l in lines if not l.startswith("![PLAUD NOTE]")]
    return "\n".join(filtered).strip()


def fetch_outline(file_id: str) -> list[dict] | None:
    """Fetch topic outline for a recording.

    Returns list: [{"start_time", "end_time", "topic"}, ...]
    """
    link = _get_content_link(file_id, "outline")
    if not link:
        return None

    raw = _download_s3_content(link)
    if not raw:
        return None

    try:
        outline = json.loads(raw)
        if isinstance(outline, list):
            return outline
    except json.JSONDecodeError:
        pass
    return None


def format_transcription(segments: list[dict]) -> str:
    """Format Plaud transcript segments into Obsidian markdown."""
    if not segments:
        return "## 녹취록\n\n(녹취 내용 없음)"

    lines = ["## 녹취록\n"]
    current_speaker = None

    for seg in segments:
        speaker = seg.get("speaker", seg.get("original_speaker", "화자"))
        content = seg.get("content", "")

        if speaker != current_speaker:
            current_speaker = speaker
            lines.append(f"\n**{speaker}**")

        lines.append(f"> {content}")

    return "\n".join(lines)


def format_outline(outline: list[dict]) -> str:
    """Format Plaud outline into markdown."""
    if not outline:
        return ""
    lines = ["## 주요 주제\n"]
    for item in outline:
        start_ms = item.get("start_time", 0)
        mins = start_ms // 60000
        secs = (start_ms % 60000) // 1000
        topic = item.get("topic", "")
        lines.append(f"- `{mins:02d}:{secs:02d}` {topic}")
    return "\n".join(lines)


def parse_recording_time(recording: dict) -> datetime | None:
    """Parse recording start time (epoch milliseconds)."""
    val = recording.get("start_time")
    if val:
        try:
            return datetime.fromtimestamp(val / 1000, tz=tz)
        except (ValueError, TypeError, OSError):
            pass
    return None


def get_recording_end_time(recording: dict) -> datetime | None:
    """Parse recording end time."""
    val = recording.get("end_time")
    if val:
        try:
            return datetime.fromtimestamp(val / 1000, tz=tz)
        except (ValueError, TypeError, OSError):
            pass
    return None


def get_recording_duration(recording: dict) -> timedelta:
    """Get recording duration (stored in milliseconds)."""
    val = recording.get("duration")
    if val:
        return timedelta(milliseconds=val)
    return timedelta(minutes=30)


def get_recording_id(recording: dict) -> str:
    """Get unique recording identifier."""
    return str(recording.get("id", ""))


def create_standalone_transcript_note(
    recording: dict, transcript_md: str, summary_md: str | None,
    outline_md: str | None = None, dry_run: bool = False,
) -> Path:
    """Create a standalone transcription note in the Inbox when no calendar match."""
    rec_time = parse_recording_time(recording)
    if not rec_time:
        rec_time = datetime.now(tz=tz)

    rec_id = get_recording_id(recording)
    title = recording.get("filename", f"녹음_{rec_time.strftime('%H%M')}")
    date_str = rec_time.strftime("%Y%m%d")

    frontmatter = {
        "created": rec_time.strftime("%Y-%m-%d %H:%M"),
        "type": "transcription",
        "source": "plaud",
        "plaud_id": rec_id,
    }

    duration = get_recording_duration(recording)
    body = f"\n# 녹음: {title}\n\n"
    body += f"- 일시: {rec_time.strftime('%Y-%m-%d %H:%M')}\n"
    body += f"- 길이: {int(duration.total_seconds() // 60)}분\n\n"

    if summary_md:
        body += f"## AI 요약\n\n{summary_md}\n\n"

    if outline_md:
        body += outline_md + "\n\n"

    body += transcript_md + "\n"

    safe_title = title.replace("/", "_").replace("\\", "_")
    note_path = INBOX_DIR / f"{date_str}_{safe_title}_Plaud.md"

    if not dry_run:
        write_note(note_path, frontmatter, body)

    logger.info(f"Created standalone transcript: {note_path.name}")
    return note_path
