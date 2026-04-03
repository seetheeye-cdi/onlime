#!/usr/bin/env python3
"""Install/uninstall LaunchD plist for automatic Onlime sync."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PLIST_NAME = "com.cdiseetheeye.onlime.plist"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def generate_plist(venv_path: Path, interval: int = 1800) -> str:
    """Generate LaunchD plist XML."""
    onlime_bin = venv_path / "bin" / "onlime"
    project_dir = Path(__file__).resolve().parent.parent
    log_dir = Path.home() / ".config" / "onlime"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cdiseetheeye.onlime</string>

    <key>ProgramArguments</key>
    <array>
        <string>{onlime_bin}</string>
        <string>run</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{project_dir}</string>

    <key>StartInterval</key>
    <integer>{interval}</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{log_dir}/launchd_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/launchd_stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{venv_path / 'bin'}:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""


def install(venv_path: Path, interval: int = 1800) -> None:
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plist_path = LAUNCH_AGENTS_DIR / PLIST_NAME

    # Unload if already loaded
    if plist_path.exists():
        subprocess.run(['launchctl', 'unload', str(plist_path)], capture_output=True)

    plist_content = generate_plist(venv_path, interval)
    plist_path.write_text(plist_content)
    print(f"Plist 생성: {plist_path}")

    result = subprocess.run(['launchctl', 'load', str(plist_path)], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"LaunchD 등록 완료! ({interval}초 간격)")
    else:
        print(f"LaunchD 등록 실패: {result.stderr}")
        sys.exit(1)


def uninstall() -> None:
    plist_path = LAUNCH_AGENTS_DIR / PLIST_NAME
    if plist_path.exists():
        subprocess.run(['launchctl', 'unload', str(plist_path)], capture_output=True)
        plist_path.unlink()
        print("LaunchD 해제 완료!")
    else:
        print("설치된 plist가 없습니다.")


def main():
    parser = argparse.ArgumentParser(description='Onlime LaunchD 자동화 설치')
    parser.add_argument('action', choices=['install', 'uninstall'], help='설치 또는 해제')
    parser.add_argument('--venv', type=str, default=None, help='venv 경로 (기본: 프로젝트 .venv)')
    parser.add_argument('--interval', type=int, default=1800, help='실행 간격(초, 기본: 1800)')
    args = parser.parse_args()

    if args.action == 'install':
        venv = Path(args.venv) if args.venv else Path(__file__).resolve().parent.parent / ".venv"
        if not (venv / "bin" / "onlime").exists():
            print(f"onlime 실행파일을 찾을 수 없습니다: {venv / 'bin' / 'onlime'}")
            print("먼저 pip install -e . 을 실행하세요.")
            sys.exit(1)
        install(venv, args.interval)
    else:
        uninstall()


if __name__ == '__main__':
    main()
