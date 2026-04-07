"""Event processors: summarization, categorization, STT."""

from onlime.processors.categorizer import categorize, extract_hashtags
from onlime.processors.summarizer import summarize

__all__ = ["categorize", "extract_hashtags", "summarize"]

# stt is imported lazily (heavy model) — use: from onlime.processors.stt import transcribe
