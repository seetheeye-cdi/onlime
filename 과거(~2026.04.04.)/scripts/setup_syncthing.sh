#!/usr/bin/env bash
# Syncthing 설치 및 초기 설정 (Mac 측)
# S26 Ultra 녹음 파일을 Mac에 동기화하기 위한 Syncthing 설정
set -euo pipefail

SYNC_DIR="${HOME}/Recordings/synced"
PLIST_PATH="${HOME}/Library/LaunchAgents/com.syncthing.syncthing.plist"

echo "=== Onlime Syncthing 설정 ==="
echo ""

# 1. Syncthing 설치
if command -v syncthing &>/dev/null; then
    echo "[OK] Syncthing이 이미 설치되어 있습니다: $(syncthing --version | head -1)"
else
    echo "[설치] brew install syncthing ..."
    brew install syncthing
    echo "[OK] Syncthing 설치 완료"
fi

# 2. 수신 폴더 생성
mkdir -p "${SYNC_DIR}"
echo "[OK] 수신 폴더 생성: ${SYNC_DIR}"

# 3. LaunchAgent 설정 (부팅 시 자동 실행)
if [ -f "${PLIST_PATH}" ]; then
    echo "[OK] LaunchAgent가 이미 존재합니다"
else
    cat > "${PLIST_PATH}" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.syncthing.syncthing</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/syncthing</string>
        <string>-no-browser</string>
        <string>-no-restart</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/syncthing.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/syncthing.err</string>
</dict>
</plist>
PLIST
    echo "[OK] LaunchAgent 생성: ${PLIST_PATH}"
fi

# 4. Syncthing 시작
if pgrep -x syncthing &>/dev/null; then
    echo "[OK] Syncthing이 이미 실행 중입니다"
else
    launchctl load "${PLIST_PATH}" 2>/dev/null || true
    echo "[OK] Syncthing 시작됨"
fi

echo ""
echo "=== 다음 단계 ==="
echo ""
echo "1. Syncthing Web UI 열기:"
echo "   open http://127.0.0.1:8384"
echo ""
echo "2. 폰(S26 Ultra)에 Syncthing 설치:"
echo "   - F-Droid: https://f-droid.org/packages/com.nutomic.syncthingandroid/"
echo "   - 또는 Play Store: 'Syncthing' 검색"
echo ""
echo "3. 폰 Syncthing 앱에서:"
echo "   a. 폴더 추가 → Voice Recorder 경로 선택"
echo "      경로: /storage/emulated/0/Recordings/Voice Recorder"
echo "   b. 장치 추가 → Mac의 Device ID 입력 (Web UI에서 확인)"
echo ""
echo "4. Mac Web UI에서:"
echo "   a. 폰 장치 수락"
echo "   b. 공유 폴더 수락 → 수신 경로: ${SYNC_DIR}"
echo ""
echo "5. 동일 Wi-Fi에 연결되면 자동 동기화 시작!"
echo ""
echo "=== 설정 완료 ==="
