"""Central configuration for obsidian-sync."""
from pathlib import Path

# Obsidian Vault
VAULT_ROOT = Path("/Users/cdiseetheeye/Documents/Obsidian_sinc")
MEETING_DIR = VAULT_ROOT / "0. INPUT" / "Meeting"
DAILY_DIR = VAULT_ROOT / "1. THINK" / "매일"
INBOX_DIR = VAULT_ROOT / "0. INPUT" / "COLLECT" / "00. Inbox"

# Sync state
STATE_DIR = Path.home() / ".config" / "obsidian-sync"
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "sync.log"

# Google Calendar
GCAL_CREDS_FILE = STATE_DIR / "credentials.json"
GCAL_TOKEN_FILE = STATE_DIR / "token.json"
CALENDAR_IDS = ["primary", "seetheeye@chamchi.kr"]
TIMEZONE = "Asia/Seoul"
SYNC_DAYS_BACK = 7
SYNC_DAYS_FORWARD = 14

# Plaud
PLAUD_CONFIG_PATHS = [
    Path.home() / ".plaud" / "config.json",
    Path.home() / ".config" / "plaud" / "token",
]

# Matching
MIN_OVERLAP_RATIO = 0.3

# 이메일 → 옵시디언 이름 매핑
EMAIL_TO_NAME = {
    "seetheeye@chamchi.kr": "최동인",
    "jh.shim@chamchi.kr": "심정혁",
    "uk.young@chamchi.kr": "김욱영",
    "wnsqud70@chamchi.kr": "김민재_참치개발자",
    "yunu.cho@chamchi.kr": "조연우",
    "joonho.yoon@chamchi.kr": "윤준호",
    "sungjin.jeon@chamchi.kr": "전성진",
    "seyeong.choe@chamchi.kr": "최세영",
}


def resolve_name(email: str) -> str:
    """이메일을 한글 이름으로 변환. 매핑에 없으면 로마자에서 유추."""
    if email in EMAIL_TO_NAME:
        return EMAIL_TO_NAME[email]
    # 로마자 표기법 기반 유추: local part에서 이름 추출
    local = email.split("@")[0]
    # firstname.lastname 패턴
    parts = local.replace("_", ".").replace("-", ".").split(".")
    if len(parts) >= 2:
        return f"{parts[0].capitalize()} {parts[1].capitalize()}"
    return local
