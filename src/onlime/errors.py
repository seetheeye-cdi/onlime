"""Exception → user-friendly Korean message mapping."""

from __future__ import annotations

import re


def humanize_error(exc: BaseException) -> str:
    """Convert an exception into a concise Korean user message.

    Checks exception type and message patterns to produce a helpful,
    non-technical message for Telegram users.
    """
    msg = str(exc).lower()

    # LLM provider failures
    from onlime.llm import LLMError

    if isinstance(exc, LLMError) or "all llm providers failed" in msg:
        return "AI 서비스에 일시적 문제가 있습니다. 잠시 후 자동 재시도됩니다."

    # HTTP status codes (from httpx, aiohttp, requests, etc.)
    status = _extract_status_code(msg)
    if status:
        if status == 429:
            return "요청이 너무 많습니다. 잠시 후 자동 재시도됩니다."
        if status in (401, 403):
            return "인증 오류가 발생했습니다."
        if status == 404:
            return "요청한 페이지를 찾을 수 없습니다. URL을 확인해주세요."
        if 500 <= status < 600:
            return "외부 서비스에 일시적 장애가 있습니다."

    # Timeout
    if "timeout" in msg or isinstance(exc, TimeoutError):
        return "웹 페이지 응답이 너무 느립니다."

    # Connection errors
    if isinstance(exc, ConnectionError) or "connectionerror" in msg or "connect" in msg and "refused" in msg:
        return "네트워크 연결에 실패했습니다."

    return "처리 중 오류가 발생했습니다. 잠시 후 자동 재시도됩니다."


_STATUS_RE = re.compile(r"(?:status[_ ]?code|http)\s*[:= ]*(\d{3})|^(\d{3})\b")


def _extract_status_code(msg: str) -> int | None:
    """Try to extract an HTTP status code from an error message."""
    m = _STATUS_RE.search(msg)
    if m:
        code_str = m.group(1) or m.group(2)
        return int(code_str)
    # Also catch patterns like "429 Too Many Requests"
    m2 = re.search(r"\b(4\d{2}|5\d{2})\b", msg)
    if m2:
        return int(m2.group(1))
    return None
