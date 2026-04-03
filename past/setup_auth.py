#!/usr/bin/env python3
"""One-time Google Calendar OAuth2 setup helper.

Usage:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or select existing)
  3. Enable "Google Calendar API"
  4. Go to Credentials → Create Credentials → OAuth client ID
     - Application type: Desktop app
     - Download the JSON file
  5. Save it as: ~/.config/obsidian-sync/credentials.json
  6. Run this script: python3 setup_auth.py
"""
import sys
from pathlib import Path

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))
from config import GCAL_CREDS_FILE, GCAL_TOKEN_FILE, STATE_DIR


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("Google Calendar OAuth2 Setup")
    print("=" * 50)

    if not GCAL_CREDS_FILE.exists():
        print(f"""
[Step 1] credentials.json이 필요합니다.

1. https://console.cloud.google.com/ 접속
2. 프로젝트 생성 또는 선택
3. API 및 서비스 → 라이브러리 → "Google Calendar API" 검색 → 사용 설정
4. API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기
   → OAuth 클라이언트 ID → 데스크톱 앱
5. JSON 다운로드 후 아래 경로에 저장:
   {GCAL_CREDS_FILE}

* OAuth 동의 화면 설정이 필요하면:
  - 사용자 유형: 외부
  - 범위: Google Calendar API (.../auth/calendar.readonly)
  - 테스트 사용자: 본인 이메일 추가
""")
        input("credentials.json을 저장한 후 Enter를 누르세요...")

        if not GCAL_CREDS_FILE.exists():
            print(f"❌ {GCAL_CREDS_FILE} 파일을 찾을 수 없습니다.")
            sys.exit(1)

    print("\n[Step 2] 브라우저에서 Google 계정 인증...")

    from google_auth_oauthlib.flow import InstalledAppFlow
    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

    flow = InstalledAppFlow.from_client_secrets_file(str(GCAL_CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    GCAL_TOKEN_FILE.write_text(creds.to_json())
    print(f"\n✅ 인증 완료! 토큰 저장됨: {GCAL_TOKEN_FILE}")
    print("이제 obsidian-sync를 실행할 수 있습니다.")


if __name__ == '__main__':
    main()
