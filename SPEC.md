# Onlime — 개인 AI 지식 베이스(Second Brain) 개발 명세서

> **Version:** 2.0 (2026-04-05)
> **Status:** Development-Ready
> **Author:** 10 Research Agents + 5 Review Agents → Final Synthesis

---

## 0. Day-1 검증 테스트 (개발 착수 전 필수)

개발에 들어가기 전, 아래 3가지 테스트를 **반드시** 통과해야 합니다.

### T1. 카카오톡 DB 접근 가능성 (CRITICAL) — **FAIL (암호화)**
```
DB 위치: ~/Library/Containers/com.kakao.KakaoTalkMac/Data/Library/
         Application Support/com.kakao.KakaoTalkMac/e4a7663e...
파일 크기: 374MB + WAL 모드
헤더: 0x0428816c... (SQLite magic 아님 → 암호화 확인)
```
**결정**: 폴백 B 채택 — **카카오톡 macOS "대화 내보내기" .txt 파일 파싱**
- 사용자가 수동으로 대화방별 .txt 내보내기 → 지정 폴더에 저장
- watchdog가 .txt 파일 감지 → 파싱 → 요약 → Vault 저장
- 향후 AppleScript UI 자동화로 내보내기 자동화 가능

### T2. faster-whisper 한국어 STT 품질
```python
from faster_whisper import WhisperModel
model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
segments, info = model.transcribe("test_korean.m4a", language="ko")
for seg in segments:
    print(f"[{seg.start:.1f}s-{seg.end:.1f}s] {seg.text}")
```
- 1분 오디오 → 처리시간 3분 이내, WER 10% 이하 확인

### T3. 메모리 동시 실행 가능성 (8GB Mac 기준)
```bash
# faster-whisper INT8 + BGE-M3 동시 로딩 메모리 확인
python -c "
from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer
import psutil
w = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
e = SentenceTransformer('BAAI/bge-m3')
print(f'RSS: {psutil.Process().memory_info().rss / 1024**3:.1f}GB')
"
```
- **PASS**: RSS < 6GB → 동시 실행 가능
- **FAIL**: RSS >= 6GB → Whisper/BGE-M3 순차 실행 (mutex 적용)

---

## 1. 시스템 아키텍처 개요

```
┌─────────────────────────────────────────────────────────┐
│                    INPUT SOURCES                         │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│ KakaoTalk│ Telegram │ Samsung  │ Web/YT   │ Google Cal  │
│ (SQLite) │ (Bot API)│(Syncthing│(trafilat-│ (MCP/API)   │
│          │          │  -Fork)  │ ura)     │             │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴──────┬──────┘
     │          │          │          │            │
     ▼          ▼          ▼          ▼            ▼
┌─────────────────────────────────────────────────────────┐
│              CONNECTOR LAYER (BaseConnector)             │
│  각 소스별 커넥터가 RawEvent를 생성                        │
└──────────────────────┬──────────────────────────────────┘
                       │ asyncio.Queue
                       ▼
┌─────────────────────────────────────────────────────────┐
│              PROCESSING PIPELINE                         │
│  RawEvent → [STT] → [Summarize] → [Categorize]          │
│          → [Embed] → ProcessedEvent                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              OUTPUT LAYER                                │
│  ProcessedEvent → VaultEntry (.md + frontmatter)         │
│                → LanceDB (vector index)                  │
│                → SQLite (metadata + state)                │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              STORAGE                                     │
│  Obsidian Vault (Google Drive 동기화)                     │
│  ├── 00-inbox/        (미분류)                            │
│  ├── 10-daily/        (일일 노트)                         │
│  ├── 20-meetings/     (미팅 노트)                         │
│  ├── 30-chats/        (대화 요약)                         │
│  ├── 40-resources/    (웹/유튜브)                         │
│  ├── 50-ideas/        (아이디어/메모)                      │
│  ├── 60-projects/     (프로젝트별)                         │
│  │   ├── borromeo/                                       │
│  │   ├── chamchi/                                        │
│  │   ├── hackathon/                                      │
│  │   └── next_nobel/                                     │
│  ├── 70-people/       (인물 프로필)                        │
│  └── 80-archive/      (아카이브)                          │
└─────────────────────────────────────────────────────────┘
```

### 기술 스택

