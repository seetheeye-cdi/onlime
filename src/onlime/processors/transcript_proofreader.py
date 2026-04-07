"""Claude-based transcript proofreader.

YouTube auto-generated Korean transcripts are rich in speech noise:
  - missing sentence boundaries (whole paragraphs with no punctuation)
  - ASR misrecognitions (`예새`, `해세`, `하이일`, …)
  - inconsistent spacing
  - filler tokens that break mid-word

This module sends each transcript chunk to Claude Sonnet with strict
instructions to preserve the speaker's original meaning and tone while:
  - fixing obvious ASR errors
  - restoring proper Korean spacing
  - inserting sentence-ending punctuation where missing
  - splitting the output into one sentence per line

Usage:
    from onlime.processors.transcript_proofreader import proofread_transcript
    corrected = await proofread_transcript(raw_transcript)
"""

from __future__ import annotations

import re
from typing import Final

import structlog

from onlime.config import get_settings
from onlime.processors.summarizer import format_one_sentence_per_line
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()

# How many characters to send per Claude call. Korean characters take ~1.5-2
# tokens each, so a 3000-char chunk needs ~4500-6000 output tokens when the
# output length ≈ input length. 8192 max_tokens gives headroom.
_CHUNK_SIZE: Final[int] = 3000
_CHUNK_OVERLAP: Final[int] = 150  # preserve sentence boundary between chunks
_MIN_PROOFREAD_LENGTH: Final[int] = 120
_MAX_OUTPUT_TOKENS: Final[int] = 8192

_SYSTEM_PROMPT: Final[str] = (
    "당신은 음성 인식 결과를 교정하는 전문가입니다. "
    "입력은 유튜브 자동 자막 혹은 STT 결과이고 구두점, 띄어쓰기, 오인식이 많이 섞여 있습니다. "
    "한국어와 영어 모두 교정 가능합니다. 다음 원칙으로 교정하세요:\n"
    "1) 화자의 원래 의미와 말투는 그대로 유지합니다. 내용을 요약하거나 제거하지 마세요.\n"
    "2) 명백한 오인식(예: '해세' → '헤세', '이겄 찮아' → '있잖아')을 문맥에 맞춰 고쳐주세요.\n"
    "3) 띄어쓰기 규칙에 맞게 단어 사이 공백을 정리하세요.\n"
    "4) 문장이 끝나는 지점에 마침표/물음표/느낌표를 붙이고, **반드시 한 문장당 한 줄**로 출력합니다.\n"
    "5) **화자가 2명 이상으로 보이면 반드시 화자를 구분하세요.** 화자가 바뀔 때마다 줄 앞에 "
    "`[A]`, `[B]` 등의 태그를 붙이세요. 같은 화자가 계속 말하면 태그를 반복하지 않습니다. "
    "화자가 1명이면 태그를 붙이지 마세요.\n"
    "6) 마크다운 문법을 절대 넣지 마세요 (>, #, *, -, 불릿, 인용 등 금지). "
    "빈 줄도 넣지 마세요. 줄바꿈만 사용합니다.\n"
    "7) 입력에 없는 내용을 추가하거나, 의역하거나, 의견을 덧붙이지 마세요.\n"
    "8) 고유명사(인물, 책, 장소 등)는 가장 가능성이 높은 표기로 교정하세요. "
    "   예: '카트' → '칸트', '데카르' → '데카르트', '쇼패나우' → '쇼펜하우어'.\n"
    "9) 숫자, 영어 단어, 외래어는 원문을 따르되 명백히 뭉개진 것만 고칩니다."
)

_USER_TEMPLATE: Final[str] = (
    "아래 대본을 위 원칙에 따라 교정하고 한 문장당 한 줄로 출력하세요. "
    "교정한 텍스트 외에는 아무것도 쓰지 마세요 (설명/머리말/꼬리말 금지).\n\n"
    "<대본>\n{chunk}\n</대본>"
)


def _split_chunks(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split long text into overlapping chunks at paragraph or sentence boundaries."""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            # Prefer breaking on a newline, then a Korean sentence ender, then whitespace.
            window_start = max(start + int(size * 0.6), start + 1)
            slice_ = text[window_start:end]
            break_at = -1
            for marker in ("\n\n", "\n", ". ", "? ", "! ", "。", "！", "？", " "):
                idx = slice_.rfind(marker)
                if idx >= 0:
                    break_at = window_start + idx + len(marker)
                    break
            if break_at > start:
                end = break_at
        chunks.append(text[start:end].strip())
        if end >= length:
            break
        start = max(end - overlap, end)
    return [c for c in chunks if c]


async def _call_claude(chunk: str) -> str:
    import anthropic

    settings = get_settings()
    api_key = get_secret_or_env("claude-api-key", "ANTHROPIC_API_KEY")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=settings.llm.claude.model,
        max_tokens=_MAX_OUTPUT_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _USER_TEMPLATE.format(chunk=chunk)}],
    )
    if response.stop_reason == "max_tokens":
        logger.warning("proofread.truncated", chunk_chars=len(chunk))
        raise RuntimeError("claude response truncated at max_tokens")
    return response.content[0].text.strip()


def _strip_markdown_artifacts(text: str) -> str:
    """Remove accidental markdown from Claude output (headers, blockquotes, wrappers)."""
    cleaned = re.sub(r"^</?대본>\s*", "", text, flags=re.MULTILINE).strip()
    # Drop heading lines
    cleaned = re.sub(r"^#+\s.*\n", "", cleaned)
    # Strip blockquote markers (> ) that cause Obsidian indentation
    cleaned = re.sub(r"^>\s?", "", cleaned, flags=re.MULTILINE)
    # Strip bullet/list markers (-, *, numbered)
    cleaned = re.sub(r"^[\-\*]\s", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\d+\.\s", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


async def proofread_transcript(transcript: str) -> str:
    """Proofread and sentence-split a Korean YouTube/STT transcript via Claude.

    Returns the corrected text with one sentence per line. On any failure the
    original transcript is returned unchanged (never raises)."""
    if not transcript:
        return ""
    if len(transcript) < _MIN_PROOFREAD_LENGTH:
        return format_one_sentence_per_line(transcript)

    chunks = _split_chunks(transcript)
    logger.info("proofread.start", chars=len(transcript), chunks=len(chunks))

    results: list[str] = []
    for i, chunk in enumerate(chunks):
        try:
            corrected = await _call_claude(chunk)
            corrected = _strip_markdown_artifacts(corrected)
            results.append(corrected)
            logger.info("proofread.chunk_ok", idx=i, in_chars=len(chunk), out_chars=len(corrected))
        except Exception:
            logger.warning("proofread.chunk_failed", idx=i)
            results.append(format_one_sentence_per_line(chunk))

    combined = "\n".join(results)
    return format_one_sentence_per_line(combined)
