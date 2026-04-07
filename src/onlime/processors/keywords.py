"""LLM-based keyword extractor → [[wikilink]] formatted keywords."""

from __future__ import annotations

import re

import structlog

from onlime.llm import LLMError, call_llm_json

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


_MAX_KEYWORD_INPUT = 3000


async def extract_keywords(text: str) -> list[str]:
    """Extract keywords from text using LLM.

    Returns a list of keyword strings (without [[ ]] brackets).
    """
    if len(text) < 50:
        return []

    truncated = text[:_MAX_KEYWORD_INPUT] if len(text) > _MAX_KEYWORD_INPUT else text
    prompt = _PROMPT.format(text=truncated)

    try:
        return await call_llm_json(prompt, caller="keywords")
    except LLMError:
        return _fallback_extract(text)


def to_wikilinks(keywords: list[str]) -> list[str]:
    """Convert keyword list to [[wikilink]] format."""
    return [f"[[{kw}]]" for kw in keywords if kw.strip()]


def _fallback_extract(text: str) -> list[str]:
    """Simple fallback: extract quoted terms and proper nouns."""
    # Extract quoted strings
    quoted = re.findall(r'["\u201c]([^"\u201d]+)["\u201d]', text)
    # Extract hashtag-like terms
    hashtags = re.findall(r"#(\w+)", text)
    combined = list(dict.fromkeys(quoted + hashtags))  # dedupe
    return combined[:10]
