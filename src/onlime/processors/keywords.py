"""LLM-based keyword extractor → [[wikilink]] formatted keywords."""

from __future__ import annotations

import json
import re

import structlog

from onlime.config import get_settings
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()

_PROMPT = """다음 텍스트에서 핵심 키워드를 5~10개 추출해주세요.

규칙:
- 고유명사(인물, 회사, 제품, 브랜드)는 반드시 포함
- 핵심 주제/개념 키워드 포함
- 너무 일반적인 단어(것, 이것, 그것)는 제외
- 고유명사는 [[한국어 English]] 형태로 작성 (예: "앤트로픽 Anthropic", "드류 벤트 Drew Bent")
- 한국어가 원래 이름이면 영어 병기 불필요 (예: "토스", "카카오페이")
- JSON 배열로만 응답하세요. 다른 텍스트 없이.

예시 응답: ["앤트로픽 Anthropic", "프롬프트 엔지니어링", "이승건", "브랜딩"]

텍스트:
{text}"""


async def extract_keywords(text: str) -> list[str]:
    """Extract keywords from text using LLM.

    Returns a list of keyword strings (without [[ ]] brackets).
    """
    if len(text) < 50:
        return []

    # Truncate very long text for the keyword prompt
    truncated = text[:3000] if len(text) > 3000 else text
    prompt = _PROMPT.format(text=truncated)

    try:
        return await _call_claude(prompt)
    except Exception as exc:
        logger.warning("keywords.claude_failed", error=str(exc))

    try:
        return await _call_openai(prompt)
    except Exception as exc:
        logger.warning("keywords.openai_failed", error=str(exc))

    try:
        return await _call_ollama(prompt)
    except Exception as exc:
        logger.warning("keywords.ollama_failed", error=str(exc))

    # Fallback: simple regex-based extraction
    return _fallback_extract(text)


def to_wikilinks(keywords: list[str]) -> list[str]:
    """Convert keyword list to [[wikilink]] format."""
    return [f"[[{kw}]]" for kw in keywords if kw.strip()]


async def _call_claude(prompt: str) -> list[str]:
    """Call Claude for keyword extraction."""
    import anthropic

    settings = get_settings()
    api_key = get_secret_or_env("claude-api-key", "ANTHROPIC_API_KEY")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=settings.llm.claude.model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    return _parse_json_list(raw)


async def _call_openai(prompt: str) -> list[str]:
    """Call OpenAI for keyword extraction."""
    import openai

    api_key = get_secret_or_env("openai-api-key", "OPENAI_API_KEY")
    client = openai.AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model="gpt-4o",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = (response.choices[0].message.content or "").strip()
    return _parse_json_list(raw)


async def _call_ollama(prompt: str) -> list[str]:
    """Call Ollama for keyword extraction."""
    import httpx

    settings = get_settings()
    base_url = settings.llm.ollama.base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base_url}/api/generate",
            json={
                "model": settings.llm.ollama.model,
                "prompt": prompt,
                "stream": False,
            },
        )
        resp.raise_for_status()
        raw = resp.json()["response"].strip()
        return _parse_json_list(raw)


def _parse_json_list(raw: str) -> list[str]:
    """Parse a JSON array from LLM response, tolerating extra text."""
    # Find JSON array in response
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return [str(item).strip() for item in result if item]
        except json.JSONDecodeError:
            pass
    # Fallback: split by comma/newline
    items = re.findall(r'"([^"]+)"', raw)
    return items[:10] if items else []


def _fallback_extract(text: str) -> list[str]:
    """Simple fallback: extract quoted terms and proper nouns."""
    # Extract quoted strings
    quoted = re.findall(r'["\u201c]([^"\u201d]+)["\u201d]', text)
    # Extract hashtag-like terms
    hashtags = re.findall(r"#(\w+)", text)
    combined = list(dict.fromkeys(quoted + hashtags))  # dedupe
    return combined[:10]
