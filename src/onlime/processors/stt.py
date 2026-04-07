"""Speech-to-text via faster-whisper."""

from __future__ import annotations

from pathlib import Path

import structlog

from onlime.config import get_settings

logger = structlog.get_logger()

_model = None


def _get_model():
    """Lazy-load the whisper model (heavy, only load once)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        settings = get_settings()
        stt = settings.stt
        _model = WhisperModel(
            stt.model,
            device=stt.device,
            compute_type=stt.compute_type,
        )
        logger.info("stt.model_loaded", model=stt.model, device=stt.device)
    return _model


async def transcribe(audio_path: str | Path) -> str:
    """Transcribe an audio file to text.

    Runs the CPU-bound whisper inference in a thread executor.
    """
    import asyncio

    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _transcribe_sync, str(path))
    return result


def _transcribe_sync(audio_path: str) -> str:
    """Synchronous transcription."""
    settings = get_settings()
    stt = settings.stt
    model = _get_model()

    segments, info = model.transcribe(
        audio_path,
        language=stt.language,
        beam_size=stt.beam_size,
        initial_prompt=stt.initial_prompt,
    )

    texts = []
    for segment in segments:
        texts.append(segment.text.strip())

    full_text = " ".join(texts)
    logger.info("stt.transcribed", path=audio_path, chars=len(full_text), language=info.language)
    return full_text
