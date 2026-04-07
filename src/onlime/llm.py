"""Unified LLM call utilities with Claude → OpenAI → Ollama fallback chain."""

from __future__ import annotations

import json
import re

import structlog

from onlime.config import get_settings
from onlime.security.secrets import get_secret_or_env

logger = structlog.get_logger()


class LLMError(Exception):
    """Raised when all LLM providers fail."""


async def _call_claude(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
) -> str:
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
    logger.info("llm.claude_ok", chars=len(result))
    return result


async def _call_openai(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
) -> str:
    import openai

    settings = get_settings()
    api_key = get_secret_or_env("openai-api-key", "OPENAI_API_KEY")
    client = openai.AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model=model or settings.llm.openai_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.choices[0].message.content or ""
    logger.info("llm.openai_ok", chars=len(result))
    return result


async def _call_ollama(
    prompt: str,
    *,
    max_tokens: int = 2048,
) -> str:
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
        logger.info("llm.ollama_ok", chars=len(result))
        return result


async def call_llm(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
    caller: str = "",
) -> str:
    """Call LLM with Claude → OpenAI → Ollama fallback chain.

    Returns the raw text response. Raises LLMError if all providers fail.
    """
    log_ctx = {"caller": caller} if caller else {}

    try:
        return await _call_claude(prompt, model=model, max_tokens=max_tokens)
    except Exception as exc:
        logger.warning("llm.claude_failed", error=str(exc), **log_ctx)

    try:
        return await _call_openai(prompt, max_tokens=max_tokens)
    except Exception as exc:
        logger.warning("llm.openai_failed", error=str(exc), **log_ctx)

    try:
        return await _call_ollama(prompt, max_tokens=max_tokens)
    except Exception as exc:
        logger.warning("llm.ollama_failed", error=str(exc), **log_ctx)

    raise LLMError("All LLM providers failed")


def _parse_json_list(raw: str) -> list[str]:
    """Parse a JSON array from LLM response, tolerating extra text."""
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return [str(item).strip() for item in result if item]
        except json.JSONDecodeError:
            pass
    items = re.findall(r'"([^"]+)"', raw)
    return items[:10] if items else []


async def call_llm_json(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 256,
    caller: str = "",
) -> list[str]:
    """Call LLM and parse JSON array from response.

    Returns parsed list. Raises LLMError if all providers fail.
    """
    raw = await call_llm(prompt, model=model, max_tokens=max_tokens, caller=caller)
    return _parse_json_list(raw)
