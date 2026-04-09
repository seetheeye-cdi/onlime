from __future__ import annotations

import asyncio

import pytest

import onlime.processors.transcript_proofreader as proofreader


@pytest.mark.asyncio
async def test_proofread_transcript_preserves_chunk_order_under_parallelism(monkeypatch):
    monkeypatch.setattr(proofreader, "_MIN_PROOFREAD_LENGTH", 1)
    monkeypatch.setattr(proofreader, "_split_chunks", lambda text: ["A", "B", "C"])
    monkeypatch.setattr(proofreader, "format_one_sentence_per_line", lambda text: text)

    delays = {"A": 0.06, "B": 0.01, "C": 0.03}

    async def fake_call(chunk: str) -> str:
        await asyncio.sleep(delays[chunk])
        return f"{chunk}-ok"

    monkeypatch.setattr(proofreader, "_call_claude", fake_call)

    result = await proofreader.proofread_transcript("dummy transcript")

    assert result == "A-ok\nB-ok\nC-ok"
