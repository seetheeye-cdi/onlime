#!/usr/bin/env python3
"""
Plaud.ai 토큰 추출 도우미.

Plaud 데스크톱 앱이 실행 중일 때 사용하세요.
브라우저 없이 토큰을 추출하는 스크립트입니다.

사용법:
  1. Plaud 데스크톱 앱이 실행 중인지 확인
  2. python3 extract_plaud_token.py

  또는 수동으로:
  1. https://web.plaud.ai 접속 (Chrome)
  2. F12 → Console 탭
  3. 입력: localStorage.getItem("tokenstr")
  4. 출력된 "bearer eyJ..." 값을 복사
  5. python3 extract_plaud_token.py --token "bearer eyJ..."
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / '.config' / 'obsidian-sync'
TOKEN_FILE = CONFIG_DIR / 'plaud_token.txt'
PLAUD_APP_CONFIG = Path.home() / 'Library' / 'Application Support' / 'Plaud' / 'config.json'


def get_api_domain():
    """Get API domain from Plaud desktop app config."""
    if PLAUD_APP_CONFIG.exists():
        cfg = json.loads(PLAUD_APP_CONFIG.read_text())
        return cfg.get('apiDomain', 'https://api-apne1.plaud.ai')
    return 'https://api-apne1.plaud.ai'


def test_token(token, api_domain):
    """Test if a token works against the Plaud API."""
    import urllib.request
    req = urllib.request.Request(
        f'{api_domain}/file/simple/web?page=1&pageSize=1',
        headers={
            'Authorization': f'bearer {token}',
            'Content-Type': 'application/json',
        }
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except Exception:
        return False


def save_token(token, api_domain):
    """Save token and API domain."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)

    # Also save API domain
    plaud_config = CONFIG_DIR / 'plaud_config.json'
    plaud_config.write_text(json.dumps({
        'token': token,
        'api_domain': api_domain,
    }, indent=2))

    print(f'토큰 저장됨: {TOKEN_FILE}')


def try_applescript_extraction():
    """Try to get token from running Plaud app via AppleScript/JavaScript."""
    # The Plaud desktop app is Electron-based
    # We can try to use osascript to execute JS in the app
    script = '''
    tell application "System Events"
        if exists (process "Plaud") then
            return "running"
        end if
    end tell
    return "not_running"
    '''
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == 'running'
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description='Plaud.ai 토큰 추출')
    parser.add_argument('--token', type=str, help='수동으로 토큰 입력 (bearer eyJ...)')
    args = parser.parse_args()

    api_domain = get_api_domain()
    print(f'API 도메인: {api_domain}')

    # Check if we already have a working token
    if TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()
        if test_token(existing, api_domain):
            print(f'기존 토큰이 유효합니다: {TOKEN_FILE}')
            return
        print('기존 토큰이 만료되었습니다. 새 토큰이 필요합니다.')

    if args.token:
        token = args.token.strip()
        # Strip "bearer " prefix if included
        if token.lower().startswith('bearer '):
            token = token[7:]

        if test_token(token, api_domain):
            save_token(token, api_domain)
            print('토큰이 유효합니다!')
        else:
            print('토큰이 유효하지 않습니다. 다시 확인해주세요.')
            sys.exit(1)
        return

    # Interactive mode
    plaud_running = try_applescript_extraction()

    print()
    print('=' * 50)
    print('Plaud.ai 토큰을 가져오는 방법:')
    print('=' * 50)
    print()
    print('1. Chrome에서 https://web.plaud.ai 접속 (로그인 상태)')
    print('2. F12 키 → Console 탭 열기')
    print('3. 아래 코드를 Console에 붙여넣고 Enter:')
    print()
    print('   localStorage.getItem("tokenstr")')
    print()
    print('4. 출력된 "bearer eyJ..." 값을 복사')
    print()

    if plaud_running:
        print('(Plaud 데스크톱 앱이 실행 중입니다)')

    token_input = input('토큰을 여기에 붙여넣기 (bearer eyJ...): ').strip()

    if not token_input:
        print('토큰이 입력되지 않았습니다.')
        sys.exit(1)

    # Clean the token
    token = token_input
    if token.startswith('"') and token.endswith('"'):
        token = token[1:-1]
    if token.lower().startswith('bearer '):
        token = token[7:]

    if test_token(token, api_domain):
        save_token(token, api_domain)
        print('토큰이 유효합니다! Plaud 동기화를 사용할 수 있습니다.')
    else:
        print('토큰이 유효하지 않습니다. 다시 시도해주세요.')
        sys.exit(1)


if __name__ == '__main__':
    main()
