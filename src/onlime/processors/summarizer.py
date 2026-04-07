"""LLM-based summarizer: Claude Sonnet (primary) + Ollama (local fallback)."""

from __future__ import annotations

import re

import structlog

from onlime.config import get_settings
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()

_WIKILINK_RULE = (
    "주요 고유명사(인물, 기업, 브랜드, 제품, 개념)가 처음 등장할 때 [[한국어 English]] 형태의 위키링크로 감싸주세요. "
    "예: [[앤쓰로픽 Anthropic]], [[드류 벤트 Drew Bent]], [[토스 Toss]]. "
    "한국어가 원래 이름이면 영어 병기 불필요: [[토스]], [[카카오페이]]. "
    "같은 키워드는 처음 한 번만 [[]] 처리하세요."
)

_SENTENCE_RULE = (
    "출력은 **반드시 한 문장당 한 줄**로 작성하세요. "
    "마침표/물음표/느낌표(`.`, `?`, `!`, `。`, `！`, `？`) 뒤에는 줄바꿈을 넣고, "
    "여러 문장을 한 줄에 붙여쓰지 마세요. 문장 사이는 빈 줄 없이 한 줄만 바꿉니다."
)

_PROMPTS: dict[str, str] = {
    "general": (
        "다음 텍스트를 한국어로 3~5문장으로 요약해주세요. "
        "핵심 정보와 맥락을 유지하세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{{text}}"
    ),
    "chat": (
        "다음 대화를 한국어로 요약해주세요. "
        "주요 논의 사항, 결정 사항, 액션 아이템을 구분해주세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{{text}}"
    ),
    "article": (
        "다음 글/기사를 한국어로 요약해주세요. "
        "핵심 주장, 근거, 결론을 정리해주세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{{text}}"
    ),
    "voice_memo": (
        "다음 음성 메모 전사본을 한국어로 요약해주세요. "
        "주요 내용과 액션 아이템을 정리해주세요. "
        f"{_WIKILINK_RULE} {_SENTENCE_RULE}\n\n{{text}}"
    ),
}

# Matches sentence-ending punctuation (Latin + CJK) followed by whitespace,
# so we can insert a newline after each sentence as a post-processing safety net
# in case the LLM ignores the prompt rule.
_SENTENCE_SPLIT_RE = re.compile(r"([.!?。！？])[ \t]+(?=\S)")


def format_one_sentence_per_line(text: str) -> str:
    """Enforce one-sentence-per-line on LLM output.

    Splits on sentence-ending punctuation followed by whitespace. Preserves
    existing line breaks, bullet points, and markdown structure. Collapses
    accidental triple+ newlines but keeps blank lines between sections.
    """
    if not text:
        return ""
    # Split into lines, process each line independently so we don't collapse
    # markdown structure (e.g. headings, bullet lists, blank separators).
    out_lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            out_lines.append(line)
            continue
        # Insert newline after sentence-ending punctuation within this line.
        expanded = _SENTENCE_SPLIT_RE.sub(r"\1\n", line)
        out_lines.extend(expanded.split("\n"))
    # Collapse 3+ consecutive newlines to at most 2 (one blank line).
    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()

# Minimum text length to trigger summarization
MIN_SUMMARIZE_LENGTH = 200


async def summarize(text: str, prompt_type: str = "general") -> str:
    """Summarize text using Claude (primary) or Ollama (fallback).

    Returns the original text if shorter than MIN_SUMMARIZE_LENGTH.
    """
    if len(text) < MIN_SUMMARIZE_LENGTH:
        return text

    prompt_template = _PROMPTS.get(prompt_type, _PROMPTS["general"])
    prompt = prompt_template.format(text=text)

    # Try Claude first
    try:
        return format_one_sentence_per_line(await _call_claude(prompt))
    except Exception as exc:
        logger.warning("summarizer.claude_failed", prompt_type=prompt_type, error=str(exc))

    # Fallback to OpenAI (GPT)
    try:
        return format_one_sentence_per_line(await _call_openai(prompt))
    except Exception as exc:
        logger.warning("summarizer.openai_failed", prompt_type=prompt_type, error=str(exc))

    # Fallback to Ollama (local)
    try:
        return format_one_sentence_per_line(await _call_ollama(prompt))
    except Exception as exc:
        logger.warning("summarizer.ollama_failed", prompt_type=prompt_type, error=str(exc))

    # All failed — return truncated original
    logger.error("summarizer.all_failed", prompt_type=prompt_type)
    fallback = text[:500] + "..." if len(text) > 500 else text
    return format_one_sentence_per_line(fallback)


async def generate_title(text: str) -> str:
    """Generate a short title (≤10 chars Korean noun phrase) from transcript.

    Uses Claude Haiku for speed. Returns empty string on failure.
    """
    prompt = (
        "다음 전사본의 핵심 주제를 15자 이내 한국어 명사구로 작성해주세요. "
        "부연 설명 없이 제목만 출력하세요.\n\n" + text[:2000]
    )
    try:
        return await _call_claude(
            prompt, model="claude-sonnet-4-6", max_tokens=32,
        )
    except Exception:
        pass
    try:
        return await _call_openai(prompt, max_tokens=32)
    except Exception:
        logger.warning("summarizer.generate_title_failed")
        return ""


async def _call_claude(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """Call Claude API for summarization."""
    import anthropic

    settings = get_settings()
    api_key = get_secret_or_env("claude-api-key", "ANTHROPIC_API_KEY")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=model or settings.llm.claude.model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.content[0].text
    logger.info("summarizer.claude_ok", chars=len(result))
    return result


async def _call_openai(
    prompt: str,
    *,
    model: str = "gpt-4o",
    max_tokens: int = 2048,
) -> str:
    """Call OpenAI API for summarization."""
    import openai

    api_key = get_secret_or_env("openai-api-key", "OPENAI_API_KEY")
    client = openai.AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.choices[0].message.content or ""
    logger.info("summarizer.openai_ok", chars=len(result))
    return result


async def _call_ollama(prompt: str) -> str:
    """Call local Ollama for summarization."""
    import httpx

    settings = get_settings()
    base_url = settings.llm.ollama.base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/api/generate",
            json={
                "model": settings.llm.ollama.model,
                "prompt": prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        result = resp.json()["response"]
        logger.info("summarizer.ollama_ok", chars=len(result))
        return result
