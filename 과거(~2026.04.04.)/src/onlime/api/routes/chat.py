"""AI Chat endpoint using Claude API."""

from __future__ import annotations

import os
import logging
import httpx
from fastapi import APIRouter, HTTPException

from onlime.api.models import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are the Onlime AI Assistant, a helpful AI that assists with personal workflow management.
You have knowledge of the user's calendar events, meeting notes, and Plaud recordings.
Respond in the user's preferred language (Korean or English).
Be concise and helpful."""


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to Claude API and return the response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured",
        )

    messages = [{"role": "user", "content": req.message}]
    if req.context:
        messages[0]["content"] = f"Context: {req.context}\n\nUser: {req.message}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6-20250514",
                    "max_tokens": 4096,
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                },
            )

        if resp.status_code != 200:
            logger.error("Claude API error: %s %s", resp.status_code, resp.text)
            raise HTTPException(
                status_code=502,
                detail=f"Claude API returned {resp.status_code}",
            )

        data = resp.json()
        content_blocks = data.get("content", [])

        reply_text = ""
        thinking_text = ""
        for block in content_blocks:
            if block.get("type") == "text":
                reply_text += block.get("text", "")
            elif block.get("type") == "thinking":
                thinking_text += block.get("thinking", "")

        return ChatResponse(
            reply=reply_text,
            thinking=thinking_text or None,
        )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Claude API timeout")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat error")
        raise HTTPException(status_code=500, detail="Internal chat error")
