"""Main async pipeline orchestrator."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime
from typing import Any

import structlog

from onlime.config import get_settings
from onlime.models import ContentType, ProcessedEvent, RawEvent, SourceType
from onlime.outputs.vault import append_to_daily_note, write_note
from onlime.processors.categorizer import categorize, extract_hashtags
from onlime.processors.name_resolver import (
    VaultNameIndex,
    resolve_keywords,
    resolve_wikilinks,
)
from onlime.processors.action_items import extract_action_items, format_action_items_daily
from onlime.processors.summarizer import MIN_SUMMARIZE_LENGTH, generate_title, summarize
from onlime.state.store import StateStore

logger = structlog.get_logger()

# Samsung call recording: "통화 박도현 도도개발자_260403_224814.m4a"
_SAMSUNG_CALL_RE = re.compile(r"^통화\s+(.+?)_(\d{6})_(\d{6})\.m4a$")


def _dict_to_raw_event(data: dict[str, Any]) -> RawEvent:
    """Reconstruct a RawEvent from a queue dict."""
    return RawEvent(
        id=data["id"],
        source=SourceType(data["source"]),
        content_type=ContentType(data["content_type"]),
        raw_content=data["raw_content"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        metadata=data.get("metadata", {}),
    )


def _parse_recording_filename(filename: str) -> dict[str, Any]:
    """Parse Samsung recording filenames to extract contact, time, and type.

    Examples:
        "통화 박도현 도도개발자_260403_224814.m4a"
          → {"contact": "박도현 도도개발자", "recorded_at": datetime(2026,4,3,22,48,14), "type": "call"}
        "소프트파워로 경제 확장.m4a"
          → {"contact": None, "recorded_at": None, "type": "voice_memo"}
    """
    # macOS APFS uses NFD for filenames; normalize to NFC for regex matching
    filename = unicodedata.normalize("NFC", filename)
    m = _SAMSUNG_CALL_RE.match(filename)
    if m:
        contact = m.group(1).strip()
        date_str, time_str = m.group(2), m.group(3)
        try:
            year = 2000 + int(date_str[:2])
            month, day = int(date_str[2:4]), int(date_str[4:6])
            hour, minute, sec = int(time_str[:2]), int(time_str[2:4]), int(time_str[4:6])
            recorded_at = datetime(year, month, day, hour, minute, sec)
        except (ValueError, OverflowError):
            recorded_at = None
        return {"contact": contact, "recorded_at": recorded_at, "type": "call"}
    return {"contact": None, "recorded_at": None, "type": "voice_memo"}


def _make_title(raw: RawEvent) -> str:
    """Generate a title from content."""
    text = raw.raw_content.strip()
    # For links (including reclassified VIDEO/ARTICLE), use the URL as title hint
    if raw.content_type in (ContentType.LINK, ContentType.VIDEO, ContentType.ARTICLE):
        url_match = re.search(r"https?://\S+", text)
        url = url_match.group(0) if url_match else ""
        non_url = re.sub(r"https?://\S+", "", text).strip()
        return non_url[:60] if non_url else url[:60]
    # For voice, use metadata hint
    if raw.content_type == ContentType.VOICE:
        return text[:60]
    # General: first line or first 60 chars
    first_line = text.split("\n", 1)[0]
    return first_line[:60]


class Engine:
    """Async event processing engine with worker pool."""

    def __init__(self, state: StateStore) -> None:
        self.state = state
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self._telegram_app: Any = None  # for sending confirmations
        self._redirect_base_url: str | None = None  # http bridge for obsidian:// links
        self._name_index = VaultNameIndex()  # canonical wikilink resolver

    def set_telegram_app(self, app: Any) -> None:
        """Store reference to Telegram app for sending confirmations."""
        self._telegram_app = app

    def set_redirect_base_url(self, base_url: str) -> None:
        """Store the base URL of the local HTTP→obsidian:// redirect bridge."""
        self._redirect_base_url = base_url.rstrip("/")

    async def start(self, num_workers: int = 2) -> None:
        self._running = True
        # Build vault name index for wikilink canonicalization
        settings = get_settings()
        await asyncio.to_thread(self._name_index.build, settings.vault.root)
        for i in range(num_workers):
            task = asyncio.create_task(self._worker(f"worker-{i}"))
            self._workers.append(task)
        logger.info("engine.started", workers=num_workers, name_index=self._name_index.size)

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("engine.stopped")

    async def submit(self, event: dict[str, Any]) -> None:
        await self.queue.put(event)

    async def _worker(self, name: str) -> None:
        logger.info("worker.started", worker=name)
        while self._running:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process(event)
                self.queue.task_done()
            except Exception:
                logger.exception("worker.error", worker=name, event_id=event.get("id"))
                self.queue.task_done()

    # ------------------------------------------------------------------
    # Content-type enrichment helpers
    # ------------------------------------------------------------------

    async def _enrich_voice(
        self, raw: RawEvent, extra_fm: dict[str, Any], event_id: str,
    ) -> tuple[str, str | None, dict[str, Any]]:
        """STT + filename parsing for voice content.

        Returns (full_text, template_name, recording_info).
        """
        file_name = raw.metadata.get("file_name", "")
        recording_info = _parse_recording_filename(file_name)
        if recording_info["recorded_at"]:
            raw.timestamp = recording_info["recorded_at"]

        full_text = raw.raw_content
        template_name: str | None = None

        audio_path = raw.metadata.get("file_path")
        if audio_path:
            try:
                from onlime.processors.stt import transcribe
                full_text = await transcribe(audio_path)
                logger.info("engine.stt_done", event_id=event_id, chars=len(full_text))
                template_name = "recording.md.j2"
                extra_fm["transcript"] = full_text
                extra_fm["file_name"] = file_name
                size_bytes = raw.metadata.get("file_size")
                if size_bytes:
                    extra_fm["file_size_mb"] = round(size_bytes / (1024 * 1024), 2)
                extra_fm["recorded_at"] = raw.timestamp.isoformat()
            except Exception:
                logger.exception("engine.stt_failed", event_id=event_id)

        return full_text, template_name, recording_info

    async def _enrich_photo(
        self, raw: RawEvent, extra_fm: dict[str, Any], event_id: str,
    ) -> tuple[str, str | None]:
        """EXIF extraction + Claude Vision for photos.

        Returns (full_text, template_name).
        """
        full_text = raw.raw_content
        template_name: str | None = None

        image_path = raw.metadata.get("file_path")
        if not image_path:
            return full_text, template_name

        try:
            from onlime.processors.photo import analyze_photo, extract_metadata

            meta = await extract_metadata(image_path)
            logger.info("engine.photo_exif", event_id=event_id, meta_keys=list(meta.keys()))

            if meta.get("taken_at"):
                raw.timestamp = meta["taken_at"]
                extra_fm["taken_at"] = meta["taken_at"].strftime("%Y-%m-%d %H:%M:%S")
            if meta.get("camera"):
                extra_fm["camera"] = meta["camera"]
            if meta.get("gps_lat") is not None:
                extra_fm["gps_lat"] = meta["gps_lat"]
                extra_fm["gps_lon"] = meta["gps_lon"]
            if meta.get("location"):
                extra_fm["location"] = meta["location"]
            if meta.get("width"):
                extra_fm["width"] = meta["width"]
                extra_fm["height"] = meta["height"]
            if meta.get("file_size_mb"):
                extra_fm["file_size_mb"] = meta["file_size_mb"]

            vision = await analyze_photo(image_path)
            logger.info("engine.photo_vision", event_id=event_id, title=vision.get("title"))
            full_text = vision.get("description", "")
            extra_fm["photo_description"] = full_text
            extra_fm["vision_title"] = vision.get("title", "사진")
            extra_fm["vision_tags"] = vision.get("tags", [])
            template_name = "photo.md.j2"
        except Exception:
            logger.exception("engine.photo_failed", event_id=event_id)

        return full_text, template_name

    async def _enrich_web(
        self, raw: RawEvent, extra_fm: dict[str, Any], event_id: str,
    ) -> tuple[str, str | None]:
        """Firecrawl/trafilatura extraction for web links.

        Returns (full_text, template_name).
        """
        from onlime.connectors.web import extract_urls, fetch_content

        full_text = raw.raw_content
        template_name: str | None = None

        urls = extract_urls(raw.raw_content)
        if not urls:
            return full_text, template_name

        try:
            web_result = await fetch_content(urls[0])
            web_source_type = web_result.get("source_type", "article")
            extra_fm["url"] = web_result["url"]
            extra_fm["source_type"] = web_source_type
            if web_result.get("title") and web_result["title"] != urls[0]:
                extra_fm["web_title"] = web_result["title"]
            if web_result["text"]:
                full_text = web_result["text"]
                if web_result.get("creator"):
                    extra_fm["creator"] = web_result["creator"]
                if web_result.get("published_at"):
                    extra_fm["publish_date"] = web_result["published_at"]
                if web_result.get("og_image"):
                    extra_fm["og_image"] = web_result["og_image"]
                if web_result.get("description"):
                    extra_fm["description"] = web_result["description"]
                if web_result.get("transcript"):
                    extra_fm["transcript"] = web_result["transcript"]
            template_name = "resource.md.j2"
            # Reclassify ContentType so categorizer routes correctly
            if web_source_type == "youtube":
                raw.content_type = ContentType.VIDEO
            elif web_source_type in (
                "article", "newsletter", "blog", "conversation",
                "research", "community",
            ):
                raw.content_type = ContentType.ARTICLE
            # Generate meaningful title for conversations with generic titles
            if web_source_type == "conversation":
                web_title = extra_fm.get("web_title", "")
                _generic = {"claude", "chatgpt", "shared chat", "shared conversation", ""}
                if (
                    not web_title
                    or web_title.lower().strip() in _generic
                    or "share" in web_title.lower()
                    or web_title == urls[0]
                ):
                    generated = await generate_title(full_text)
                    if generated:
                        extra_fm["web_title"] = generated
                # Remove boilerplate description from share pages
                extra_fm.pop("description", None)
            logger.info(
                "engine.web_done", event_id=event_id,
                url=urls[0], source_type=web_source_type,
            )
        except Exception:
            logger.exception("engine.web_failed", event_id=event_id, url=urls[0])

        return full_text, template_name

    async def _send_telegram_confirmation(
        self, chat_id: int, message_id: int | None,
        note_path: Any, vault_root: Any, event_id: str,
    ) -> None:
        """Send Telegram confirmation with Obsidian deep-link."""
        from html import escape as html_escape
        from urllib.parse import quote

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode

        rel_path = note_path.relative_to(vault_root.expanduser())
        vault_name = vault_root.expanduser().name
        obsidian_file = str(rel_path.with_suffix("")).replace("\\", "/")

        link_url = (
            f"https://seetheeye-cdi.github.io/onlime-open/"
            f"?vault={quote(vault_name, safe='')}"
            f"&file={quote(obsidian_file, safe='/')}"
        )

        safe_path = html_escape(str(rel_path))
        html_text = f"저장했습니다\n📝 <code>{safe_path}</code>"
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📂 옵시디언에서 열기", url=link_url)]]
        )

        try:
            await self._telegram_app.bot.send_message(
                chat_id=chat_id, text=html_text,
                parse_mode=ParseMode.HTML, reply_to_message_id=message_id,
                disable_web_page_preview=True, reply_markup=keyboard,
            )
        except Exception:
            logger.warning("engine.telegram_link_failed", event_id=event_id)
            await self._telegram_app.bot.send_message(
                chat_id=chat_id,
                text=f"저장했습니다: `{rel_path}`\n{link_url}",
                reply_to_message_id=message_id,
                disable_web_page_preview=True,
            )

    async def _send_action_items_telegram(
        self, chat_id: int, action_items: list[dict], event_id: str,
    ) -> None:
        """Send action items as Telegram message with inline complete buttons."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode

        lines = ["<b>액션 아이템:</b>"]
        buttons: list[list[InlineKeyboardButton]] = []
        for item in action_items:
            task_text = item["task"]
            owner = f" (담당: {item['owner']})" if item.get("owner") else ""
            lines.append(f"- {task_text}{owner}")

        text = "\n".join(lines)
        if len(text) > 4096:
            text = text[:4090] + "..."

        try:
            await self._telegram_app.bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.warning("engine.action_items_telegram_failed", event_id=event_id)

    # ------------------------------------------------------------------
    # Main pipeline orchestrator
    # ------------------------------------------------------------------

    async def _process(self, event: dict[str, Any]) -> None:
        """Process a single event through the pipeline.

        Stages: Save → Enrich → Summarize → Categorize → Write → Confirm.
        """
        from onlime.connectors.progress import ProgressReporter
        from onlime.errors import humanize_error

        event_id = event.get("id", "unknown")
        logger.info("engine.processing", event_id=event_id)

        chat_id = event.pop("_telegram_chat_id", None)
        message_id = event.pop("_telegram_message_id", None)

        raw = _dict_to_raw_event(event)
        progress = await ProgressReporter.create(self._telegram_app, chat_id, message_id)

        # 1. Save to state DB (or allow retry of failed events)
        saved = await self.state.save_event(
            event_id=raw.id, source_type=raw.source.value,
            source_id=raw.id, connector_name=raw.source.value, payload=event,
        )
        if not saved:
            existing = await self.state.get_event(raw.id)
            if existing and existing["status"] == "pending" and existing["retry_count"] > 0:
                logger.info("engine.retry", event_id=event_id, attempt=existing["retry_count"])
            else:
                logger.info("engine.duplicate", event_id=event_id)
                return

        await self.state.update_event_status(raw.id, "processing")

        try:
            full_text = raw.raw_content
            extra_fm: dict[str, Any] = {}
            template_name: str | None = None
            recording_info: dict[str, Any] = {}

            # 2. Content-type enrichment
            if raw.content_type == ContentType.VOICE:
                await progress.update("🎤 음성 변환 중...")
                full_text, template_name, recording_info = await self._enrich_voice(
                    raw, extra_fm, event_id,
                )
            elif raw.content_type == ContentType.PHOTO:
                await progress.update("📷 사진 분석 중...")
                full_text, template_name = await self._enrich_photo(
                    raw, extra_fm, event_id,
                )
            elif raw.content_type == ContentType.LINK:
                await progress.update("🌐 웹 콘텐츠 추출 중...")
                full_text, template_name = await self._enrich_web(
                    raw, extra_fm, event_id,
                )

            # 3. Summarize (skip for PHOTO — Vision result serves as summary)
            await progress.update("✍️ 요약 생성 중...")
            if raw.content_type == ContentType.PHOTO:
                summary = full_text
            else:
                prompt_type = "general"
                if raw.source in (SourceType.KAKAO, SourceType.SLACK):
                    prompt_type = "chat"
                elif raw.content_type in (ContentType.LINK, ContentType.ARTICLE, ContentType.VIDEO):
                    prompt_type = "article"
                elif raw.content_type == ContentType.VOICE:
                    prompt_type = "voice_memo"
                summary = await summarize(full_text, prompt_type)

            if summary:
                summary = resolve_wikilinks(summary, self._name_index)

            # 3a. Extract action items (voice, chat messages)
            action_items: list[dict] = []
            if raw.content_type in (ContentType.VOICE, ContentType.MESSAGE) or \
               raw.source in (SourceType.KAKAO, SourceType.SLACK):
                try:
                    meeting_ctx = None
                    if meeting_event:
                        meeting_ctx = {
                            "attendees": meeting_event.get("attendees", []),
                            "project": meeting_event.get("project"),
                        }
                    action_items = await extract_action_items(
                        full_text,
                        meeting_context=meeting_ctx,
                    )
                    if action_items:
                        logger.info("engine.action_items", event_id=event_id, count=len(action_items))
                except Exception:
                    logger.warning("engine.action_items_failed", event_id=event_id)

            # 4. Extract keywords
            keywords: list[str] = []
            if raw.content_type == ContentType.PHOTO:
                keywords = extra_fm.get("vision_tags", [])
                keywords = resolve_keywords(keywords, self._name_index)
            else:
                try:
                    from onlime.processors.keywords import extract_keywords, to_wikilinks
                    keywords = await extract_keywords(full_text)
                    keywords = resolve_keywords(keywords, self._name_index)
                    logger.info("engine.keywords", event_id=event_id, count=len(keywords))
                except Exception:
                    logger.warning("engine.keywords_failed", event_id=event_id)

            # 5. Categorize + build ProcessedEvent
            category = categorize(raw)
            title = extra_fm.get("web_title") or _make_title(raw)
            hashtags = extract_hashtags(raw.raw_content)
            hashtags.extend(raw.metadata.get("hashtags", []))
            people: list[str] = []

            # Calendar matching for voice recordings
            meeting_event: dict[str, Any] | None = None
            if raw.content_type == ContentType.VOICE and recording_info.get("recorded_at"):
                try:
                    from onlime.connectors.gcal import find_overlapping_event
                    meeting_event = await find_overlapping_event(raw.timestamp)
                except Exception:
                    logger.warning("engine.gcal_lookup_failed", event_id=event_id)

            if raw.content_type == ContentType.PHOTO:
                title = f"{extra_fm.get('vision_title', '사진')}-사진"
                logger.info("engine.photo_title", event_id=event_id, title=title)
            elif raw.content_type == ContentType.VOICE and full_text and full_text != raw.raw_content:
                contact = recording_info.get("contact")
                rec_type = recording_info.get("type", "voice_memo")
                if contact:
                    people.append(contact)

                if meeting_event:
                    # Meeting recording: use calendar event info
                    extra_fm["meeting_title"] = meeting_event["summary"]
                    if meeting_event.get("attendees"):
                        extra_fm["attendees"] = meeting_event["attendees"]
                    if meeting_event.get("project"):
                        extra_fm["project"] = meeting_event["project"]
                    recording_info["type"] = "meeting"
                    title = f"{meeting_event['summary']}-음성-미팅"
                    logger.info("engine.meeting_matched", event_id=event_id, title=title)
                else:
                    generated = await generate_title(full_text)
                    topic = generated or _make_title(raw)
                    type_suffix = "통화" if rec_type == "call" else "메모"
                    title = f"{topic}-음성-{type_suffix}"
                    logger.info("engine.title_generated", event_id=event_id, title=title)

            if keywords:
                from onlime.processors.keywords import to_wikilinks
                extra_fm["keywords"] = to_wikilinks(keywords)

            if action_items:
                extra_fm["action_items"] = action_items

            processed = ProcessedEvent(
                raw_event_id=raw.id, title=title, summary=summary,
                full_text=full_text, category=category, timestamp=raw.timestamp,
                tags=list(set(hashtags)), people=people,
            )

            # 6. Write to vault
            settings = get_settings()
            vault_root = settings.vault.root
            note_path = write_note(vault_root, category, processed, template_name, extra_fm)
            processed.vault_path = str(note_path)

            # 6a. Append to daily note
            if raw.content_type == ContentType.VOICE:
                try:
                    time_str = raw.timestamp.strftime("%H:%M")
                    rec_type = recording_info.get("type", "voice_memo")
                    if rec_type == "meeting":
                        emoji = "📅"
                    elif rec_type == "call":
                        emoji = "📞"
                    else:
                        emoji = "🎙️"
                    note_link = f"[[{note_path.stem}]]"
                    first_sentence = summary.split("\n", 1)[0][:80] if summary else ""
                    entry = f"- {time_str} {emoji} {note_link} — {first_sentence}"
                    # Append project wikilink if meeting has a project
                    if rec_type == "meeting" and extra_fm.get("project"):
                        entry += f" [[{extra_fm['project']}]]"
                    append_to_daily_note(vault_root, raw.timestamp, entry, note_link)
                except Exception:
                    logger.warning("engine.daily_note_failed", event_id=event_id)
            elif raw.content_type == ContentType.PHOTO:
                try:
                    time_str = raw.timestamp.strftime("%H:%M")
                    note_link = f"[[{note_path.stem}]]"
                    location = extra_fm.get("location", "").split(",")[0] if extra_fm.get("location") else ""
                    suffix = f" @ {location}" if location else ""
                    entry = f"- {time_str} 📷 {note_link}{suffix}"
                    append_to_daily_note(vault_root, raw.timestamp, entry, note_link)
                except Exception:
                    logger.warning("engine.daily_note_failed", event_id=event_id)
            elif raw.content_type in (ContentType.LINK, ContentType.ARTICLE, ContentType.VIDEO):
                try:
                    time_str = raw.timestamp.strftime("%H:%M")
                    note_link = f"[[{note_path.stem}]]"
                    first_sentence = summary.split("\n", 1)[0][:80] if summary else ""
                    if raw.content_type == ContentType.VIDEO:
                        emoji = "🎬"
                    elif raw.content_type == ContentType.ARTICLE:
                        emoji = "📰"
                    else:
                        emoji = "🔗"
                    entry = f"- {time_str} {emoji} {note_link} — {first_sentence}"
                    append_to_daily_note(vault_root, raw.timestamp, entry, note_link)
                except Exception:
                    logger.warning("engine.daily_note_link_failed", event_id=event_id)

            # 6b. Save action items to task_queue + daily todo
            if action_items:
                import json as _json
                for item in action_items:
                    item["source_note"] = note_path.stem
                try:
                    for item in action_items:
                        task_id = await self.state.enqueue_task(
                            "action_item", str(note_path), priority=3,
                        )
                        await self.state.db.execute(
                            "UPDATE task_queue SET result = ? WHERE id = ?",
                            (_json.dumps(item, ensure_ascii=False), task_id),
                        )
                    await self.state.db.commit()
                except Exception:
                    logger.warning("engine.action_items_save_failed", event_id=event_id)
                try:
                    from onlime.outputs.vault import append_to_daily_todo
                    append_to_daily_todo(vault_root, raw.timestamp, action_items)
                except Exception:
                    logger.warning("engine.action_items_daily_failed", event_id=event_id)

            # 7. Update state
            await self.state.update_event_status(raw.id, "done", obsidian_path=str(note_path))
            logger.info("engine.done", event_id=event_id, vault_path=str(note_path))

            # 8. Send Telegram confirmation
            await progress.delete()
            if chat_id and self._telegram_app:
                await self._send_telegram_confirmation(
                    chat_id, message_id, note_path, vault_root, event_id,
                )
                # 8a. Send action items with inline buttons
                if action_items:
                    await self._send_action_items_telegram(
                        chat_id, action_items, event_id,
                    )

        except Exception as exc:
            await self.state.update_event_status(raw.id, "failed", error=str(exc))
            logger.exception("engine.failed", event_id=event_id)

            await progress.delete()
            if chat_id and self._telegram_app:
                await self._telegram_app.bot.send_message(
                    chat_id=chat_id, text=f"⚠️ {humanize_error(exc)}",
                    reply_to_message_id=message_id,
                )
