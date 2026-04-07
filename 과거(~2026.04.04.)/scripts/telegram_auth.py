"""Telegram 첫 인증 스크립트 — 터미널에서 직접 실행.

사용법:
    .venv/bin/python3.12 scripts/telegram_auth.py

Telegram 앱으로 전송된 인증 코드를 입력하면
세션 파일이 ~/.config/onlime/onlime_telegram.session 에 저장됩니다.
이후에는 코드 입력 없이 자동 로그인됩니다.
"""
import sys
sys.path.insert(0, "src")

from pyrogram import Client
from onlime.config.settings import load_settings

settings = load_settings()
tg = settings.telegram
session_dir = tg.resolved_session_dir
session_dir.mkdir(parents=True, exist_ok=True)
session_path = str(session_dir / "onlime_telegram")

print(f"API ID: {tg.api_id}")
print(f"Phone: {tg.phone}")
print(f"Session: {session_path}")
print()

client = Client(
    session_path,
    api_id=tg.api_id,
    api_hash=tg.api_hash,
    phone_number=tg.phone,
)

with client:
    me = client.get_me()
    print(f"\n인증 완료! {me.first_name} ({me.phone_number})")
    print("세션 파일이 저장되었습니다. 이후 자동 로그인됩니다.")
