"""Pydantic settings model with TOML loader and environment variable overrides."""
from __future__ import annotations

import sys
from pathlib import Path
from functools import lru_cache

from pydantic import BaseModel, Field

if sys.version_info >= (3, 12):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib


class VaultSettings(BaseModel):
    root: Path = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
    meeting_dir: str = "1. INPUT/Meeting"
    daily_dir: str = "2. OUTPUT/Daily"
    inbox_dir: str = "1. INPUT/Inbox"
    people_dir: str = "1. INPUT/People"
    entity_dir: str = "1. Input"
    entity_watchlist: list[str] = Field(default_factory=list)

    @property
    def meeting_path(self) -> Path:
        return self.root / self.meeting_dir

    @property
    def daily_path(self) -> Path:
        return self.root / self.daily_dir

    @property
    def inbox_path(self) -> Path:
        return self.root / self.inbox_dir

    @property
    def people_path(self) -> Path:
        return self.root / self.people_dir


class StateSettings(BaseModel):
    dir: Path = Path("~/.config/onlime")

    @property
    def resolved_dir(self) -> Path:
        return self.dir.expanduser()

    @property
    def state_file(self) -> Path:
        return self.resolved_dir / "state.json"

    @property
    def log_file(self) -> Path:
        return self.resolved_dir / "sync.log"


class GCalSettings(BaseModel):
    calendar_ids: list[str] = ["primary", "seetheeye@chamchi.kr"]
    sync_days_back: int = 7
    sync_days_forward: int = 14
    creds_file: Path = Path("~/.config/onlime/credentials.json")
    token_file: Path = Path("~/.config/onlime/token.json")

    @property
    def resolved_creds_file(self) -> Path:
        return self.creds_file.expanduser()

    @property
    def resolved_token_file(self) -> Path:
        return self.token_file.expanduser()


class PlaudSettings(BaseModel):
    api_base: str = "https://api-apne1.plaud.ai"
    config_paths: list[Path] = Field(default_factory=lambda: [
        Path("~/.plaud/config.json"),
        Path("~/.config/plaud/token"),
    ])
    token_file: Path = Path("~/.config/onlime/plaud_token.txt")
    plaud_config_file: Path = Path("~/.config/onlime/plaud_config.json")


class GeneralSettings(BaseModel):
    timezone: str = "Asia/Seoul"
    min_overlap_ratio: float = 0.3


class KakaoSettings(BaseModel):
    nickname_to_name: dict[str, str] = Field(default_factory=dict)


class SlackSettings(BaseModel):
    bot_token: str = ""
    sync_channels: list[str] = Field(default_factory=list)
    sync_days_back: int = 1


class TelegramSettings(BaseModel):
    api_id: int = 0
    api_hash: str = ""
    phone: str = ""
    session_dir: Path = Path("~/.config/onlime")
    sync_chats: list[str] = Field(default_factory=list)
    sync_days_back: int = 1

    @property
    def resolved_session_dir(self) -> Path:
        return self.session_dir.expanduser()


class RecordingSyncSettings(BaseModel):
    enabled: bool = False
    watch_dir: Path = Path("~/Recordings/synced")
    extensions: list[str] = Field(default_factory=lambda: [
        ".m4a", ".wav", ".mp3", ".ogg", ".3gp", ".amr",
    ])
    auto_note: bool = True  # 새 녹음 감지 시 자동 Obsidian 노트 생성

    @property
    def resolved_watch_dir(self) -> Path:
        return self.watch_dir.expanduser()


class MessagingSettings(BaseModel):
    apps: list[str] = Field(default_factory=lambda: [
        "com.kakao.talk",
        "com.Slack",
        "org.telegram.messenger",
        "com.instagram.android",
    ])
    ignore_rooms: list[str] = Field(default_factory=list)


class NameSettings(BaseModel):
    email_to_name: dict[str, str] = Field(default_factory=lambda: {
        "seetheeye@chamchi.kr": "최동인",
        "jh.shim@chamchi.kr": "심정혁",
        "uk.young@chamchi.kr": "김욱영",
        "wnsqud70@chamchi.kr": "김민재_참치개발자",
        "yunu.cho@chamchi.kr": "조연우",
        "joonho.yoon@chamchi.kr": "윤준호",
        "sungjin.jeon@chamchi.kr": "전성진",
        "seyeong.choe@chamchi.kr": "최세영",
    })
    known_contacts: list[str] = Field(default_factory=list)

    def resolve_name(self, email: str) -> str:
        """이메일을 한글 이름으로 변환. 매핑에 없으면 로마자에서 유추."""
        if email in self.email_to_name:
            return self.email_to_name[email]
        local = email.split("@")[0]
        parts = local.replace("_", ".").replace("-", ".").split(".")
        if len(parts) >= 2:
            return f"{parts[0].capitalize()} {parts[1].capitalize()}"
        return local


class Settings(BaseModel):
    vault: VaultSettings = VaultSettings()
    state: StateSettings = StateSettings()
    gcal: GCalSettings = GCalSettings()
    plaud: PlaudSettings = PlaudSettings()
    general: GeneralSettings = GeneralSettings()
    kakao: KakaoSettings = KakaoSettings()
    slack: SlackSettings = SlackSettings()
    telegram: TelegramSettings = TelegramSettings()
    recording_sync: RecordingSyncSettings = RecordingSyncSettings()
    messaging: MessagingSettings = MessagingSettings()
    names: NameSettings = NameSettings()


def _find_config_file() -> Path | None:
    """Search for onlime.toml in standard locations."""
    candidates = [
        Path.cwd() / "onlime.toml",
        Path(__file__).resolve().parents[3] / "onlime.toml",  # project root
        Path.home() / ".config" / "onlime" / "onlime.toml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from TOML file, with environment variable overrides."""
    import os

    path = config_path or _find_config_file()
    if path and path.is_file():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    else:
        raw = {}

    settings = Settings(**raw)

    # Environment variable overrides
    env_map = {
        "ONLIME_VAULT_ROOT": lambda v: setattr(settings.vault, "root", Path(v)),
        "ONLIME_TIMEZONE": lambda v: setattr(settings.general, "timezone", v),
        "ONLIME_STATE_DIR": lambda v: setattr(settings.state, "dir", Path(v)),
        "SLACK_BOT_TOKEN": lambda v: setattr(settings.slack, "bot_token", v),
        "TELEGRAM_API_ID": lambda v: setattr(settings.telegram, "api_id", int(v)),
        "TELEGRAM_API_HASH": lambda v: setattr(settings.telegram, "api_hash", v),
    }
    for env_key, setter in env_map.items():
        val = os.environ.get(env_key)
        if val:
            setter(val)

    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached global settings instance."""
    return load_settings()
