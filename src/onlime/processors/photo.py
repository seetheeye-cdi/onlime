"""Photo analysis: EXIF metadata extraction + Claude Vision."""

from __future__ import annotations

import base64
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# HEIC support: pillow-heif registers itself on import
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    logger.debug("photo.no_heif_support")

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS


def _gps_dms_to_float(dms: tuple, ref: str) -> float:
    """Convert GPS DMS (degrees, minutes, seconds) to decimal float."""
    degrees, minutes, seconds = dms
    result = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if ref in ("S", "W"):
        result = -result
    return round(result, 6)


def _parse_gps(gps_info: dict) -> tuple[float, float] | None:
    """Parse EXIF GPSInfo dict to (lat, lon) floats."""
    try:
        lat_dms = gps_info.get(2)  # GPSLatitude
        lat_ref = gps_info.get(1, "N")  # GPSLatitudeRef
        lon_dms = gps_info.get(4)  # GPSLongitude
        lon_ref = gps_info.get(3, "E")  # GPSLongitudeRef
        if lat_dms and lon_dms:
            return _gps_dms_to_float(lat_dms, lat_ref), _gps_dms_to_float(lon_dms, lon_ref)
    except (TypeError, ValueError, IndexError):
        pass
    return None


async def _reverse_geocode(lat: float, lon: float) -> str | None:
    """Reverse geocode GPS coordinates to a place name via Nominatim."""
    import httpx

    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "accept-language": "ko",
        "zoom": 16,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params, headers={"User-Agent": "Onlime/1.0"})
            resp.raise_for_status()
            data = resp.json()
            return data.get("display_name")
    except Exception:
        logger.warning("photo.geocode_failed", lat=lat, lon=lon)
        return None


async def extract_metadata(image_path: str | Path) -> dict[str, Any]:
    """Extract EXIF metadata from an image file.

    Returns dict with: taken_at, camera, gps_lat, gps_lon, location,
    width, height, file_size_mb.
    """
    path = Path(image_path)
    result: dict[str, Any] = {
        "file_size_mb": round(path.stat().st_size / (1024 * 1024), 2),
    }

    try:
        img = Image.open(path)
        result["width"] = img.width
        result["height"] = img.height
    except Exception:
        logger.warning("photo.open_failed", path=str(path))
        return result

    exif_data = img.getexif()
    if not exif_data:
        return result

    # Camera model (tag 272 = Model)
    model = exif_data.get(272)
    if model:
        result["camera"] = str(model).strip()

    # Date taken (tag 36867 = DateTimeOriginal via ExifIFD)
    exif_ifd = exif_data.get_ifd(0x8769)  # ExifIFD
    date_str = exif_ifd.get(36867) or exif_ifd.get(36868)  # DateTimeOriginal or DateTimeDigitized
    if date_str:
        try:
            result["taken_at"] = datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass

    # GPS (tag 34853 = GPSInfo)
    gps_ifd = exif_data.get_ifd(0x8825)  # GPSInfo IFD
    if gps_ifd:
        coords = _parse_gps(gps_ifd)
        if coords:
            result["gps_lat"], result["gps_lon"] = coords
            location = await _reverse_geocode(coords[0], coords[1])
            if location:
                result["location"] = location

    return result


def _resize_for_vision(img: Image.Image, max_side: int = 1568) -> Image.Image:
    """Resize image so longest side <= max_side, preserving aspect ratio."""
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    scale = max_side / max(w, h)
    new_w, new_h = int(w * scale), int(h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


def _image_to_base64(image_path: str | Path) -> tuple[str, str]:
    """Load image, resize, convert to JPEG base64. Returns (b64_data, media_type)."""
    img = Image.open(image_path)
    img = _resize_for_vision(img)

    # Convert to RGB if needed (HEIC/PNG may have alpha)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return b64, "image/jpeg"


async def analyze_photo(image_path: str | Path) -> dict[str, Any]:
    """Analyze photo content using Claude Vision.

    Returns dict with: description, title, tags.
    """
    import anthropic
    from onlime.config import get_settings

    settings = get_settings()
    b64_data, media_type = _image_to_base64(image_path)

    client = anthropic.AsyncAnthropic(api_key=settings.llm.api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6-20250514",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "이 사진을 분석해주세요. 반드시 아래 JSON 형식으로만 응답하세요.\n"
                            "```json\n"
                            '{"description": "사진에 대한 한 줄 설명 (한국어)",\n'
                            ' "title": "15자 이내 한국어 제목 (명사구)",\n'
                            ' "tags": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]}\n'
                            "```"
                        ),
                    },
                ],
            }
        ],
    )

    text = response.content[0].text.strip()
    # Extract JSON from markdown code block if present
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0].strip()
        if not text:
            text = response.content[0].text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("photo.vision_parse_failed", raw=text[:200])
        data = {"description": text[:200], "title": "사진", "tags": []}

    return {
        "description": data.get("description", ""),
        "title": data.get("title", "사진"),
        "tags": data.get("tags", []),
    }
