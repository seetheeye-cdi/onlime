"""Web content extractor with URL-type routing.

Strategy:
- YouTube  → youtube-transcript-api + yt-dlp (unchanged, works well)
- All other URLs → Firecrawl first (JS rendering, markdown output, metadata)
- Fallback → trafilatura when Firecrawl fails or returns empty body

Firecrawl is the DEFAULT for all non-YouTube URLs. It handles JS-heavy sites,
Korean communities (DCInside, 클리앙, 루리웹, 에펨코리아, 뽐뿌, 더쿠, Brunch),
social platforms, newsletters, and general blogs/articles uniformly.
Trafilatura is kept as a lightweight fallback for when Firecrawl is unavailable.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
import structlog

from onlime.config import get_settings

logger = structlog.get_logger()

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Firecrawl API key availability (cached after first check)
_firecrawl_available: bool | None = None


def _check_firecrawl() -> bool:
    """Check if Firecrawl API key is configured. Cached after first call."""
    global _firecrawl_available
    if _firecrawl_available is not None:
        return _firecrawl_available
    try:
        from onlime.security.secrets import get_secret_or_env
        get_secret_or_env("firecrawl-api-key", "FIRECRAWL_API_KEY")
        _firecrawl_available = True
    except (RuntimeError, Exception):
        logger.warning("web.firecrawl_not_configured")
        _firecrawl_available = False
    return _firecrawl_available


def _validate_url(url: str) -> None:
    """Reject URLs targeting private/internal networks (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Blocked URL scheme: {parsed.scheme}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("Missing hostname")
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError(f"Blocked private/internal address: {hostname}")
    except socket.gaierror:
        pass  # unresolvable host will fail on actual request


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from text, stripping trailing punctuation."""
    raw = _URL_RE.findall(text)
    return [u.rstrip(".,;:!?)>]}'\"") for u in raw]


_SENTENCE_SPLIT_RE = re.compile(r"([.!?。！？])\s+")


def _format_transcript(text: str) -> str:
    """Split a transcript into one sentence per line for readability."""
    if not text:
        return ""
    # Insert newline after sentence-ending punctuation followed by whitespace.
    formatted = _SENTENCE_SPLIT_RE.sub(r"\1\n", text)
    # Collapse accidental double newlines and trim.
    return re.sub(r"\n{2,}", "\n", formatted).strip()


# ---------------------------------------------------------------------------
# URL Type Detection
# ---------------------------------------------------------------------------

_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "music.youtube.com",
}

# Twitter / X — need oEmbed extraction (JS-gated, Firecrawl fails)
_TWITTER_HOSTS = {
    "twitter.com", "www.twitter.com",
    "x.com", "www.x.com",
    "mobile.twitter.com", "mobile.x.com",
}

# AI conversation sharing platforms
_CONVERSATION_HOSTS = {
    "claude.ai", "chatgpt.com", "chat.openai.com",
    "gemini.google.com", "deepseek.com", "chat.deepseek.com",
    "perplexity.ai", "www.perplexity.ai",
    "poe.com",
}

# Research / academic platforms — source_type "article" but need cleanup
_RESEARCH_HOSTS = {
    "arxiv.org", "www.arxiv.org",
    "scholar.google.com",
    "semanticscholar.org", "www.semanticscholar.org",
    "openreview.net",
    "papers.ssrn.com",
    "pubmed.ncbi.nlm.nih.gov",
}

# Korean community / forum sites
_COMMUNITY_HOSTS = {
    "dcinside.com", "www.dcinside.com", "m.dcinside.com",
    "clien.net", "www.clien.net",
    "ruliweb.com", "www.ruliweb.com",
    "fmkorea.com", "www.fmkorea.com",
    "ppomppu.co.kr", "www.ppomppu.co.kr",
    "theqoo.net", "www.theqoo.net",
    "instiz.net", "www.instiz.net",
    "mlbpark.donga.com",
    "todayhumor.co.kr", "www.todayhumor.co.kr",
    "ilbe.com", "www.ilbe.com",
    "bobaedream.co.kr", "www.bobaedream.co.kr",
    "82cook.com", "www.82cook.com",
    "community.naver.com",
    "cafe.naver.com",
    # Global community/social
    "reddit.com", "www.reddit.com", "old.reddit.com",
    "threads.net", "www.threads.net",
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "instagram.com", "www.instagram.com",
    "linkedin.com", "www.linkedin.com",
    "tiktok.com", "www.tiktok.com",
}

# Blog / personal publishing platforms
_BLOG_HOSTS = {
    "brunch.co.kr", "brunch.kakao.com",
    "velog.io",
    "medium.com",
    "wordpress.com",
    "ghost.io",
}

# Newsletter platforms (also *.substack.com wildcard — checked separately)
_NEWSLETTER_HOSTS = {
    "substack.com",
    "mailchi.mp",
    "buttondown.email",
    "convertkit.com",
    "beehiiv.com",
}

# Korean/global news outlets — source_type "article"
_NEWS_HOSTS = {
    "chosun.com", "www.chosun.com",
    "donga.com", "www.donga.com",
    "joongang.co.kr", "www.joongang.co.kr",
    "hani.co.kr", "www.hani.co.kr",
    "ohmynews.com", "www.ohmynews.com",
    "yonhapnews.co.kr", "www.yonhapnews.co.kr",
    "yna.co.kr", "www.yna.co.kr",
    "khan.co.kr", "www.khan.co.kr",
    "hankyung.com", "www.hankyung.com",
    "mk.co.kr", "www.mk.co.kr",
    "zdnet.co.kr", "www.zdnet.co.kr",
    "n.news.naver.com",
    "news.naver.com",
    "blog.naver.com",
    "naver.com", "m.naver.com",
    "techcrunch.com",
    "theverge.com",
    "wired.com",
    "arstechnica.com",
    "bloomberg.com", "www.bloomberg.com",
    "ft.com", "www.ft.com",
    "nytimes.com", "www.nytimes.com",
}


def _source_type_for_host(host: str) -> str:
    """Derive a semantic source_type string from the hostname.

    Returns one of: youtube, conversation, community, blog, newsletter,
    research, article.  'article' is the default for unknown sites.
    """
    host = host.lower()

    if host in _CONVERSATION_HOSTS or host.endswith(".claude.ai"):
        return "conversation"
    if host in _RESEARCH_HOSTS:
        return "research"
    if host in _COMMUNITY_HOSTS:
        return "community"
    if host in _NEWSLETTER_HOSTS or host.endswith(".substack.com"):
        return "newsletter"
    if (
        host in _BLOG_HOSTS
        or host.endswith(".tistory.com")
        or host.endswith(".wordpress.com")
        or host.endswith(".medium.com")
        or host.endswith(".ghost.io")
    ):
        return "blog"
    if host in _NEWS_HOSTS:
        return "article"
    return "article"


def _classify_url(url: str) -> str:
    """Classify URL: 'youtube', 'twitter', or 'web' (everything else)."""
    host = (urlparse(url).hostname or "").lower()
    if host in _YOUTUBE_HOSTS:
        return "youtube"
    if host in _TWITTER_HOSTS:
        return "twitter"
    return "web"


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

async def fetch_content(url: str) -> dict[str, str]:
    """Fetch and extract content from any URL.

    Routing:
      1. YouTube  → dedicated extractor (transcript + yt-dlp metadata)
      2. All else → Firecrawl first (JS rendering, structured metadata)
      3. Fallback → trafilatura when Firecrawl fails or body is empty

    Returns a dict with guaranteed keys: title, text, url, source_type.
    Optional keys: creator, description, published_at, og_image, transcript.
    """
    # SSRF protection: reject private/internal network targets
    _validate_url(url)

    host = urlparse(url).hostname or ""
    url_type = _classify_url(url)
    logger.info("web.routing", url=url, type=url_type, host=host)

    if url_type == "youtube":
        return await _fetch_youtube(url)

    if url_type == "twitter":
        try:
            result = await _fetch_twitter(url)
            if result and result.get("text", "").strip():
                return result
        except Exception as exc:
            logger.warning("web.twitter_oembed_failed", url=url, error=str(exc))
        # Fall through to Firecrawl/trafilatura as last resort

    # --- Firecrawl-first for ALL non-YouTube URLs ---
    result: dict[str, str] | None = None

    if _check_firecrawl():
        try:
            result = await _fetch_firecrawl(url)
            # Only accept if Firecrawl returned meaningful body content
            if not result.get("text", "").strip():
                logger.warning("web.firecrawl_empty", url=url)
                result = None
        except Exception as exc:
            logger.warning("web.firecrawl_failed", url=url, error=str(exc))

    # --- Trafilatura fallback ---
    if result is None:
        try:
            result = await _fetch_trafilatura(url)
            if not result.get("text", "").strip():
                logger.warning("web.trafilatura_empty", url=url)
                result = None
        except Exception:
            logger.warning("web.trafilatura_failed", url=url)

    if result is None:
        # Last-resort stub — pipeline must not crash on empty body
        return {
            "title": url,
            "text": "",
            "url": url,
            "source_type": _source_type_for_host(host),
        }

    # --- Post-processing: AI conversation cleanup ---
    if _is_conversation_url(url):
        text, participant = _clean_conversation(result["text"])
        result["text"] = text
        if participant:
            result["creator"] = participant
        logger.info("web.conversation_cleaned", url=url, participant=participant)

    return result


# ---------------------------------------------------------------------------
# YouTube Extractor (unchanged — works well)
# ---------------------------------------------------------------------------

async def _fetch_youtube(url: str) -> dict[str, str]:
    """Extract YouTube transcript + metadata, then proofread the transcript."""
    import asyncio

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _youtube_sync, url)

    # Claude proofread pass: fix Korean STT errors, spacing, punctuation,
    # enforce one-sentence-per-line. Runs only when transcript is non-empty.
    raw_transcript = result.get("transcript", "")
    if raw_transcript:
        try:
            from onlime.processors.transcript_proofreader import proofread_transcript
            corrected = await proofread_transcript(raw_transcript)
            if corrected and corrected != raw_transcript:
                result["transcript"] = corrected
                # Rebuild combined `text` so the summarizer sees the fixed version.
                description = result.get("description", "")
                parts = [p for p in (description, corrected) if p]
                result["text"] = "\n\n".join(parts) if parts else result.get("text", "")
                logger.info(
                    "web.youtube_proofread_ok",
                    before=len(raw_transcript),
                    after=len(corrected),
                )
        except Exception:
            logger.warning("web.youtube_proofread_failed")

    return result


def _youtube_sync(url: str) -> dict[str, str]:
    """Synchronous YouTube extraction (runs in a thread executor)."""
    video_id = _extract_youtube_id(url)
    if not video_id:
        raise ValueError(f"Cannot extract video ID from: {url}")

    title = ""
    description = ""
    creator = ""

    # 1. Metadata via yt-dlp (no download)
    try:
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                title = info.get("title", "")
                description = info.get("description", "")
                creator = info.get("channel", "") or info.get("uploader", "")
    except Exception:
        logger.warning("web.yt_dlp_failed", url=url)

    # 2. Transcript via youtube-transcript-api v1.2+
    transcript_text = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["ko", "en"])
        transcript_text = _format_transcript(" ".join(s.text for s in fetched.snippets))
        logger.info("web.youtube_transcript_ok", video_id=video_id, chars=len(transcript_text))
    except Exception:
        logger.warning("web.youtube_transcript_failed", video_id=video_id)
        # Fallback: any auto-generated transcript
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            generated = transcript_list.find_generated_transcript(["ko", "en"])
            fetched = generated.fetch()
            transcript_text = _format_transcript(" ".join(s.text for s in fetched.snippets))
        except Exception:
            logger.warning("web.youtube_transcript_generated_failed", video_id=video_id)

    parts = []
    if description:
        parts.append(description)
    if transcript_text:
        parts.append(transcript_text)

    full_text = "\n\n".join(parts) if parts else f"YouTube 영상: {url}"

    logger.info("web.youtube_ok", video_id=video_id, title=title[:50], creator=creator, chars=len(full_text))
    return {
        "title": title or f"YouTube: {video_id}",
        "text": full_text,
        "url": url,
        "source_type": "youtube",
        "creator": creator,
        "description": description,
        "transcript": transcript_text,
    }


def _extract_youtube_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    parsed = urlparse(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0]
    if "youtube.com" in (parsed.hostname or ""):
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
        # /shorts/VIDEO_ID, /live/VIDEO_ID, /embed/VIDEO_ID
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
            return parts[1]
    return None


# ---------------------------------------------------------------------------
# Twitter / X Extractor — FxTwitter API (free, full text, no auth)
# ---------------------------------------------------------------------------

_TWEET_ID_RE = re.compile(r"/status/(\d+)")


async def _fetch_twitter(url: str) -> dict[str, str]:
    """Extract tweet content via FxTwitter API.

    Twitter/X blocks all non-browser requests (Firecrawl gets
    "JavaScript is not available"). FxTwitter is a free public API
    that returns full tweet text, media, quote tweets, and metrics.
    """
    # Extract username and tweet ID from URL
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) < 3:
        raise ValueError(f"Cannot parse tweet URL: {url}")
    username = path_parts[0]
    tid_match = _TWEET_ID_RE.search(url)
    if not tid_match:
        raise ValueError(f"No tweet ID in URL: {url}")

    api_url = f"https://api.fxtwitter.com/{username}/status/{tid_match.group(1)}"

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Onlime/1.0)"},
    ) as client:
        resp = await client.get(api_url)
        resp.raise_for_status()
        data = resp.json()

    tweet = data.get("tweet", {})
    text = tweet.get("text", "")
    author = tweet.get("author", {}).get("name", "")
    handle = tweet.get("author", {}).get("screen_name", "")

    # Append quote tweet if present
    quote = tweet.get("quote")
    if quote:
        qt_author = quote.get("author", {}).get("name", "")
        qt_text = quote.get("text", "")
        if qt_text:
            text += f"\n\n> **{qt_author}**: {qt_text}"

    # Append media descriptions
    media_all = tweet.get("media", {}).get("all", [])
    for m in media_all:
        alt = m.get("altText", "")
        mtype = m.get("type", "")
        if alt:
            text += f"\n\n[{mtype}: {alt}]"
        elif mtype == "video":
            text += f"\n\n[video: {m.get('url', '')}]"

    title = f"{author}(@{handle}): {text[:60]}..." if len(text) > 60 else f"{author}(@{handle}): {text}"

    logger.info(
        "web.twitter_fxtwitter_ok",
        url=url,
        author=f"{author}(@{handle})",
        chars=len(text),
        likes=tweet.get("likes"),
    )

    return {
        "title": title,
        "text": text,
        "url": url,
        "source_type": "community",
        "creator": f"{author}(@{handle})",
    }


# ---------------------------------------------------------------------------
# Markdown cleanup — aggressively strip platform boilerplate
# ---------------------------------------------------------------------------

# End-of-article markers: everything AFTER these is platform cruft.
# Order matters — first match wins, so put the most specific patterns first.
# All markers are stored lowercase — matching is case-insensitive.
_ARTICLE_END_MARKERS = [
    # Naver blog
    "이 블로그 인기글",
    "볼만한 airs 추천",
    "airs 추천 탐색",
    "이 블로그의 인기글",
    "관련글 더보기",
    "댓글을 더 보려면",
    "댓글 더보기",
    "포스트 공감",
    "블로그 정보",
    "이웃 블로거",
    "이 포스트가 좋았다면",
    "카테고리의 다른 글",
    "공감한 사람 보러가기",
    # Tistory
    "저작자표시",
    "카카오스토리",
    "페이스북 공유",
    # Brunch
    "작가의 이전글",
    "작가의 다음글",
    "매거진의 이전글",
    "이 글이 마음에 드셨다면",
    # General / English sites
    "naver corp.",
    "© naver corp.",
    "recommended for you",
    "you might also like",
    "related posts",
    "share this post",
    "## comments",
    "join the wired community",
    "don't just keep up",
    "back to top",
    "sign in or create account",
    "to revisit this article",
    # Claude / ChatGPT / AI shared conversation
    "start your own conversation",
    "start a new chat",
    "sign up for free",
    "chatgpt can make mistakes",
    "get smarter responses",
    "get responses tailored to you",
    "discover more",
    "ask follow-up",
    # Medium / Substack
    "if you enjoyed this",
    "subscribe to get",
    "thanks for reading",
    "share this post",
    "a]ready have an account? sign in",
    "start writing",
    # Velog
    "이 글이 좋으셨다면",
    "0개의 댓글",
    # General CTA
    "more from this author",
    "read more articles",
    "continue reading",
    "subscribe now",
    "join our newsletter",
    "follow us on",
]

# Lines containing these → remove the individual line
_BOILERPLATE_LINE_RE = re.compile(
    r"^.*("
    # Naver blog UI
    r"로그인이 필요합니다|본문 바로가기|MY메뉴|카테고리 이동|"
    r"이웃추가|이웃목록|신고하기|본문 폰트|댓글을 입력|"
    r"공감한 사람|블로그 앱|좋아요\s*\d|공유하기|"
    r"주제별\s*보기|최근\s*글|최신\s*댓글|"
    r"맨\s*위로|이전\s*포스트|다음\s*포스트|"
    # Naver reaction buttons
    r"공감|칭찬|감사|웃김|놀람|슬픔|"
    # Naver thumbnail grid artifacts
    r"pstatic\.net|postfiles|blogfiles|storep-phinf|"
    # Platform nav / auth / legal
    r"Skip to main content|Skip to content|Sign up|Log in|Subscribe|"
    r"Cookie|Privacy Policy|Terms of Service|Terms of Use|"
    r"All Rights Reserved|©\s*\d{4}|"
    # Medium / Substack / Ghost
    r"Member-only story|Open in app|Listen to this article|"
    r"Share this post|Give this article|Clap|Follow|"
    # Tistory / Daum
    r"티스토리툴바|다음\s*블로그|"
    # Velog
    r"시리즈\s*에\s*추가|"
    # Image-only lines (usually thumbnails/ads)
    r"!\[.*?\]\(https?://.*?(?:pstatic|daumcdn|tistorycdn|blogpay).*?\)"
    r").*$",
    re.MULTILINE | re.IGNORECASE,
)

# Nav-link lines (markdown links to platform menus)
_NAV_LINK_RE = re.compile(
    r"^\s*[-*]?\s*\[(?:내소식|이웃목록|통계|검색|최근 본 글|내 동영상|"
    r"내 클립|장바구니|마켓|블로그팀|이달의 블로그|공식 블로그|"
    r"본문 바로가기|글쓰기|클립만들기|구독하기|좋아요|"
    r"이전글|다음글|목록|홈|맨위로|뒤로가기|"
    r"로그인|회원가입|공유|신고|"
    r"Home|About|Contact|Menu|Search|Archive"
    r")[^\]]*\]\([^)]+\)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Repeated image thumbnail blocks (recommended post grids)
_THUMB_GRID_RE = re.compile(
    r"(?:!\[[^\]]*\]\([^)]*\)\s*\n?){3,}",
    re.MULTILINE,
)

# Bare URLs on their own line (usually tracking/CDN links)
_BARE_URL_LINE_RE = re.compile(
    r"^\s*https?://(?:pstatic|daumcdn|tistory|blogpay|img\.)?[^\s]+\s*$",
    re.MULTILINE,
)


def _clean_markdown(text: str) -> str:
    """Aggressively strip platform boilerplate from extracted markdown.

    Strategy:
    1. Truncate everything after end-of-article markers (recommended posts,
       reactions, profile cards, etc.)
    2. Remove individual boilerplate lines (navigation, UI elements)
    3. Strip thumbnail grids and bare CDN URLs
    """
    if not text:
        return ""

    # --- Phase 1: Truncate at end-of-article marker ---
    # Find the earliest marker and cut everything from there.
    # Case-insensitive: markers are lowercase, search in lowered text.
    text_lower = text.lower()
    earliest_pos = len(text)
    for marker in _ARTICLE_END_MARKERS:
        pos = text_lower.find(marker)
        if pos != -1 and pos < earliest_pos:
            earliest_pos = pos
    if earliest_pos < len(text):
        text = text[:earliest_pos]

    # --- Phase 2: Line-level cleanup ---
    text = _BOILERPLATE_LINE_RE.sub("", text)
    text = _NAV_LINK_RE.sub("", text)

    # --- Phase 3: Block-level cleanup ---
    # Remove thumbnail grids (3+ consecutive images)
    text = _THUMB_GRID_RE.sub("", text)
    # Remove bare CDN/tracking URL lines
    text = _BARE_URL_LINE_RE.sub("", text)

    # --- Phase 4: Final whitespace normalization ---
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# AI conversation cleanup (Claude, ChatGPT, Gemini, etc.)
# ---------------------------------------------------------------------------

# Platform disclaimer patterns — each captures participant name in group(1).
_CONVERSATION_DISCLAIMERS = [
    # Claude: "This is a copy of a chat between Claude and **Name**. Content may..."
    re.compile(
        r"^.*this is a (?:copy|snapshot) of a (?:chat|conversation) between claude and \*{0,2}([^.*\n]+?)\*{0,2}\..*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # ChatGPT: "This is a copy of a conversation between ChatGPT & **Name**."
    re.compile(
        r"^.*this is a (?:copy|snapshot) of a conversation between chatgpt (?:&|and) \*{0,2}([^.*\n]+?)\*{0,2}\..*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Generic: "Shared conversation with <AI name>"
    re.compile(
        r"^.*shared (?:chat|conversation) (?:with|between) .+? (?:&|and) \*{0,2}([^.*\n]+?)\*{0,2}\..*$",
        re.IGNORECASE | re.MULTILINE,
    ),
]

# Report / abuse button lines (all platforms)
_REPORT_LINE_RE = re.compile(
    r"^\s*(?:Report|Report conversation|Report content|Flag|신고)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# AI platform action indicator lines
_AI_ACTION_RE = re.compile(
    r"^\s*(?:"
    # Claude actions
    r"Searched the web|Viewed (?:a |)file|Created (?:a |)file|Read (?:a |)file"
    r"|Edited (?:a |)file|Ran code|Analyzed|Thinking"
    # ChatGPT actions
    r"|Searching the web|Browsing the web|Analyzing (?:image|data|file)"
    r"|Used (?:a |)tool|Generated (?:an? |)image|Calling (?:a |)function"
    # Perplexity source counts
    r"|\d+ sources?"
    r")"
    r".*$",
    re.MULTILINE | re.IGNORECASE,
)

# ChatGPT speaker labels — normalize to cleaner format
_CHATGPT_SPEAKER_RE = re.compile(
    r"^####\s+(You|ChatGPT)\s+said:\s*$",
    re.MULTILINE,
)

# Sidebar / nav / login CTA lines common to AI platforms
_AI_NAV_RE = re.compile(
    r"^.*("
    r"Skip to content|New chat|Search chats|Chat history|See plans and pricing"
    r"|Deep research|Sign up for free|Log in|Voice$"
    r"|New thread|Ctrl\s*[A-Z]|⌥⌃"
    r").*$",
    re.MULTILINE | re.IGNORECASE,
)


def _is_conversation_url(url: str) -> bool:
    """Check if URL is from a conversation-sharing AI platform."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _CONVERSATION_HOSTS:
        return False
    path = parsed.path.lower()
    # Must have a share/page path — not a homepage or docs page
    return any(seg in path for seg in ("/share/", "/page/", "/search/", "/c/"))


def _clean_conversation(text: str) -> tuple[str, str]:
    """Clean AI conversation boilerplate from any platform.

    Returns (cleaned_text, participant_name).
    Works for Claude, ChatGPT, Gemini, Perplexity, etc.
    """
    participant = ""

    # 1. Extract participant from disclaimer header and remove it
    for pattern in _CONVERSATION_DISCLAIMERS:
        m = pattern.search(text)
        if m:
            participant = m.group(1).strip().strip("*")
            text = text[:m.start()] + text[m.end():]
            break

    # 2. Remove report button lines
    text = _REPORT_LINE_RE.sub("", text)

    # 3. Remove AI action indicator lines
    text = _AI_ACTION_RE.sub("", text)

    # 4. Remove sidebar / nav / CTA lines
    text = _AI_NAV_RE.sub("", text)

    # 5. Normalize ChatGPT speaker labels: "#### You said:" → "**You:**"
    text = _CHATGPT_SPEAKER_RE.sub(r"**\1:**", text)

    # 6. Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text, participant


# ---------------------------------------------------------------------------
# Firecrawl Extractor — default for all non-YouTube URLs
# ---------------------------------------------------------------------------

async def _fetch_firecrawl(url: str) -> dict[str, str]:
    """Extract content via Firecrawl API.

    Requests markdown body plus metadata so we get author, publish date,
    description, and ogImage without a separate HTML parse.
    """
    from onlime.security.secrets import get_secret_or_env

    api_key = get_secret_or_env("firecrawl-api-key", "FIRECRAWL_API_KEY")
    host = urlparse(url).hostname or ""
    settings = get_settings()

    async with httpx.AsyncClient(timeout=settings.web.firecrawl_timeout) as client:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,  # strip nav, header, footer, sidebar
                "excludeTags": [
                    "nav", "footer", "header", "aside",
                    ".sidebar", ".comment", ".comments", ".reply",
                    ".recommend", ".related", ".popular", ".footer",
                    ".ad", ".ads", ".advertisement",
                    "#comment", "#comments", "#footer",
                    # Naver blog specific
                    ".blog-category", ".blog-popular", ".blog-subscribe",
                    ".post-btn", ".post-share", ".wrap_postcomment",
                    ".area_sympathy", ".btn_sympathize",
                    ".wrap_blog_popular", ".wrap_related",
                    ".area_related", ".area_comment",
                    ".se-module-oglink",
                    # Tistory
                    ".another_category", ".container_postbtn",
                    "#tistorySnsLayer",
                ],
                # Mobile UA helps bypass some login hints on Korean community sites
                "headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"
                    ),
                },
                "waitFor": settings.web.firecrawl_wait_ms,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    result_data = data.get("data", {})
    markdown = _clean_markdown(result_data.get("markdown", ""))
    metadata = result_data.get("metadata", {})

    # --- Title: og:title > <title> tag ---
    title = metadata.get("ogTitle") or metadata.get("title") or url
    # Strip common CMS site-name suffixes: "제목 | 사이트명"
    if " | " in title:
        candidate = title.rsplit(" | ", 1)[0].strip()
        if candidate:
            title = candidate
    elif " - " in title and len(title) > 60:
        candidate = title.rsplit(" - ", 1)[0].strip()
        if candidate:
            title = candidate

    # --- Author/creator ---
    creator = (
        metadata.get("author")
        or metadata.get("ogAuthor")
        or metadata.get("twitterCreator")
        or ""
    )

    # --- Description ---
    description = (
        metadata.get("description")
        or metadata.get("ogDescription")
        or ""
    )

    # --- Publish date ---
    published_at = (
        metadata.get("publishedTime")
        or metadata.get("datePublished")
        or metadata.get("articlePublishedTime")
        or metadata.get("article:published_time")
        or ""
    )

    # --- OG image ---
    og_image = metadata.get("ogImage") or metadata.get("og:image") or ""

    source_type = _source_type_for_host(host)

    logger.info(
        "web.firecrawl_ok",
        url=url,
        title=title[:60],
        chars=len(markdown),
        creator=creator,
        source_type=source_type,
    )

    result: dict[str, str] = {
        "title": title,
        "text": markdown,
        "url": url,
        "source_type": source_type,
    }
    if creator:
        result["creator"] = creator
    if description:
        result["description"] = description
    if published_at:
        result["published_at"] = published_at
    if og_image:
        result["og_image"] = og_image

    return result


