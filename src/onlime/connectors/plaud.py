"""Plaud.ai connector — fetch logic only.

Ported from past/plaud_sync.py. Note formatting moved to outputs/.
"""
from __future__ import annotations

import gzip
import json
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from onlime.config import get_settings
from onlime.connectors.base import BaseConnector, ConnectorResult
from onlime.connectors.registry import register

logger = logging.getLogger(__name__)


def _get_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().general.timezone)


def _get_api_domain() -> str:
    """Get the correct API domain for this user's region."""
    settings = get_settings()
    plaud_config = settings.plaud.plaud_config_file.expanduser()

    if plaud_config.exists():
        try:
            cfg = json.loads(plaud_config.read_text())
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

    return settings.plaud.api_base


def get_plaud_token() -> str | None:
    """Resolve Plaud auth token from multiple sources."""
    settings = get_settings()
    token_file = settings.plaud.token_file.expanduser()

    if token_file.exists():
        token = token_file.read_text().strip()
        if token:
            logger.info("Using Plaud token from onlime config")
            return token

    plaud_config = settings.plaud.plaud_config_file.expanduser()
    if plaud_config.exists():
        try:
            cfg = json.loads(plaud_config.read_text())
            token = cfg.get("token")
            if token:
                logger.info("Using Plaud token from plaud_config")
                return token
        except (json.JSONDecodeError, KeyError):
            pass

    for p in settings.plaud.config_paths:
        resolved = p.expanduser()
        if resolved.exists():
            try:
                text = resolved.read_text().strip()
                if text.startswith('{'):
                    cfg = json.loads(text)
                    token = cfg.get("token") or cfg.get("accessToken") or cfg.get("access_token")
                else:
                    token = text
                if token:
                    logger.info(f"Using Plaud token from {resolved}")
                    return token
            except (json.JSONDecodeError, KeyError):
                continue

    # Also check old obsidian-sync location
    old_token = Path.home() / ".config" / "obsidian-sync" / "plaud_token.txt"
    if old_token.exists():
        token = old_token.read_text().strip()
        if token:
            logger.info("Using Plaud token from legacy obsidian-sync config")
            return token

    token = os.environ.get("PLAUD_TOKEN")
    if token:
        logger.info("Using Plaud token from environment variable")
        return token

    logger.warning(
        "No Plaud token found. Run: onlime setup plaud"
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
    """Fetch recent recordings from Plaud API."""
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
            logger.error("Plaud token expired or invalid. Run: onlime setup plaud")
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
    """Fetch transcription segments for a recording."""
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

    if text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "ai_content" in data:
                text = data["ai_content"]
        except json.JSONDecodeError:
            pass

    lines = text.split("\n")
    filtered = [l for l in lines if not l.startswith("![PLAUD NOTE]")]
    return "\n".join(filtered).strip()


def fetch_outline(file_id: str) -> list[dict] | None:
    """Fetch topic outline for a recording."""
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
    tz = _get_tz()
    val = recording.get("start_time")
    if val:
        try:
            return datetime.fromtimestamp(val / 1000, tz=tz)
        except (ValueError, TypeError, OSError):
            pass
    return None


def get_recording_end_time(recording: dict) -> datetime | None:
    """Parse recording end time."""
    tz = _get_tz()
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


def _recording_to_connector_result(recording: dict) -> ConnectorResult:
    """Convert a raw Plaud recording to ConnectorResult."""
    rec_time = parse_recording_time(recording) or datetime.now(tz=_get_tz())
    duration = get_recording_duration(recording)

    return ConnectorResult(
        source_id=get_recording_id(recording),
        source_type='recording',
        connector_name='plaud',
        timestamp=rec_time,
        title=recording.get("filename", f"녹음_{rec_time.strftime('%H%M')}"),
        content='',
        participants=[],
        duration_minutes=duration.total_seconds() / 60,
        metadata={
            'is_trans': recording.get("is_trans", False),
            'is_summary': recording.get("is_summary", False),
            'scene': recording.get("scene", ""),
            'serial_number': recording.get("serial_number", ""),
        },
        raw=recording,
    )


@register
class PlaudConnector(BaseConnector):
    name = "plaud"

    def fetch(self, *, limit: int = 50, days: int | None = None, **kwargs) -> list[ConnectorResult]:
        recordings = fetch_recordings(limit=limit)

        if recordings and days:
            tz = _get_tz()
            cutoff = datetime.now(tz) - timedelta(days=days)
            recordings = [
                r for r in recordings
                if (t := parse_recording_time(r)) and t >= cutoff
            ]

        return [_recording_to_connector_result(r) for r in recordings]

    def is_available(self) -> bool:
        return get_plaud_token() is not None
