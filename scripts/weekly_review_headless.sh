#!/bin/bash
# 주간회고 자동 실행 스크립트
# macOS launchd에서 매주 일요일 자정에 호출됨
#
# 실행 전략:
#   1차: Claude Code headless 모드 (에이전트 10명 병렬 분석)
#   2차: Python fallback (Claude API 직접 호출)

set -euo pipefail

LOG_DIR="$HOME/.local/log/weekly-review"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== 주간회고 시작: $(date) ==="

# PATH 설정 (launchd 환경에서 필요)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"

ONLIME_DIR="$HOME/Desktop/Onlime"
VENV="$ONLIME_DIR/.venv"

# ─── 1차: Claude Code headless ───
if command -v claude &>/dev/null; then
    echo "[1차] Claude Code headless 모드 실행"

    cd "$ONLIME_DIR"

    # headless 모드로 주간회고 스킬 실행
    if claude -p "주간회고 실행해줘. /주간회고" \
        --output-format text \
        --max-turns 50 \
        >> "$LOG_FILE" 2>&1; then
        echo "=== Claude Code headless 성공: $(date) ==="
        exit 0
    else
        echo "[1차 실패] Claude Code headless 에러, Python fallback 시도"
    fi
else
    echo "[1차 건너뜀] Claude Code CLI 미설치"
fi

# ─── 2차: Python fallback ───
echo "[2차] Python fallback 실행"

if [ -d "$VENV" ]; then
    source "$VENV/bin/activate"
else
    echo "Warning: venv not found at $VENV, using system python"
fi

python "$ONLIME_DIR/scripts/weekly_review.py" >> "$LOG_FILE" 2>&1

echo "=== 주간회고 완료: $(date) ==="
