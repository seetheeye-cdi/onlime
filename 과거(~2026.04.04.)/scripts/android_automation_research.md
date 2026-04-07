# Android 자동화 프레임워크 및 개인 데이터 처리 도구 종합 조사

> 조사일: 2026-04-02
> 목적: 안드로이드 기기에서 개인 데이터(알림, 녹음, 캘린더 등)를 자동으로 수집/처리/보고하는 최적의 워크플로우 구축

---

## 목차
1. [Tasker - 핵심 자동화 엔진](#1-tasker)
2. [MacroDroid - 간편 자동화](#2-macrodroid)
3. [Automate (LlamaLab) - 플로우 기반 자동화](#3-automate)
4. [Termux - 안드로이드에서 Python/스크립트 실행](#4-termux)
5. [Join by joaoapps - 크로스 디바이스 자동화](#5-join)
6. [IFTTT / Zapier - 클라우드 기반 연동](#6-ifttt-zapier)
7. [Python + ADB - Mac에서 원격 제어](#7-python-adb)
8. [Tasker + Termux 조합 - 최강 자동화](#8-tasker-termux)
9. [n8n - 셀프 호스팅 워크플로우 자동화](#9-n8n)
10. [온디바이스 vs PC 연결 자동화 비교](#10-comparison)
11. [Samsung Bixby Routines](#11-bixby)
12. [실전 워크플로우: 카카오톡 자동 내보내기 -> 녹음 전사 -> 캘린더 매칭 -> 보고서 생성](#12-workflow)

---

## 1. Tasker - 핵심 자동화 엔진 {#1-tasker}

### 개요
Tasker는 Android에서 가장 강력한 자동화 앱으로, 400개 이상의 자동화 액션을 지원한다. 2025년 5월에 AI 생성기(OpenRouter/Google Gemini 기반)가 추가되었고, 2026년 2월에는 BeanShell 인터프리터, Shizuku 통합, 일출/일몰 시간 지원이 추가되었다.

### 핵심 기능

#### 알림 읽기 (Notification Interception)
```
설정 경로:
1. Android 설정 -> 앱 및 알림 -> 고급 -> 특수 앱 접근 -> 알림 접근
2. Tasker 선택하여 권한 부여
3. Tasker 내: 메뉴 -> Preferences -> Misc -> 알림 가로채기 활성화
```

**주요 변수:**
- `%NTITLE` - 알림 제목 (약 60자 제한)
- `%NTEXT` - 알림 텍스트
- `%NPACKAGE` - 알림을 보낸 앱 패키지명

**AutoNotification 플러그인 (권장):**
- Tasker 내장 알림 변수보다 더 많은 내용 전달 가능
- 알림 취소 사유(사용자 해제, 알림 클릭, 시스템 취소 등) 필터링
- 카카오톡 등 채팅앱 알림에 자동 답장 가능

#### 트리거 액션 설정
```
프로필 예시 - 카카오톡 메시지 감지:
1. Profile -> Event -> UI -> Notification
2. Owner Application: com.kakao.talk
3. Task: 원하는 액션 (로그 저장, 파일 쓰기, Webhook 호출 등)
```

#### 파일 작업
- 로컬 파일 읽기/쓰기/이동/복사/삭제
- Google Drive 연동
- 디렉토리 감시 (File Modified 이벤트)
- CSV/JSON 포맷 파일 생성

### 실전 설정 가이드

```
[프로필: 카카오톡 알림 -> 텍스트 파일 저장]

Profile:
  Event: Notification [Owner App: KakaoTalk]

Task:
  1. Variable Set: %date to %DATE %TIME
  2. Variable Set: %sender to %NTITLE
  3. Variable Set: %message to %NTEXT
  4. Write File: /sdcard/Onlime/kakao_log_%DATEFULL.txt
     Content: [%date] %sender: %message\n
     Append: On
  5. (선택) HTTP Request: POST to n8n webhook URL
     Body: {"sender":"%sender","message":"%message","time":"%date"}
```

---

## 2. MacroDroid - 간편 자동화 {#2-macrodroid}

### 개요
MacroDroid는 드래그 앤 드롭 인터페이스와 사전 제작 템플릿으로 코딩 없이 자동화를 구현할 수 있는 앱이다. Tasker보다 진입 장벽이 낮다.

### 핵심 사양
| 항목 | 수치 |
|------|------|
| 트리거 | 80개 이상 |
| 액션 | 100개 이상 |
| 제약 조건 | 50개 이상 |
| Tasker 플러그인 호환 | 지원 |

### 주요 트리거 유형
- **위치 기반**: GPS, 셀 타워, 지오펜싱
- **디바이스 상태**: 배터리 레벨, 앱 시작/종료
- **센서**: 흔들기, 조도
- **연결**: 블루투스, WiFi, 알림 수신
- **Work Profile 트리거** (최신 추가)

### 최근 추가 기능 (2025-2026)
- Check Image on Screen 액션 (Android 11+) - 화면 이미지 인식
- Goto 액션 - 조건부 흐름 제어
- Camera Circle Notification 액션
- Samsung Routines 액션 (삼성 기기 전용)
- MacroDroid Enabled 트리거

### Tasker vs MacroDroid 선택 기준

| 기준 | Tasker | MacroDroid |
|------|--------|-----------|
| 난이도 | 높음 (학습 곡선) | 낮음 (직관적) |
| 유연성 | 매우 높음 | 중간 |
| 플러그인 | 풍부 (AutoApps 생태계) | Tasker/Locale 플러그인 호환 |
| 스크립팅 | JavaScript, BeanShell | 제한적 |
| 가격 | 유료 ($3.49) | 무료(5개 매크로)/Pro($4.99) |
| API 연동 | 강력 | 기본적 |

**결론**: 단순 자동화는 MacroDroid, 복잡한 워크플로우(스크립트 실행, API 연동, 조건 분기)는 Tasker 권장.

---

## 3. Automate (LlamaLab) - 플로우 기반 자동화 {#3-automate}

### 개요
Automate는 시각적 플로우차트로 자동화를 구성하는 무료 앱이다. 410개 이상의 빌딩 블록을 제공하며, 500만+ 설치, 평균 4.4점 평가를 받고 있다.

### 핵심 특징
- **시각적 플로우차트**: 블록을 연결하여 자동화 로직 구성
- **초보자 친화적**: 사전 정의 옵션 / 고급 사용자용 표현식, 변수, 함수 지원
- **커뮤니티 플로우 공유**: 앱 내에서 다른 사용자 플로우 다운로드 가능

### 자동화 가능 영역
- 로컬/원격 저장소 파일 관리 (Google Drive, FTP)
- 사진 촬영, 오디오/비디오 녹화
- 이메일/Gmail, SMS, MMS 발송
- 전화 통화 제어
- Bluetooth, Wi-Fi, NFC 설정
- 위치, 시간 기반 조건 트리거

### Termux:Tasker 연동
Automate에서도 Termux:Tasker 플러그인을 사용하여 Termux 명령 실행 가능.

### 적합한 사용 사례
- 복잡한 조건 분기가 있는 자동화를 시각적으로 이해하고 싶을 때
- 커뮤니티에서 만든 플로우를 재활용하고 싶을 때
- Tasker의 학습 곡선이 부담될 때

---

## 4. Termux - 안드로이드에서 Python/스크립트 실행 {#4-termux}

### 개요
Termux는 안드로이드에서 리눅스 명령줄 환경을 제공하는 터미널 에뮬레이터이다. Python, Node.js, Ruby 등 다양한 프로그래밍 언어를 직접 실행할 수 있다.

### 설치 (중요!)
```bash
# 2025년 이후 Google Play Store 버전은 더 이상 유지보수되지 않음
# 반드시 F-Droid 또는 GitHub에서 설치할 것

# F-Droid 앱 설치 후:
# F-Droid -> Termux 검색 -> 설치

# 또는 GitHub Releases에서 APK 직접 다운로드:
# https://github.com/termux/termux-app/releases
```

### Python 환경 설정
```bash
# 패키지 업데이트
pkg update && pkg upgrade

# Python 설치
pkg install python

# pip로 필수 패키지 설치
pip install requests openai whisper google-api-python-client

# Termux API 설치 (하드웨어/시스템 접근)
pkg install termux-api

# Git 설치 (버전 관리)
pkg install git
```

### Termux API 기능 (termux-api 패키지)
```bash
# 카메라 접근
termux-camera-photo /sdcard/photo.jpg

# 알림 표시
termux-notification --title "제목" --content "내용"

# SMS 발송
termux-sms-send -n 010-1234-5678 "메시지 내용"

# 센서 데이터 읽기
termux-sensor -s accelerometer

# 클립보드 읽기/쓰기
termux-clipboard-get
termux-clipboard-set "텍스트"

# 전화 걸기
termux-telephony-call 010-1234-5678

# 위치 정보
termux-location -p gps

# 진동
termux-vibrate -d 500

# 배터리 상태
termux-battery-status

# 녹음
termux-microphone-record -f /sdcard/recording.m4a
termux-microphone-record -q  # 녹음 중지
```

### Cron Job 설정 (정기 자동화)
```bash
# cronie 설치
pkg install cronie

# cron 서비스 시작
crond

# crontab 편집
crontab -e

# 예시: 매일 오후 6시 카카오톡 로그 백업
0 18 * * * python /data/data/com.termux/files/home/scripts/backup_kakao.py

# 예시: 매 30분마다 데이터 동기화
*/30 * * * * python /data/data/com.termux/files/home/scripts/sync_data.py
```

---

## 5. Join by joaoapps - 크로스 디바이스 자동화 {#5-join}

### 개요
Join은 Google 계정을 통해 Android, PC, 브라우저 간 데이터를 주고받는 크로스 디바이스 도구이다. Tasker 개발자(joaoapps)가 만들어 Tasker와 깊은 통합을 제공한다.

### 핵심 기능
- **알림 동기화**: Android 알림을 다른 기기에서 확인/응답 (WhatsApp 메시지를 PC에서 답장 등)
- **SMS/MMS**: 웹 브라우저에서 직접 SMS/MMS 발송/수신
- **원격 입력**: PC에서 Android 앱에 직접 텍스트 입력
- **파일 전송**: 기기 간 파일 전송 (자동 열기 옵션)
- **원격 파일 탐색**: PC에서 Android 파일 시스템 탐색
- **스크린샷**: 원격으로 Android 스크린샷 캡처
- **위치 추적**: 기기 위치 확인
- **종단간 암호화**: 보안 통신

### Tasker + Join 연동 시나리오

```
[Mac에서 Android 카카오톡 데이터 수집 워크플로우]

1. Tasker 프로필: 카카오톡 알림 감지
2. Tasker 태스크: Join Push 액션 -> Mac Chrome 확장에 데이터 전송
3. Mac 측: Join API로 데이터 수신 -> Python 스크립트 처리

Join API 호출 예시 (Mac에서):
curl "https://joinjoaomgcd.appspot.com/_ah/api/messaging/v1/sendPush?\
  deviceId=YOUR_DEVICE_ID&\
  text=명령어&\
  apikey=YOUR_API_KEY"
```

### 가격
- 30일 무료 체험 후 1회 결제 (약 $5)

---

## 6. IFTTT / Zapier - 클라우드 기반 연동 {#6-ifttt-zapier}

### IFTTT vs Zapier 비교

| 항목 | IFTTT | Zapier |
|------|-------|--------|
| 연동 서비스 수 | ~800개 | ~6,000개 |
| 워크플로우 복잡도 | 단순 (if-then) | 다단계 분기 |
| 주 용도 | 개인 자동화, IoT | 비즈니스 자동화 |
| Android 연동 | Android Device 서비스 | 웹훅 기반 |
| 가격 (무료) | 5개 애플릿 | 5개 Zap, 100 task/월 |
| AI 기능 | 분석/요약/추출 (2025+) | AI 분기 로직 |
| 실행 속도 | 20% 향상 (2025) | 실시간에 가까움 |

### IFTTT Android 연동 (2025 업데이트)
- 방해 금지 모드 자동 ON/OFF
- 앱 실행 시 자동 액션
- 위치 기반 트리거
- 배터리 레벨 트리거

### 실전 활용 예시

```
[IFTTT: 카카오톡 알림 -> Google Sheets 기록]

1. Trigger: Android Notification from KakaoTalk
2. Action: Google Sheets - Add Row
   - Timestamp: {{OccurredAt}}
   - Title: {{NotificationTitle}}
   - Content: {{NotificationBody}}

[Zapier: Webhook -> OpenAI Whisper -> Google Docs]

1. Trigger: Webhook (Tasker에서 녹음 파일 URL 전송)
2. Action: OpenAI - Transcribe Audio
3. Action: Google Docs - Create Document
4. Action: Gmail - Send Email (보고서 발송)
```

### 한계
- 실시간성 부족 (IFTTT는 최대 15분 지연)
- 무료 플랜 제한적
- 안드로이드 알림 내용 접근이 제한적
- 복잡한 온디바이스 작업 불가

---

## 7. Python + ADB - Mac에서 원격 제어 {#7-python-adb}

### 개요
ADB(Android Debug Bridge)를 통해 Mac에서 Android 기기를 원격으로 제어할 수 있다. Python과 결합하면 강력한 자동화 스크립팅이 가능하다.

### Mac 환경 설정

```bash
# Homebrew로 ADB 설치
brew install android-platform-tools

# 연결 확인
adb devices

# WiFi ADB 연결 (케이블 없이)
adb tcpip 5555
adb connect 192.168.1.XXX:5555
```

### Python 라이브러리 설치

```bash
# pure-python-adb (순수 Python ADB 구현)
pip install pure-python-adb

# 또는 Google의 python-adb
pip install adb
```

### Python ADB 자동화 스크립트 예시

```python
from ppadb.client import Client as AdbClient
import subprocess
import time

# ADB 서버 연결
client = AdbClient(host="127.0.0.1", port=5037)
devices = client.devices()
device = devices[0]

# 화면 캡처
device.shell("screencap -p /sdcard/screen.png")
device.pull("/sdcard/screen.png", "screen.png")

# 카카오톡 실행
device.shell("am start -n com.kakao.talk/.activity.main.MainActivity")
time.sleep(2)

# 화면 터치 (좌표 기반)
device.shell("input tap 500 1200")

# 텍스트 입력
device.shell("input text 'Hello'")

# 파일 가져오기
device.pull("/sdcard/kakao_backup/", "./local_backup/")

# 녹음 파일 가져오기
device.pull("/sdcard/Recordings/", "./recordings/")
```

### ADB 셸 유용 명령어

```bash
# 카카오톡 알림 로그 확인
adb shell dumpsys notification | grep -A 10 "com.kakao.talk"

# 파일 목록 확인
adb shell ls /sdcard/KakaoTalk/

# 파일 복사 (기기 -> Mac)
adb pull /sdcard/KakaoTalk/Chats/ ./kakao_chats/

# 녹음 파일 복사
adb pull /sdcard/Recordings/ ./recordings/

# 앱 데이터 백업 (루팅 불필요)
adb backup -f kakao_backup.ab com.kakao.talk

# 현재 화면 정보 (UI Automator)
adb shell uiautomator dump /sdcard/ui.xml
adb pull /sdcard/ui.xml ./ui.xml
```

### 한계
- ADB는 화면 상태를 인식하지 못함 (좌표 기반 "맹목적" 조작)
- UI 변경 시 스크립트가 깨질 수 있음
- USB 또는 WiFi 연결 필요
- 기기 잠금 해제 상태여야 함

---

## 8. Tasker + Termux 조합 - 최강 자동화 {#8-tasker-termux}

### 왜 이 조합이 최강인가

Tasker는 **오케스트레이터**(이벤트 감지, 조건 판단, 트리거)로, Termux는 **실행기**(Python 스크립트, Linux 명령, 네트워크 통신)로 동작한다. 이 조합은 안드로이드 자동화의 끝판왕이다.

### Termux:Tasker 플러그인 설정

```
[설치 순서]

1. Termux 설치 (F-Droid에서)
2. Termux:Tasker 설치 (F-Droid에서)
3. Termux:API 설치 (F-Droid에서)
4. Tasker 설치 (Google Play에서)

[권한 설정]

1. Termux 최초 실행 (부트스트랩 설치)
2. 권한:
   - Termux:Tasker >= 0.5: com.termux.permission.RUN_COMMAND 권한 필요
   - Termux >= 0.100: "다른 앱 위에 표시" 권한
     Android 설정 -> 앱 -> Termux -> 고급 -> 다른 앱 위에 그리기

[스크립트 디렉토리 설정]

mkdir -p ~/.termux/tasker/
chmod 700 ~/.termux/tasker/
```

### 실전 스크립트 구성

```bash
# ~/.termux/tasker/process_kakao_notification.sh
#!/bin/bash

SENDER="$1"
MESSAGE="$2"
TIMESTAMP="$3"

# Python 스크립트 호출
python3 ~/scripts/process_notification.py \
  --sender "$SENDER" \
  --message "$MESSAGE" \
  --timestamp "$TIMESTAMP"
```

```python
# ~/scripts/process_notification.py
import argparse
import json
import os
from datetime import datetime
import requests

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sender', required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--timestamp', required=True)
    args = parser.parse_args()

    # 로그 파일에 기록
    log_entry = {
        "sender": args.sender,
        "message": args.message,
        "timestamp": args.timestamp,
        "processed_at": datetime.now().isoformat()
    }

    log_dir = os.path.expanduser("~/onlime_data/kakao_logs/")
    os.makedirs(log_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"kakao_{date_str}.jsonl")

    with open(log_file, 'a') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    # n8n webhook으로 전송 (선택)
    webhook_url = "http://YOUR_N8N_SERVER:5678/webhook/kakao-notification"
    try:
        requests.post(webhook_url, json=log_entry, timeout=5)
    except:
        pass  # 오프라인 시 로컬에만 저장

if __name__ == '__main__':
    main()
```

### Tasker 프로필 설정

```
[Tasker 프로필: 카카오톡 -> Termux 스크립트 실행]

Profile:
  Event: Notification
  Owner App: com.kakao.talk

Task:
  1. Plugin -> Termux:Tasker
     Executable: process_kakao_notification.sh
     Arguments: "%NTITLE" "%NTEXT" "%TIMES"
     Execute in terminal session: OFF (백그라운드 실행)
```

### 고급 활용: 녹음 자동 전사

```bash
# ~/.termux/tasker/transcribe_recording.sh
#!/bin/bash

RECORDING_FILE="$1"

# Whisper로 전사 (로컬 또는 API)
python3 ~/scripts/transcribe.py --file "$RECORDING_FILE"
```

```python
# ~/scripts/transcribe.py
import openai
import argparse
import json
import os

def transcribe(file_path):
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ko"
        )

    # 결과 저장
    output_dir = os.path.expanduser("~/onlime_data/transcripts/")
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_file = os.path.join(output_dir, f"{base_name}.txt")

    with open(output_file, 'w') as f:
        f.write(transcript.text)

    return output_file

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True)
    args = parser.parse_args()
    transcribe(args.file)
```

---

## 9. n8n - 셀프 호스팅 워크플로우 자동화 {#9-n8n}

### 개요
n8n은 시각적 워크플로우 빌더 + 코드 작성이 가능한 오픈소스 자동화 플랫폼이다. 셀프 호스팅으로 데이터 통제가 가능하며, 400~1,900개의 사전 빌드 커넥터를 제공한다.

### 설치 (Mac/서버)

```bash
# Docker로 설치 (권장)
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  docker.n8n.io/n8nio/n8n

# 또는 npm으로 설치
npm install n8n -g
n8n start

# 접속: http://localhost:5678
```

### Android 연동 방법

n8n에는 전용 Android 앱이 없지만, **Webhook 노드**를 통해 Tasker/Termux와 연동할 수 있다.

```
[n8n 워크플로우: Webhook -> 데이터 처리 -> 저장]

1. Webhook 노드 (트리거)
   - Method: POST
   - Path: /kakao-notification
   - URL: http://YOUR_SERVER:5678/webhook/kakao-notification

2. Function 노드 (데이터 가공)
   - 발신자/메시지/시간 파싱
   - 카테고리 분류

3. Google Sheets 노드 (기록)
   - 스프레드시트에 행 추가

4. IF 노드 (조건 분기)
   - 중요 키워드 포함 시 -> Slack/이메일 알림
   - 그 외 -> 로그만 저장
```

### Tasker -> n8n Webhook 호출

```
[Tasker Task: n8n Webhook 호출]

1. HTTP Request
   Method: POST
   URL: http://YOUR_N8N_SERVER:5678/webhook/kakao-notification
   Headers: Content-Type: application/json
   Body: {
     "sender": "%NTITLE",
     "message": "%NTEXT",
     "timestamp": "%TIMES",
     "app": "kakaotalk"
   }
```

### n8n의 강점 (개인 데이터 처리용)
- **셀프 호스팅**: 데이터가 외부로 나가지 않음 (프라이버시)
- **AI 노드**: OpenAI, Anthropic 등 LLM 직접 연동
- **스케줄링**: Cron 기반 정기 실행
- **시각적 디버깅**: 각 노드의 입출력을 실시간 확인
- **무료**: 셀프 호스팅 시 무제한 워크플로우

---

## 10. 온디바이스 vs PC 연결 자동화 비교 {#10-comparison}

### 종합 비교표

| 기준 | 온디바이스 (Tasker/Termux) | PC 연결 (ADB/Python) | 하이브리드 (Tasker+n8n) |
|------|--------------------------|----------------------|----------------------|
| **실시간성** | 즉시 반응 | 폴링 필요 또는 지연 | 웹훅으로 준실시간 |
| **화면 인식** | Accessibility API로 가능 | UI Automator (제한적) | 온디바이스가 담당 |
| **스크립팅 파워** | Termux (Python 등) | 완전한 Python 환경 | 양쪽 모두 활용 |
| **항상 활성** | 기기만 켜져 있으면 동작 | PC 켜져 있어야 함 | 서버 필요 |
| **외부 의존성** | 없음 | USB/WiFi 연결 필요 | 네트워크 필요 |
| **처리 능력** | 기기 성능에 제한 | PC의 강력한 CPU/GPU | 서버 성능 활용 |
| **설정 복잡도** | 중간 | 높음 | 높음 |
| **안정성** | Android 백그라운드 제한 | 연결 끊김 가능 | 네트워크 의존 |

### 권장 아키텍처

```
[최적의 하이브리드 아키텍처]

Android (Tasker + Termux)
  -> 이벤트 감지 (알림, 파일 변경, 위치 등)
  -> 1차 데이터 수집 및 로컬 저장
  -> Webhook으로 서버에 전달

Mac/Server (n8n + Python)
  -> 복잡한 데이터 처리 (LLM, Whisper 등)
  -> 보고서 생성
  -> 장기 저장 및 분석
  -> 결과를 Join API로 Android에 피드백
```

### 온디바이스 자동화 시 주의사항
- **배터리 최적화 제외**: 설정 -> 배터리 -> Tasker/Termux를 최적화 제외
- **백그라운드 실행 허용**: Android 설정 -> 앱 -> Tasker -> 배터리 -> 제한 없음
- **앱 자동 종료 방지**: 삼성 기기의 경우 설정 -> 배터리 -> 절전 모드 -> 사용하지 않는 앱 절전에서 Tasker/Termux 제외
- **Doze 모드 대응**: AlarmManager 사용 또는 Foreground Service 유지

---

## 11. Samsung Bixby Routines {#11-bixby}

### 개요
Bixby Routines는 삼성 갤럭시 기기에 내장된 자동화 도구이다. 2026년 업데이트로 자연어 기반 루틴 생성이 가능해졌다.

### 주요 기능 (2025-2026)

#### 자연어 루틴 생성 (2026 신기능)
```
사용자: "매일 밤 9시에 화면 밝기를 낮춰줘"
-> Bixby가 자동으로 루틴 생성 (수동 설정 불필요)
```

#### LLM 기반 고급 명령 이해
- 복잡한 자연어 문장 이해 가능
- 다단계 태스크 수행
- Perplexity AI와 협업하여 고급 추론

#### 스마트 홈 연동
```
"세탁이 끝나면 로봇 청소기 시작해" -> 세탁기 완료 -> 로봇 청소기 트리거
"비 오면 제습기 돌려" -> 날씨 기반 자동 루틴
```

### 트리거/조건 유형
- 시간, 위치, Wi-Fi 연결
- 블루투스 기기 연결
- 앱 실행/종료
- 충전 상태
- 전화/메시지 수신

### 한계
- 삼성 갤럭시 기기 전용
- Tasker 대비 액션 수가 제한적
- 외부 API 연동 불가
- 스크립트 실행 불가
- 알림 내용 기반 조건 분기 제한적

### Tasker vs Bixby Routines

| 기준 | Bixby Routines | Tasker |
|------|----------------|--------|
| 설정 난이도 | 매우 쉬움 | 어려움 |
| 자연어 | 지원 (2026) | 미지원 |
| 액션 수 | 제한적 | 400+ |
| 외부 API | 불가 | 가능 |
| 스크립팅 | 불가 | JavaScript/BeanShell |
| 알림 기반 | 기본적 | 고급 (AutoNotification) |
| 가격 | 무료 (내장) | 유료 ($3.49) |

**결론**: 간단한 기기 설정 자동화는 Bixby Routines로 충분. 데이터 처리 파이프라인에는 Tasker 필수.

---

## 12. 실전 워크플로우: 카카오톡 자동 내보내기 -> 녹음 전사 -> 캘린더 매칭 -> 보고서 생성 {#12-workflow}

### 전체 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    Android (Galaxy)                       │
│                                                           │
│  ┌──────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │ KakaoTalk │───>│    Tasker     │───>│    Termux      │  │
│  │  알림     │    │ (이벤트감지)  │    │ (Python실행)   │  │
│  └──────────┘    └──────┬───────┘    └───────┬────────┘  │
│                         │                     │           │
│  ┌──────────┐           │                     │           │
│  │ 녹음 앱  │───────────┘                     │           │
│  │ (통화녹음)│                                │           │
│  └──────────┘                                 │           │
│                                               │           │
└───────────────────────────────────────────────┼───────────┘
                                                │
                                    Webhook / File Sync
                                                │
┌───────────────────────────────────────────────┼───────────┐
│                Mac / Server                    │           │
│                                               ▼           │
│  ┌─────────┐   ┌──────────┐   ┌─────────────────────┐   │
│  │  n8n    │──>│ Whisper  │──>│ LLM (GPT/Claude)    │   │
│  │ Webhook │   │ 음성전사 │   │ 보고서 생성          │   │
│  └────┬────┘   └──────────┘   └──────────┬──────────┘   │
│       │                                    │              │
│       ▼                                    ▼              │
│  ┌─────────────┐              ┌──────────────────────┐   │
│  │Google Calendar│              │  보고서 (Markdown/   │   │
│  │  API 매칭    │──────────────>│  Google Docs/Email)  │   │
│  └─────────────┘              └──────────────────────┘   │
└───────────────────────────────────────────────────────────┘
```

### Step 1: 카카오톡 메시지 자동 수집

#### 방법 A: 알림 기반 수집 (실시간)

```
[Tasker 프로필]
Profile: KakaoTalk Notification Capture
  Event: Notification
  Owner App: com.kakao.talk

Task: Capture KakaoTalk
  1. Variable Set: %kakao_data to {
       "sender": "%NTITLE",
       "message": "%NTEXT",
       "time": "%TIME",
       "date": "%DATE"
     }

  2. Plugin -> Termux:Tasker
     Executable: kakao_capture.sh
     Arguments: '%kakao_data'
     Background: ON

  3. (선택) HTTP Request POST
     URL: http://MAC_IP:5678/webhook/kakao
     Body: %kakao_data
```

#### 방법 B: 채팅 내보내기 자동화 (일괄)

```
[Tasker + AutoInput으로 카카오톡 채팅 내보내기 자동화]

주의: 이 방법은 UI 자동화이므로 카카오톡 업데이트 시 깨질 수 있음

Task: Export KakaoTalk Chat
  1. Launch App: com.kakao.talk
  2. Wait: 2초
  3. AutoInput Action: Click (채팅방 선택)
  4. Wait: 1초
  5. AutoInput Action: Click (메뉴 버튼 - 3점)
  6. AutoInput Action: Click ("대화 내보내기")
  7. AutoInput Action: Click ("파일로 저장")
  8. Wait: 3초
  9. Plugin -> Termux:Tasker
     Executable: process_exported_chat.sh
```

#### 방법 C: kakaotalk-chat-exporter (Python)

GitHub에 공개된 kakaotalk-chat-exporter를 활용할 수 있다. 이 도구는 공식 KakaoTalk API가 채팅 내보내기를 지원하지 않아 UI 자동화로 구현한 Python 앱이다.

```bash
# 설치 (Termux 또는 Mac)
git clone https://github.com/jooncco/kakaotalk-chat-exporter.git
cd kakaotalk-chat-exporter
pip install -r requirements.txt
```

### Step 2: 통화/회의 녹음 자동 전사

```python
# ~/scripts/auto_transcribe_pipeline.py
"""
녹음 파일 감시 -> Whisper 전사 -> 결과 저장
"""

import os
import time
import json
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import openai

WATCH_DIR = "/sdcard/Recordings/"  # Termux에서 실행 시
# WATCH_DIR = "./recordings/"  # Mac에서 실행 시
OUTPUT_DIR = os.path.expanduser("~/onlime_data/transcripts/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

class RecordingHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(('.m4a', '.mp3', '.wav', '.ogg', '.aac')):
            print(f"새 녹음 파일 감지: {event.src_path}")
            # 파일 쓰기 완료 대기
            time.sleep(5)
            self.transcribe(event.src_path)

    def transcribe(self, file_path):
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ko",
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        base_name = Path(file_path).stem

        # 전사 결과 저장 (JSON)
        output_json = os.path.join(OUTPUT_DIR, f"{base_name}.json")
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump({
                "source_file": file_path,
                "text": transcript.text,
                "segments": [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in transcript.segments
                ],
                "language": transcript.language
            }, f, ensure_ascii=False, indent=2)

        # 텍스트만 저장
        output_txt = os.path.join(OUTPUT_DIR, f"{base_name}.txt")
        with open(output_txt, 'w', encoding='utf-8') as f:
            f.write(transcript.text)

        print(f"전사 완료: {output_txt}")
        return output_txt

if __name__ == '__main__':
    observer = Observer()
    observer.schedule(RecordingHandler(), WATCH_DIR, recursive=False)
    observer.start()
    print(f"녹음 디렉토리 감시 중: {WATCH_DIR}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
```

### Step 3: Google Calendar 매칭

```python
# ~/scripts/calendar_matcher.py
"""
전사된 텍스트/카카오톡 로그의 시간대를 Google Calendar 이벤트와 매칭
"""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import json
import os

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

def get_calendar_events(date_str):
    """지정 날짜의 Google Calendar 이벤트 조회"""
    creds = Credentials.from_authorized_user_file(
        os.path.expanduser('~/credentials/google_token.json'),
        SCOPES
    )
    service = build('calendar', 'v3', credentials=creds)

    date = datetime.strptime(date_str, '%Y-%m-%d')
    time_min = date.isoformat() + 'Z'
    time_max = (date + timedelta(days=1)).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    return events_result.get('items', [])

def match_recording_to_event(recording_time, events):
    """녹음 시간과 가장 가까운 캘린더 이벤트 매칭"""
    rec_dt = datetime.fromisoformat(recording_time)

    best_match = None
    min_diff = timedelta(hours=24)

    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        event_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))

        diff = abs(rec_dt - event_dt.replace(tzinfo=None))
        if diff < min_diff and diff < timedelta(hours=1):
            min_diff = diff
            best_match = event

    return best_match

def build_daily_report(date_str):
    """일간 보고서 빌드"""
    events = get_calendar_events(date_str)

    # 카카오톡 로그 로드
    kakao_log_file = os.path.expanduser(
        f"~/onlime_data/kakao_logs/kakao_{date_str}.jsonl"
    )
    kakao_messages = []
    if os.path.exists(kakao_log_file):
        with open(kakao_log_file, 'r') as f:
            for line in f:
                kakao_messages.append(json.loads(line))

    # 전사 파일 로드
    transcript_dir = os.path.expanduser("~/onlime_data/transcripts/")
    transcripts = []
    for fname in os.listdir(transcript_dir):
        if fname.startswith(date_str) and fname.endswith('.json'):
            with open(os.path.join(transcript_dir, fname), 'r') as f:
                transcripts.append(json.load(f))

    report = {
        "date": date_str,
        "calendar_events": [
            {
                "title": e.get('summary', '제목 없음'),
                "start": e['start'].get('dateTime', e['start'].get('date')),
                "end": e['end'].get('dateTime', e['end'].get('date')),
                "attendees": [a.get('email') for a in e.get('attendees', [])]
            }
            for e in events
        ],
        "kakao_messages_count": len(kakao_messages),
        "kakao_conversations": kakao_messages,
        "transcripts": transcripts
    }

    return report
```

### Step 4: LLM으로 보고서 생성

```python
# ~/scripts/generate_report.py
"""
수집된 데이터를 LLM에 전달하여 일간/주간 브리핑 보고서 생성
"""

import json
import os
from datetime import datetime
import anthropic  # 또는 openai

def generate_daily_briefing(report_data):
    """일간 브리핑 보고서 생성"""

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    prompt = f"""다음 데이터를 바탕으로 오늘의 일간 브리핑 보고서를 한국어로 작성해주세요.

## 오늘 날짜: {report_data['date']}

## 캘린더 일정:
{json.dumps(report_data['calendar_events'], ensure_ascii=False, indent=2)}

## 카카오톡 메시지 요약 (총 {report_data['kakao_messages_count']}건):
{json.dumps(report_data['kakao_conversations'][:50], ensure_ascii=False, indent=2)}

## 녹음 전사 내용:
{json.dumps([t.get('text', '') for t in report_data['transcripts']], ensure_ascii=False, indent=2)}

---

다음 형식으로 보고서를 작성하세요:

# 일간 브리핑 - {report_data['date']}

## 1. 오늘의 일정 요약
(캘린더 이벤트 기반)

## 2. 주요 커뮤니케이션
(카카오톡 메시지에서 중요 내용 추출)

## 3. 회의/통화 요약
(녹음 전사 기반 핵심 내용)

## 4. 액션 아이템
(위 내용에서 도출된 할 일 목록)

## 5. 내일 주의사항
(캘린더 + 대화 내용 기반 내일 준비사항)
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    report_text = response.content[0].text

    # 보고서 파일 저장
    output_dir = os.path.expanduser("~/onlime_data/reports/")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(
        output_dir,
        f"daily_briefing_{report_data['date']}.md"
    )

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report_text)

    return output_file
```

### Step 5: n8n 워크플로우 (전체 파이프라인 오케스트레이션)

```
[n8n 워크플로우: 일간 보고서 생성 파이프라인]

노드 1: Schedule Trigger
  - 매일 오후 9시 실행

노드 2: Execute Command
  - python3 ~/scripts/calendar_matcher.py --date today
  - 출력: 일간 데이터 JSON

노드 3: IF 노드
  - 조건: 새로운 녹음 파일 존재?
  - Yes -> 노드 4로
  - No -> 노드 5로

노드 4: Execute Command
  - python3 ~/scripts/auto_transcribe_pipeline.py --batch
  - 미전사 파일 일괄 전사

노드 5: Execute Command
  - python3 ~/scripts/generate_report.py --date today
  - LLM 보고서 생성

노드 6: Gmail 노드
  - 생성된 보고서를 이메일로 발송

노드 7: Google Drive 노드
  - 보고서를 Google Drive에 백업
```

### 완전 자동화 Tasker 프로필 모음

```
[프로필 1: 카카오톡 알림 캡처 (24시간)]
Event: Notification (com.kakao.talk)
-> Termux: kakao_capture.sh
-> HTTP POST to n8n webhook

[프로필 2: 새 녹음 파일 감지]
Event: File Modified (/sdcard/Recordings/)
-> Wait 10초 (파일 쓰기 완료 대기)
-> Termux: transcribe_recording.sh
-> Notify: "녹음 전사 완료"

[프로필 3: 매일 저녁 9시 보고서 생성]
Time: 21:00
-> Termux: python3 generate_daily_report.py
-> Join Push: Mac에 보고서 전송
-> Notify: "일간 브리핑 생성 완료"

[프로필 4: WiFi 연결 시 데이터 동기화]
State: WiFi Connected (집 WiFi)
-> Termux: sync_to_mac.sh (rsync 또는 scp)
```

---

## 총평 및 권장 구성

### 초보자용 (설정 30분)
```
Bixby Routines + IFTTT
- 간단한 알림 기반 자동화
- Google Sheets 기록
- 코딩 불필요
```

### 중급자용 (설정 2-3시간)
```
MacroDroid + Join + Google Apps Script
- 알림 캡처 -> 스프레드시트 기록
- 크로스 디바이스 알림 동기화
- 기본 스크립팅
```

### 고급자용 (설정 반나절 ~ 1일) -- 권장
```
Tasker + Termux + n8n + Python
- 알림/파일 실시간 감지
- 온디바이스 Python 스크립트 실행
- 서버사이드 Whisper 전사 + LLM 보고서
- 완전 자동화 파이프라인
```

### 필수 앱/도구 목록 (권장 구성)

| 도구 | 용도 | 설치 출처 | 비용 |
|------|------|-----------|------|
| Tasker | 이벤트 감지/오케스트레이션 | Google Play | $3.49 |
| Termux | Linux/Python 환경 | F-Droid | 무료 |
| Termux:Tasker | 연동 플러그인 | F-Droid | 무료 |
| Termux:API | 디바이스 기능 접근 | F-Droid | 무료 |
| AutoNotification | 고급 알림 처리 | Google Play | 무료/인앱 |
| AutoInput | UI 자동화 | Google Play | 무료/인앱 |
| Join | 크로스 디바이스 통신 | Google Play | ~$5 |
| n8n | 서버사이드 워크플로우 | Docker/npm | 무료(셀프호스팅) |

---

*이 문서는 Onlime 프로젝트의 Android 자동화 파이프라인 구축을 위한 기술 조사 보고서입니다.*
