"""Configuration via pydantic-settings + TOML."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-untyped]


# --- Sub-models ---


class VaultSettings(BaseModel):
    root: Path = Path("~/Documents/Obsidian_sinc")
    # 1차: 0.SYSTEM / 1.INPUT / 2.OUTPUT
    system_dir: str = "0.SYSTEM"
    inbox_dir: str = "1.INPUT/Inbox"
    meeting_dir: str = "1.INPUT/Meeting"
    article_dir: str = "1.INPUT/Article"
    book_dir: str = "1.INPUT/Book"
    class_dir: str = "1.INPUT/Class"
    media_dir: str = "1.INPUT/Media"
    term_dir: str = "1.INPUT/Term"
    quote_dir: str = "1.INPUT/Quote"
    people_dir: str = "1.INPUT/People"
    recording_dir: str = "1.INPUT/Recording"
    input_archive_dir: str = "1.INPUT/Archive"
    daily_dir: str = "2.OUTPUT/Daily"
    weekly_dir: str = "2.OUTPUT/Weekly"
    monthly_dir: str = "2.OUTPUT/Monthly"
    project_dir: str = "2.OUTPUT/Projects"
    explore_dir: str = "2.OUTPUT/Explore"
    think_dir: str = "2.OUTPUT/Think"
    questions_dir: str = "2.OUTPUT/Questions"
    output_people_dir: str = "2.OUTPUT/People"
    wiki_dir: str = "2.OUTPUT/Wiki"
    archive_dir: str = "0.SYSTEM/Archive"


class StateSettings(BaseModel):
    dir: Path = Path("~/.onlime")
    db_file: str = "onlime.db"

    @property
    def db_path(self) -> Path:
        return self.dir.expanduser() / self.db_file


class GeneralSettings(BaseModel):
    timezone: str = "Asia/Seoul"
    log_level: str = "INFO"


class KakaoSettings(BaseModel):
    enabled: bool = True
    export_dir: str = ""  # .txt export folder to watch
    use_kakaocli: bool = True  # prefer kakaocli DB polling over .txt watcher
    poll_interval_minutes: int = 30
    sync_days_back: int = 7
    schedule_hours: int = 6
    nickname_to_name: dict[str, str] = Field(default_factory=dict)
    exclude_rooms: list[str] = Field(default_factory=list)


class SlackSettings(BaseModel):
    enabled: bool = False
    sync_channels: list[str] = Field(default_factory=list)  # empty = all joined
    sync_days_back: int = 7
    poll_interval_minutes: int = 30


class TelegramBotSettings(BaseModel):
    enabled: bool = True
    allowed_user_ids: list[int] = Field(default_factory=list)
    assistant_model: str = "claude"


class GDriveSettings(BaseModel):
    enabled: bool = True
    watch_paths: list[str] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=lambda: [".DS_Store", "*.tmp", "~$*"])
    stability_delay_seconds: float = 2.0


class GCalSettings(BaseModel):
    enabled: bool = True
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"])
    schedule_minutes: int = 15
    sync_days_forward: int = 1
    creds_file: str = "~/.onlime/credentials.json"
    token_file: str = "~/.onlime/token.json"


class WebSettings(BaseModel):
    enabled: bool = True
    user_agent: str = "Mozilla/5.0 (Macintosh) Onlime/2.0"
    max_content_length: int = 500_000
    summary_model: str = "claude"
    youtube_prefer_transcript: bool = True


class STTSettings(BaseModel):
    model: str = "large-v3-turbo"
    compute_type: str = "int8"
    device: str = "cpu"
    language: str = "ko"
    beam_size: int = 5
    initial_prompt: str = "이것은 한국어 회의 녹음입니다."


class LLMProviderConfig(BaseModel):
    model: str = ""
    base_url: str = ""


class LLMSettings(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["claude", "ollama"])
    default_timeout: int = 30
    daily_token_limit: int = 1_200_000
    claude: LLMProviderConfig = LLMProviderConfig(model="claude-sonnet-4-6")
    ollama: LLMProviderConfig = LLMProviderConfig(model="gemma2:9b", base_url="http://localhost:11434")


class SearchSettings(BaseModel):
    db_path: str = "~/.onlime/lancedb"
    embedding_model: str = "BAAI/bge-m3"
    chunk_max_tokens: int = 512
    search_top_k: int = 10
    rerank_top_k: int = 5


class RoutingSettings(BaseModel):
    routes: dict[str, str] = Field(default_factory=lambda: {
        "#aip": "2.OUTPUT/Projects/borromeo",
        "#borromeo": "2.OUTPUT/Projects/borromeo",
        "#boromeo": "2.OUTPUT/Projects/borromeo",
        "#chamchi": "2.OUTPUT/Projects/chamchi",
        "#thehackathon": "2.OUTPUT/Projects/hackathon",
        "#nextnobel": "2.OUTPUT/Projects/next_nobel",
        "#philosophy": "2.OUTPUT/Projects/philosophy",
    })


class SchedulerSettings(BaseModel):
    enabled: bool = True
    morning_brief_hour: int = 8
    daily_summary_hour: int = 23


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class NamesSettings(BaseModel):
    known_contacts: list[str] = Field(default_factory=list)
    email_to_name: dict[str, str] = Field(default_factory=dict)


# --- Root Settings ---


class Settings(BaseModel):
    vault: VaultSettings = VaultSettings()
    state: StateSettings = StateSettings()
    general: GeneralSettings = GeneralSettings()
    kakao: KakaoSettings = KakaoSettings()
    slack: SlackSettings = SlackSettings()
    telegram_bot: TelegramBotSettings = TelegramBotSettings()
    gdrive: GDriveSettings = GDriveSettings()
    gcal: GCalSettings = GCalSettings()
    web: WebSettings = WebSettings()
    stt: STTSettings = STTSettings()
    llm: LLMSettings = LLMSettings()
    search: SearchSettings = SearchSettings()
    routing: RoutingSettings = RoutingSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    server: ServerSettings = ServerSettings()
    names: NamesSettings = NamesSettings()


def _find_config_file() -> Path | None:
    candidates = [
        Path("onlime.toml"),
        Path.home() / ".onlime" / "onlime.toml",
        Path.home() / ".config" / "onlime" / "onlime.toml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_toml(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    config_path = _find_config_file()
    if config_path:
        data = _load_toml(config_path)
        return Settings(**data)
    return Settings()