# ---------------------------------------------------------------------------
# Trafilatura Extractor — fallback only
# ---------------------------------------------------------------------------

async def _fetch_trafilatura(url: str) -> dict[str, str]:
    """Extract content via trafilatura. Used only when Firecrawl fails."""
    import trafilatura

    settings = get_settings()
    host = urlparse(url).hostname or ""

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": settings.web.user_agent},
        follow_redirects=True,
        max_redirects=5,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw_html = resp.text
        if len(raw_html) > settings.web.max_content_length:
            raw_html = raw_html[: settings.web.max_content_length]

    # Main text extraction
    text = trafilatura.extract(
        raw_html,
        include_comments=False,
        include_tables=True,
        output_format="txt",
    ) or ""

    # Structured metadata (title, author, date) via trafilatura
    meta = None
    if hasattr(trafilatura, "extract_metadata"):
        try:
            meta = trafilatura.extract_metadata(raw_html)
        except Exception:
            pass

    title = (getattr(meta, "title", "") or "") if meta else ""
    creator = (getattr(meta, "author", "") or "") if meta else ""
    published_at = (getattr(meta, "date", "") or "") if meta else ""

    # Fallback title from <title> tag
    if not title:
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", raw_html, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            if " | " in title:
                candidate = title.rsplit(" | ", 1)[0].strip()
                if candidate:
                    title = candidate

    source_type = _source_type_for_host(host)

    logger.info(
        "web.trafilatura_ok",
        url=url,
        title=title[:60],
        chars=len(text),
        source_type=source_type,
    )

    result: dict[str, str] = {
        "title": title or url,
        "text": text,
        "url": url,
        "source_type": source_type,
    }
    if creator:
        result["creator"] = creator
    if published_at:
        result["published_at"] = published_at

    return result