| 레이어 | 기술 | 버전 | 비고 |
|--------|------|------|------|
| Runtime | Python | 3.12+ | asyncio 기반 |
| API Server | FastAPI + uvicorn | 0.115+ | lifespan context manager |
| Scheduler | APScheduler | **3.10.x** | 4.x는 불안정, `>=3.10,<4.0` 핀 |
| DB (메타) | SQLite WAL + aiosqlite | — | `onlime.db` |
| DB (벡터) | **LanceDB** | 0.6+ | 서버리스, 파일기반 |
| Embedding | BGE-M3 | — | 1024dim, dense+sparse |
| STT | faster-whisper | — | large-v3-turbo, INT8, CPU only |
| LLM (주) | Gemini 2.0 Flash | — | 무료 티어 1.5M tok/day |
| LLM (보조) | Claude Haiku 4.5 | — | Gemini 장애시 폴백 |
| Config | pydantic-settings | — | TOML 포맷 |
| Logging | structlog | — | JSON 구조화 로깅 |
| Process Mgmt | launchd | — | macOS 데몬 |

---

## 2. 프로젝트 구조

```
onlime/
├── pyproject.toml
├── onlime.toml                  # 설정 파일 (비밀 정보 제외)
├── src/
│   └── onlime/
│       ├── __init__.py
│       ├── __main__.py          # CLI 진입점
│       ├── config.py            # pydantic-settings 설정
│       ├── models.py            # 공통 데이터 모델
│       ├── engine.py            # 메인 이벤트 루프
│       │
│       ├── connectors/          # 데이터 수집 커넥터
│       │   ├── __init__.py      # registry + BaseConnector ABC
│       │   ├── kakao.py         # 카카오톡 SQLite 읽기
│       │   ├── telegram.py      # 텔레그램 봇 (수집 + 비서)
│       │   ├── gdrive.py        # Google Drive watchdog 감시
│       │   ├── web.py           # 웹/유튜브 추출
│       │   └── gcal.py          # 구글 캘린더
│       │
│       ├── processors/          # 데이터 가공 파이프라인
│       │   ├── __init__.py
│       │   ├── stt.py           # faster-whisper STT
│       │   ├── summarizer.py    # LLM 요약
│       │   ├── categorizer.py   # 자동 분류
│       │   └── embedder.py      # BGE-M3 임베딩
│       │
│       ├── outputs/             # Vault 출력
│       │   ├── __init__.py
│       │   ├── vault.py         # Obsidian .md 파일 쓰기
│       │   └── templates.py     # Jinja2 템플릿 (autoescape 활성화)
│       │
│       ├── search/              # RAG 검색
│       │   ├── __init__.py
│       │   └── rag.py           # LanceDB hybrid search
│       │
│       ├── state/               # 상태 관리
│       │   ├── __init__.py
│       │   └── store.py         # SQLite 상태 저장소
│       │
│       └── security/            # 보안
│           ├── __init__.py
│           └── secrets.py       # macOS Keychain 통합
│
├── templates/                   # Jinja2 .md 템플릿
│   ├── daily_note.md.j2
│   ├── chat_summary.md.j2
│   ├── meeting_note.md.j2
│   ├── resource.md.j2
│   └── idea.md.j2
│
├── tests/
│   ├── test_connectors/
│   ├── test_processors/
│   └── test_outputs/
│
└── scripts/
    ├── install_launchd.py       # launchd plist 설치
    └── verify_day1.py           # Day-1 검증 스크립트
```

---

## 3. 데이터 모델

### 3.1 핵심 이벤트 타입

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

class SourceType(str, Enum):
    KAKAO = "kakao"
    TELEGRAM = "telegram"
    WEB = "web"
    YOUTUBE = "youtube"
    VOICE = "voice"
    GCAL = "gcal"
    MANUAL = "manual"

class ContentType(str, Enum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    LINK = "link"
    FILE = "file"

@dataclass
class RawEvent:
    """커넥터가 생성하는 원시 이벤트"""
    id: str                          # UUID
    source: SourceType
    content_type: ContentType
    raw_content: str | bytes         # 텍스트 또는 파일 경로
    timestamp: datetime
    metadata: dict = field(default_factory=dict)
    # metadata 예: {"chat_room": "팀챗", "sender": "홍길동", "hashtag": "#AIP"}

@dataclass
class ProcessedEvent:
    """파이프라인 처리 완료된 이벤트"""
    raw_event_id: str
    title: str
    summary: str
    full_text: str
    category: str                    # 폴더 매핑용
    tags: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    embedding: Optional[list[float]] = None
    vault_path: Optional[str] = None  # 최종 저장 경로
```

### 3.2 SQLite 스키마 (`~/.onlime/onlime.db`)

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;

-- 이벤트 상태 추적
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,                    -- source_type + "_" + source_id
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    connector_name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',          -- pending/processing/done/failed
    payload TEXT NOT NULL,                  -- JSON (RawEvent 직렬화)
    obsidian_path TEXT,
    created_at TEXT NOT NULL,               -- ISO 8601
    processed_at TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    UNIQUE(source_type, source_id)
);

-- 커넥터별 동기화 커서
CREATE TABLE IF NOT EXISTS connector_state (
    connector_name TEXT PRIMARY KEY,
    cursor_value TEXT,                      -- last_row_id, timestamp 등
    last_sync_at TEXT,
    last_success_at TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    metadata TEXT                           -- JSON
);

-- 사람 매칭
CREATE TABLE IF NOT EXISTS people (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wikilink TEXT NOT NULL,
    aliases TEXT,                           -- JSON array
    kakao_name TEXT,
    telegram_username TEXT,
    updated_at TEXT
);

-- 프로젝트 매칭
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wikilink TEXT NOT NULL,
    hashtags TEXT,                          -- JSON array (#AIP, #boromeo)
    active INTEGER DEFAULT 1,
    updated_at TEXT
);

-- 비동기 태스크 큐 (GDrive watcher → STT 등)
CREATE TABLE IF NOT EXISTS task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,                -- stt/summarize/embed
    input_path TEXT,
    status TEXT DEFAULT 'pending',          -- pending/processing/done/failed
    priority INTEGER DEFAULT 5,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT,                            -- JSON
    error TEXT,
    retry_count INTEGER DEFAULT 0
);

-- RAG 청크 메타데이터 (벡터는 LanceDB에 별도)
CREATE TABLE IF NOT EXISTS rag_chunks (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 헬스체크 기록
CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_name TEXT NOT NULL,
    status TEXT NOT NULL,                   -- ok/warning/error
    message TEXT,
    checked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_type, created_at);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status, priority);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source_path);
```

### 3.3 Obsidian Frontmatter 스키마

```yaml
# 공통 필드 (모든 노트)
---
id: "evt_20260405_abc123"
title: "제목"
created: 2026-04-05T14:30:00+09:00
source: kakao | telegram | web | youtube | voice | gcal | manual
tags: [tag1, tag2]
people: ["[[홍길동]]", "[[김철수]]"]
status: raw | processed | reviewed
---

# 대화 요약 (30-chats/)
---
chat_room: "팀 프로젝트"
participants: ["홍길동", "김철수"]
message_count: 42
period: "2026-04-05 09:00 ~ 18:00"
---

# 미팅 노트 (20-meetings/)
---
meeting_type: online | offline
attendees: ["홍길동"]
duration_min: 60
recording_path: "recordings/2026-04-05_meeting.m4a"
---

# 리소스 (40-resources/)
---
url: "https://example.com/article"
content_type: article | video | pdf
word_count: 1500
---
```

---

## 4. 커넥터 상세 설계

### 4.1 BaseConnector (ABC)

```python
from abc import ABC, abstractmethod
import asyncio

class BaseConnector(ABC):
    """모든 커넥터의 기본 클래스"""

    def __init__(self, config: dict, queue: asyncio.Queue):
        self.config = config
        self.queue = queue  # ProcessedEvent를 넣는 큐
        self.name = self.__class__.__name__

    @abstractmethod
    async def start(self) -> None:
        """커넥터 시작 (스케줄 등록 또는 감시 시작)"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """커넥터 정지"""
        ...

    @abstractmethod
    async def collect(self) -> list[RawEvent]:
        """데이터 수집 1회 실행"""
        ...

    async def emit(self, event: RawEvent) -> None:
        await self.queue.put(event)

# 레지스트리 패턴
_registry: dict[str, type[BaseConnector]] = {}

def register(name: str):
    def decorator(cls):
        _registry[name] = cls
        return cls
    return decorator
```

### 4.2 카카오톡 커넥터 (`kakao.py`)

**방식 결정 로직** (Day-1 테스트 결과에 따라):
- **Primary**: macOS SQLite DB 직접 읽기
  - 경로: `~/Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Application Support/KakaoTalk/KakaoTalk.db`
  - WAL 모드로 열기 (`PRAGMA journal_mode=WAL`)
  - 주요 테이블: `ZCHATLOGS` (메시지), `ZCHATROOM` (채팅방)
  - 증분 수집: 마지막 처리 `ZLOGID` 기준
- **Fallback A**: `kmsg` CLI 도구 활용
- **Fallback B**: .txt 내보내기 파일 파싱

**스케줄**: 6시간마다 (`APScheduler interval trigger`)

**처리 흐름**:
1. DB에서 마지막 수집 이후 새 메시지 쿼리
2. 채팅방별로 그룹핑
3. 채팅방별 RawEvent 생성 (content_type=TEXT)
4. → 파이프라인: 원문 전체 저장 + LLM 요약 → 30-chats/ 에 저장
   - 모든 메시지 원문, 발신자 실명, 타임스탬프를 그대로 보관
   - 요약은 원문 위에 추가되는 보조 정보

### 4.3 텔레그램 봇 커넥터 (`telegram.py`)

**라이브러리**: `python-telegram-bot` v21+ (asyncio native)

**2가지 모드**:

#### Mode 1: Data Catcher (수집기)
```
사용자 → 텔레그램 봇: "https://example.com/article #AIP 이거 읽어봐"
봇 → 추출 + 요약 → 60-projects/borromeo/article_title.md
봇 → 사용자: "✓ borromeo 폴더에 저장했습니다: [제목]"
```

#### Mode 2: AI Assistant (비서)
```
사용자 → 텔레그램 봇: "지난주 AIP 관련 미팅 요약해줘"
봇 → RAG 검색 (LanceDB) → LLM 답변 생성
봇 → 사용자: "지난주 AIP 미팅은 2건..."
```

**해시태그 라우팅**:
```python
ROUTE_MAP = {
    "#aip": "60-projects/borromeo",
    "#borromeo": "60-projects/borromeo",
    "#boromeo": "60-projects/borromeo",   # 오타 대응
    "#chamchi": "60-projects/chamchi",
    "#thehackathon": "60-projects/hackathon",
    "#nextnobel": "60-projects/next_nobel",
    "#philosophy": "60-projects/philosophy",
}
DEFAULT_ROUTE = "00-inbox"
```

**보안**:
```python
ALLOWED_USER_IDS: set[int]  # config에서 로드
# owner만 쓰기, 허용 유저는 읽기만
```

### 4.4 Google Drive 감시 커넥터 (`gdrive.py`)

**라이브러리**: `watchdog` (FSEventsObserver, macOS 최적)

**감시 대상**: Google Drive Mirror Sync 폴더 내 특정 하위 폴더
- `phone-photos/` → 이미지 파일 감지
- `phone-recordings/` → 음성 파일 감지 → STT 파이프라인

**동작**:
```python
class StableFileHandler(FileSystemEventHandler):
    """파일 쓰기 완료 확인 후 처리 (2초간 크기 변동 없으면 안정)"""

    def on_created(self, event):
        # 2초 대기 → 크기 변동 확인 → content-hash 중복 체크 → RawEvent 생성
        ...
```

### 4.5 웹/유튜브 커넥터 (`web.py`)

**텔레그램 봇을 통해 트리거됨** (독립 스케줄 없음)

**웹 아티클**:
- `trafilatura` (primary) → `readability-lxml` (fallback)
- 메타데이터 추출: 제목, 저자, 발행일, 본문

**유튜브**:
- `youtube-transcript-api` (자막 있을 때) → `yt-dlp` (오디오 추출) → faster-whisper (STT)
- 영상 메타데이터: 제목, 채널, 길이, 조회수

**PDF**:
- `pdfminer.six` → 텍스트 추출

### 4.6 구글 캘린더 커넥터 (`gcal.py`)

**방식**: Google Calendar API (OAuth2) 또는 Claude MCP

**스케줄**: 1시간마다 오늘+내일 일정 동기화
- 10-daily/ 의 일일 노트에 일정 섹션 업데이트
- 미팅 종료 후 → 20-meetings/ 에 빈 미팅 노트 템플릿 생성

---

## 5. 프로세싱 파이프라인

### 5.1 STT (`stt.py`)

```python
from faster_whisper import WhisperModel

class STTProcessor:
    def __init__(self):
        self.model = WhisperModel(
            "large-v3-turbo",
            device="cpu",          # MPS 사용 금지 (수치 오류)
            compute_type="int8"    # 메모리 절약
        )

    async def transcribe(self, audio_path: str) -> str:
        segments, info = self.model.transcribe(
            audio_path,
            language="ko",
            vad_filter=True,       # 무음 구간 필터링
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        return "\n".join(seg.text for seg in segments)
```

**Speaker Diarization (Phase 3 — MVP 제외)**:
- `pyannote.audio` 3.1 사용시 반드시 `device="cpu"` (MPS 수치 오류 확인됨)
- HuggingFace 토큰 필요 (라이센스 동의)

### 5.2 LLM 요약 (`summarizer.py`)

```python
class LLMClient:
    """Multi-provider LLM 클라이언트"""

    def __init__(self, config):
        self.primary = GeminiProvider(config.gemini_api_key)    # Gemini 2.0 Flash
        self.fallback = ClaudeProvider(config.claude_api_key)   # Claude Haiku

    async def summarize(self, text: str, prompt_template: str) -> str:
        try:
            return await self.primary.generate(prompt_template.format(text=text))
        except Exception:
            return await self.fallback.generate(prompt_template.format(text=text))
```

**프롬프트 템플릿 (한국어)**:
- 대화 요약: 핵심 논의사항, 결정사항, 액션아이템 추출
- 웹/유튜브: 3줄 요약 + 핵심 인사이트 + 관련 키워드
- 음성 메모: 주제별 구조화 정리

**비용 제어**:
- Gemini 무료 티어: 1,500,000 토큰/일, 15 RPM, 1M 컨텍스트
- 일일 사용량 추적 → 한도 80% 도달시 경고
- 캐시: 동일 content-hash 재처리 방지

### 5.3 자동 분류 (`categorizer.py`)

```python
def categorize(event: RawEvent) -> str:
    """해시태그 우선, 없으면 LLM 분류"""

    # 1. 해시태그 기반 (확정적)
    hashtag = event.metadata.get("hashtag")
    if hashtag and hashtag.lower() in ROUTE_MAP:
        return ROUTE_MAP[hashtag.lower()]

    # 2. 소스 기반 (규칙)
    if event.source == SourceType.KAKAO:
        return "30-chats"
    if event.source == SourceType.GCAL:
        return "20-meetings"
    if event.source in (SourceType.WEB, SourceType.YOUTUBE):
        return "40-resources"
    if event.source == SourceType.VOICE:
        return "50-ideas"

    # 3. 폴백
    return "00-inbox"
```

### 5.4 임베딩 (`embedder.py`)

```python
from sentence_transformers import SentenceTransformer

class Embedder:
    def __init__(self):
        self.model = SentenceTransformer("BAAI/bge-m3")

    def embed(self, text: str) -> list[float]:
        # BGE-M3: 한국어+영어 다국어 지원, 1024 dim
        return self.model.encode(text, normalize_embeddings=True).tolist()
```

---

## 6. RAG 검색 (`search/rag.py`)

```python
import lancedb

class RAGSearch:
    def __init__(self, db_path: str):
        self.db = lancedb.connect(db_path)
        self.table = self.db.open_table("vault_index")
        self.embedder = Embedder()

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        query_vec = self.embedder.embed(query)
        results = (
            self.table
            .search(query_vec)
            .limit(top_k)
            .to_pandas()
        )
        return results.to_dict(orient="records")

    async def upsert(self, doc_id: str, text: str, metadata: dict):
        vec = self.embedder.embed(text)
        self.table.add([{"id": doc_id, "text": text, "vector": vec, **metadata}])
```

**인덱싱 전략**:
- Vault에 새 .md 파일 생성/수정 시 자동 인덱싱
- 청크 단위: 문서 전체 (대부분 요약본이라 짧음)
- 메타데이터 필터: source, category, date range

---

## 7. Vault 출력 (`outputs/vault.py`)

### 7.1 Atomic Write

```python
import os
import tempfile

def atomic_write(path: str, content: str) -> None:
    """원자적 파일 쓰기 — 중간에 실패해도 기존 파일 손상 없음"""
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)  # 원자적 교체
    except Exception:
        os.unlink(tmp_path)
        raise
```

### 7.2 Jinja2 템플릿

```python
from jinja2 import Environment, FileSystemLoader, select_autoescape

template_env = Environment(
    loader=FileSystemLoader("templates/"),
    autoescape=select_autoescape(["html", "xml"]),  # 보안: autoescape 활성화
    trim_blocks=True,
    lstrip_blocks=True,
)
```

### 7.3 파일명 규칙

```
{YYYY-MM-DD}_{source}_{slugified_title}.md

예시:
2026-04-05_kakao_팀프로젝트_대화요약.md
2026-04-05_web_transformer_논문_리뷰.md
2026-04-05_voice_아이디어_메모.md
```

---

## 8. 스케줄링 & 실행

### 8.1 APScheduler 설정

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

# 커넥터별 스케줄
scheduler.add_job(kakao_connector.collect, IntervalTrigger(hours=6), id="kakao")
scheduler.add_job(gcal_connector.collect, IntervalTrigger(hours=1), id="gcal")
scheduler.add_job(daily_note_generator, CronTrigger(hour=7, minute=0), id="daily")
scheduler.add_job(vault_health_check, CronTrigger(hour=3, minute=0), id="health")
```

### 8.2 launchd plist

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.onlime.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>onlime</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/cdiseetheeye/Desktop/Onlime</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/cdiseetheeye/.onlime/logs/onlime.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/cdiseetheeye/.onlime/logs/onlime.err</string>
</dict>
</plist>
```

---

## 9. 보안 설계

### 9.1 시크릿 관리 — macOS Keychain

```python
import subprocess

def get_secret(service: str, account: str) -> str:
    """macOS Keychain에서 시크릿 로드. .env 사용 금지."""
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Keychain lookup failed: {service}/{account}")
    return result.stdout.strip()

def set_secret(service: str, account: str, password: str) -> None:
    """시크릿을 Keychain에 저장"""
    subprocess.run(
        ["/usr/bin/security", "add-generic-password", "-s", service, "-a", account, "-w", password, "-U"],
        check=True
    )

# 사용 예:
# set_secret("onlime", "gemini-api-key", "AIza...")
# set_secret("onlime", "telegram-bot-token", "123456:ABC...")
# get_secret("onlime", "gemini-api-key")
```

### 9.2 보안 체크리스트

- [ ] `.env` 파일 사용하지 않음 — 모든 시크릿은 Keychain
- [ ] FastAPI 바인딩: `127.0.0.1` only (0.0.0.0 금지)
- [ ] CORS: 명시적 origin만 허용 (와일드카드 금지)
- [ ] 텔레그램 봇: allowlist 기반 인증 + 무단 접근 로깅
- [ ] subprocess 호출: 절대 경로 사용 (`/usr/bin/osascript`)
- [ ] Jinja2: autoescape 활성화
- [ ] 모든 메시지 원문 + 실명 + 연락처 전체 축적 (삭제 없음)
- [ ] 사진/미디어 파일 원본 보관

---

## 10. 설정 파일 (`onlime.toml`)

```toml
[general]
vault_path = "~/Documents/Obsidian/Onlime"
data_dir = "~/.onlime"
log_level = "INFO"

[connectors.kakao]
enabled = true
schedule_hours = 6
# db_path는 자동 감지

[connectors.telegram]
enabled = true
# bot_token → Keychain: service="onlime", account="telegram-bot-token"
allowed_user_ids = [123456789]

[connectors.gdrive]
enabled = true
watch_paths = [
    "~/Google Drive/My Drive/phone-recordings",
    "~/Google Drive/My Drive/phone-photos",
]

[connectors.gcal]
enabled = true
schedule_hours = 1

[connectors.web]
enabled = true
# 텔레그램 봇 통해서만 트리거

[llm]
# api_key → Keychain: service="onlime", account="gemini-api-key"
primary_model = "gemini-2.0-flash"
daily_token_limit = 1_200_000    # 80% of 1.5M (안전 마진)

[search]
db_path = "~/.onlime/lancedb"
embedding_model = "BAAI/bge-m3"

[routing]
"#aip" = "60-projects/borromeo"
"#borromeo" = "60-projects/borromeo"
"#boromeo" = "60-projects/borromeo"
"#chamchi" = "60-projects/chamchi"
"#thehackathon" = "60-projects/hackathon"
"#nextnobel" = "60-projects/next_nobel"
"#philosophy" = "60-projects/philosophy"
```

---

## 11. 의존성 (`pyproject.toml`)

```toml
[project]
name = "onlime"
version = "2.0.0"
requires-python = ">=3.12"
dependencies = [
    # Core
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "apscheduler>=3.10,<4.0",       # 4.x 불안정 — 반드시 3.x
    "aiosqlite>=0.20",
    "structlog>=24.0",
    "tomli>=2.0; python_version<'3.11'",

    # Connectors
    "python-telegram-bot>=21.0",
    "watchdog>=4.0",
    "trafilatura>=1.8",
    "readability-lxml>=0.8",
    "youtube-transcript-api>=0.6",
    "yt-dlp>=2024.0",
    "pdfminer.six>=20231228",
    "google-api-python-client>=2.0",
    "google-auth-oauthlib>=1.0",

    # ML/AI
    "faster-whisper>=1.0",
    "sentence-transformers>=3.0",
    "lancedb>=0.6",
    "google-generativeai>=0.8",
    "anthropic>=0.30",

    # Utils
    "httpx>=0.27",
    "python-slugify>=8.0",
    "jinja2>=3.1",
]

[project.scripts]
onlime = "onlime.__main__:main"
```

---

## 12. 구현 페이즈

### Phase 1: 기반 (Day 1-2)
- [ ] Day-1 검증 테스트 실행 (T1, T2, T3)
- [ ] 프로젝트 구조 생성
- [ ] `config.py` — pydantic-settings + TOML 로더
- [ ] `models.py` — RawEvent, ProcessedEvent 데이터 클래스
- [ ] `state/store.py` — SQLite WAL 상태 저장소
- [ ] `security/secrets.py` — macOS Keychain 래퍼
- [ ] `engine.py` — 메인 이벤트 루프 스켈레톤
- [ ] `connectors/__init__.py` — BaseConnector ABC + registry

### Phase 2: 텔레그램 봇 (Day 3-4)
- [ ] `connectors/telegram.py` — 봇 기본 구조
- [ ] 해시태그 라우팅 구현
- [ ] Data Catcher 모드 (텍스트/링크/음성 수신 → RawEvent)
- [ ] `outputs/vault.py` — atomic_write + 템플릿 렌더링
- [ ] `outputs/templates.py` — Jinja2 환경 설정
- [ ] 텔레그램 → Vault 엔드투엔드 동작 확인

### Phase 3: 웹/유튜브 추출 (Day 5-6)
- [ ] `connectors/web.py` — trafilatura + youtube-transcript-api
- [ ] `processors/summarizer.py` — Gemini Flash 연동
- [ ] `processors/categorizer.py` — 해시태그 + 규칙 기반 분류
- [ ] PDF 추출 기능
- [ ] 텔레그램 봇에 링크 처리 핸들러 연결

### Phase 4: 음성 처리 (Day 7-8)
- [ ] `processors/stt.py` — faster-whisper 한국어 STT
- [ ] `connectors/gdrive.py` — watchdog 파일 감시
- [ ] 음성 → 텍스트 → 요약 → Vault 파이프라인
- [ ] 텔레그램 음성 메시지 처리 연동

### Phase 5: 카카오톡 (Day 9-10)
- [ ] `connectors/kakao.py` — Day-1 결과에 따른 방식 구현
- [ ] 증분 수집 (마지막 ZLOGID 기반)
- [ ] 채팅방별 요약 생성
- [ ] 실명 + 연락처 원문 보존 확인

### Phase 6: RAG + AI 비서 (Day 11-12)
- [ ] `processors/embedder.py` — BGE-M3 임베딩
- [ ] `search/rag.py` — LanceDB 인덱싱 + 검색
- [ ] 텔레그램 봇 AI Assistant 모드
- [ ] Vault 기존 문서 일괄 인덱싱 스크립트

### Phase 7: 스케줄링 + 배포 (Day 13-14)
- [ ] `engine.py` — APScheduler 통합
- [ ] `__main__.py` — CLI 진입점 (start/stop/status)
- [ ] launchd plist 생성 + 설치 스크립트
- [ ] 구글 캘린더 연동
- [ ] 일일 노트 자동 생성 (CronTrigger 07:00)
- [ ] 로깅/모니터링 최종 점검
- [ ] 전체 E2E 테스트

---

## 13. 리스크 대응 매트릭스

| 리스크 | 심각도 | 확률 | 대응 |
|--------|--------|------|------|
| 카카오톡 DB 암호화 | CRITICAL | 60-70% | Day-1 T1 테스트, 폴백: kmsg/txt 파싱 |
| pyannote MPS 수치 오류 | CRITICAL | 100% | CPU 강제, Phase 3 이후 도입 |
| Whisper+BGE-M3 메모리 초과 | HIGH | 40% | T3 테스트, 순차 실행 mutex |
| Gemini 무료 티어 SLA 없음 | MAJOR | 30% | Claude Haiku 자동 폴백 |
| APScheduler 4.x 불안정 | MAJOR | — | 3.10.x 핀, `<4.0` 제한 |
| 카카오톡 TOS 위반 | MEDIUM | — | 개인 용도 로컬 보관, 외부 공유 금지 |
| Google Drive Mirror Sync 비활성화 | LOW | — | 설치 가이드에 Mirror Sync 설정 포함 |

---

## 14. Samsung S26 Ultra 동기화

### MVP: Syncthing-Fork (P2P 동기화)

**선택 이유**: 클라우드 불필요, LAN에서 직접 P2P, 배터리 효율적

**설정**:
1. 폰: Syncthing-Fork 설치 → `DCIM/Camera`, `Recordings` 폴더 공유
2. Mac: Syncthing 설치 → `~/Google Drive/My Drive/phone-photos`, `phone-recordings` 로 수신
3. → Google Drive watchdog가 자동 감지 → STT/처리 파이프라인

**폴백 (Syncthing 실패시)**: 수동 USB 연결 또는 Google Photos 자동 백업

---

## 15. 보안 감사 결과 (R4 Security Review)

R4 보안 리뷰어가 기존 코드베이스를 전수 감사한 결과입니다. 신규 개발 시 반드시 반영해야 합니다.

### 즉시 조치 (CRITICAL)

| ID | 이슈 | 위치 | 조치 |
|----|------|------|------|
| C1 | `.env`에 실제 비밀번호 하드코딩 | `.env` | **모든 시크릿 macOS Keychain으로 이관**, `.env` 삭제 |
| C2 | philomoim 사이트에 실제 전화번호 노출 | `philomoim/index.html` | placeholder를 `010-0000-0000`으로 교체 |
| C3 | philomoim `/api/submit` rate limit/CSRF/검증 없음 | `philomoim/api/submit.js` | rate limit + input validation + CAPTCHA 추가 |

### 1주 내 조치 (HIGH)

| ID | 이슈 | 조치 |
|----|------|------|
| H1 | 텔레그램 봇 단일 ownerId 인증 | allowlist + 무단 접근 로깅 + 읽기/쓰기 권한 분리 |
| H2 | 봇 토큰 JSON 평문 저장 | 환경변수 또는 Keychain으로 이관 |
| H3 | FastAPI `0.0.0.0` 바인딩 문서화 | `127.0.0.1` 강제, 원격 접근은 SSH 터널 |
| H4 | CORS 와일드카드 허용 | 와일드카드 거부, 명시적 origin만 허용 |
| H5 | `notify.ts` AppleScript 커맨드 인젝션 | `execFile` + 인자 분리 또는 `node-notifier` |
| H6 | Threads 스크래퍼 하드코딩 크레덴셜 | 스크립트 제거 또는 공식 API 전환 |

### 신규 개발 적용 원칙

1. **시크릿**: `.env` 금지 → macOS Keychain (`security/secrets.py`)
2. **서버 바인딩**: `127.0.0.1` only
3. **입력 검증**: 모든 외부 입력에 길이 제한 + 패턴 검증
4. **데이터 완전 보존**: 모든 텍스트 원문, 실명, 사진을 삭제 없이 축적
5. **subprocess**: 절대 경로 (`/usr/bin/osascript`, `/usr/bin/security`)
6. **Jinja2**: `autoescape=select_autoescape(["html", "xml"])` 필수
7. **로깅**: 보안 이벤트 (인증 실패, 무단 접근) 별도 분류 기록

---

## 16. 기술 결정 트레이드오프

| 결정 | 선택한 이유 | 단점/리스크 |
|------|------------|------------|
| KakaoTalk SQLite 직접 읽기 vs Termux push | DB 히스토리 전체 접근, 안정적 | DB 암호화 가능성 60-70%, 업데이트시 스키마 변경 위험 |
| LanceDB vs ChromaDB | 서버리스/파일기반, `.md` SoT 원칙 부합 | 생태계가 Chroma보다 작음 |
| Gemini 무료 티어 vs Claude primary | 비용 $0, 1.5M tok/day | 15 RPM rate limit, SLA 없음 |
| SQLite WAL vs JSON state | ACID 트랜잭션, race condition 해결 | aiosqlite 의존성 추가 |
| faster-whisper CPU vs GPU | macOS 범용 호환 | 1분 오디오 ~30-60초 처리 |
| BGE-M3 로컬 vs OpenAI 임베딩 API | 비용 $0, 오프라인, 데이터 외부 전송 없음 | 초기 모델 ~2GB, CPU 임베딩 느림 |
| APScheduler 3.x vs 4.x | 안정적, 프로덕션 검증됨 | 4.x의 새 기능 사용 불가 |
| Syncthing-Fork vs ADB+KDE Connect 3중 스택 | MVP 단순성, P2P 충분 | ADB/KDE Connect 고급 기능 미사용 |
| python-telegram-bot vs Pyrogram | 공식 Bot API, async native, 유지보수 활발 | 채팅 히스토리 동기화 불가 (봇 한계) |

---

## 17. 기존 코드베이스 참조

신규 개발 시 기존 코드(`과거(~2026.04.04.)/`)에서 **유지할 패턴**:

| 파일 | 패턴 | 비고 |
|------|------|------|
| `connectors/registry.py` | `@register` 데코레이터 + 싱글톤 | 그대로 유지 |
| `connectors/base.py` | `ConnectorResult` dataclass + ABC | 필드 확장 (content_type, hashtags 추가) |
| `vault/io.py` | `tempfile.mkstemp` + `os.replace` atomic write | 그대로 유지 |
| `config/settings.py` | pydantic `BaseModel` + TOML 로더 | 새 섹션 추가 |
| `api/server.py` | FastAPI + lifespan context manager | 스케줄러/워커 통합 |

**교체 대상**:

| 기존 | 신규 | 이유 |
|------|------|------|
| `state/store.py` (JSON 파일) | SQLite WAL + aiosqlite | race condition 해결 |
| `connectors/kakao.py` (Termux push) | macOS SQLite DB 직접 읽기 | macOS 네이티브 |
| `engine.py` (동기식 `run_sync()`) | asyncio + Queue WorkerPool | 비동기 파이프라인 |
| `connectors/telegram_conn.py` (Pyrogram) | python-telegram-bot 봇 | 커맨드 센터 역할 |

---

*이 명세서는 10명의 리서치 에이전트(KakaoTalk, Telegram, Google Drive, Whisper, Obsidian, Web/YouTube, RAG, Samsung, LLM, System Architecture)와 5명의 리뷰어 에이전트(Architecture Coherence, Feasibility & Risk, Data Pipeline, Security & Privacy, Final Synthesis)의 분석을 종합한 결과입니다.*
