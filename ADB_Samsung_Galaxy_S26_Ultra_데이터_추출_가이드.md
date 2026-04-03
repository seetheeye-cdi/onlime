# ADB를 통한 Samsung Galaxy S26 Ultra 데이터 추출 완전 가이드

> USB-C 연결 기반 ADB(Android Debug Bridge) 활용 데이터 접근, 백업, 자동화 종합 리서치
> 작성일: 2026-04-02

---

## 목차

1. [ADB 설치 및 USB-C 연결 설정 (Mac)](#1-adb-설치-및-usb-c-연결-설정-mac)
2. [루트 없이 접근 가능한 데이터](#2-루트-없이-접근-가능한-데이터)
3. [adb backup vs adb pull 비교](#3-adb-backup-vs-adb-pull-비교)
4. [앱별 데이터 디렉토리 접근](#4-앱별-데이터-디렉토리-접근)
5. [삼성 전용 ADB 명령어 및 도구](#5-삼성-전용-adb-명령어-및-도구)
6. [scrcpy 및 미러링/제어 도구](#6-scrcpy-및-미러링제어-도구)
7. [Python으로 ADB 자동화 (adbutils)](#7-python으로-adb-자동화-adbutils)
8. [파일 전송 속도 및 제한사항](#8-파일-전송-속도-및-제한사항)
9. [보안 고려사항](#9-보안-고려사항)
10. [Samsung DeX 모드 데이터 접근](#10-samsung-dex-모드-데이터-접근)
11. [Samsung Smart Switch 데이터 내보내기 형식](#11-samsung-smart-switch-데이터-내보내기-형식)
12. [Python/Shell 자동화 스크립트](#12-pythonshell-자동화-스크립트)

---

## 1. ADB 설치 및 USB-C 연결 설정 (Mac)

### 1.1 Galaxy S26 Ultra USB 사양

- **포트**: USB Type-C 3.2 Gen 1
- **데이터 전송 속도**: 최대 5Gbps
- **DisplayPort**: 1.2 지원
- **OTG**: 지원
- **충전**: 60W 유선 충전, Qi2.2 무선 25W

### 1.2 ADB 설치 방법

**방법 A: Homebrew 사용 (권장)**

```bash
# Homebrew 설치 (미설치 시)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Android Platform Tools 설치
brew install android-platform-tools

# 설치 확인
adb version
# 출력 예: Android Debug Bridge version 1.0.41
```

**방법 B: Google 공식 다운로드**

```bash
# SDK Platform Tools 직접 다운로드
curl -O https://dl.google.com/android/repository/platform-tools-latest-darwin.zip

# 압축 해제
unzip platform-tools-latest-darwin.zip

# PATH에 추가 (~/.zshrc 또는 ~/.bash_profile)
echo 'export PATH="$HOME/platform-tools:$PATH"' >> ~/.zshrc
source ~/.zshrc

# 확인
adb version
```

### 1.3 Galaxy S26 Ultra에서 개발자 모드 활성화

```
1. 설정(Settings) 앱 열기
2. 휴대전화 정보(About Phone) 진입
3. 소프트웨어 정보(Software Information) 선택
4. "빌드 번호(Build Number)"를 7회 연속 탭
   → "개발자 모드가 활성화되었습니다" 메시지 확인
5. 설정 > 개발자 옵션(Developer Options) 진입
6. "USB 디버깅(USB Debugging)" 토글 ON
7. (선택) "무선 디버깅(Wireless Debugging)" 토글 ON
```

### 1.4 USB-C 연결 및 인증

```bash
# 1. USB-C 케이블로 Mac과 Galaxy S26 Ultra 연결
#    주의: 충전 전용 케이블이 아닌 "데이터 전송 가능" 케이블 사용 필수

# 2. 폰 화면에서 "USB 디버깅을 허용하시겠습니까?" 대화상자가 나타남
#    → "이 컴퓨터에서 항상 허용" 체크 후 "허용" 터치

# 3. 연결 확인
adb devices
# 출력 예:
# List of devices attached
# RFXXXXXXXX    device

# "unauthorized"로 표시되면 폰 화면의 인증 대화상자를 확인할 것
# "offline"이면 USB 케이블 재연결

# 4. 장치 상세 정보 확인
adb devices -l
# 출력 예:
# RFXXXXXXXX    device usb:336855040X product:e2sxxx model:SM_S938B device:e2s
```

### 1.5 ADB 서버 관리

```bash
# ADB 서버 시작
adb start-server

# ADB 서버 종료 (문제 발생 시)
adb kill-server

# 서버 재시작
adb kill-server && adb start-server

# 특정 디바이스 대상 명령 (여러 디바이스 연결 시)
adb -s RFXXXXXXXX shell
```

---

## 2. 루트 없이 접근 가능한 데이터

### 2.1 접근 가능한 공개 디렉토리

Galaxy S26 Ultra에서 루트 없이 ADB로 접근 가능한 경로들:

```bash
# 내부 저장소 루트 (모두 동일한 위치를 가리킴)
# /sdcard/ = /storage/emulated/0/ = /data/media/0/

# 사진/동영상
adb pull /sdcard/DCIM/Camera/ ./backup/camera/
adb pull /sdcard/Pictures/ ./backup/pictures/

# 다운로드한 파일
adb pull /sdcard/Download/ ./backup/downloads/

# 문서
adb pull /sdcard/Documents/ ./backup/documents/

# 음악
adb pull /sdcard/Music/ ./backup/music/

# 동영상
adb pull /sdcard/Movies/ ./backup/movies/

# 카카오톡 미디어 (외부 저장소 부분)
adb pull /sdcard/Android/media/com.kakao.talk/ ./backup/kakaotalk_media/

# 녹음 파일
adb pull /sdcard/Recordings/ ./backup/recordings/

# 스크린샷
adb pull /sdcard/DCIM/Screenshots/ ./backup/screenshots/
# 또는
adb pull /sdcard/Pictures/Screenshots/ ./backup/screenshots/

# 전체 내부 저장소 디렉토리 목록 보기
adb shell ls -la /sdcard/
```

### 2.2 접근 가능한 시스템 정보 (dumpsys)

```bash
# 기기 정보
adb shell getprop ro.product.model          # 모델명: SM-S938B
adb shell getprop ro.build.version.release   # Android 버전
adb shell getprop ro.build.version.sdk       # SDK 버전
adb shell getprop ro.serialno                # 시리얼 번호

# 배터리 상태
adb shell dumpsys battery
# 출력: 충전 상태, 배터리 레벨, 전압, 온도 등

# Wi-Fi 정보
adb shell dumpsys wifi | head -50

# 설치된 앱 목록
adb shell pm list packages                    # 전체 앱
adb shell pm list packages -s                 # 시스템 앱만
adb shell pm list packages -3                 # 서드파티 앱만
adb shell pm list packages | grep samsung     # 삼성 앱만
adb shell pm list packages | grep kakao       # 카카오 관련 앱

# 앱 상세 정보
adb shell dumpsys package com.kakao.talk

# 실행 중인 프로세스
adb shell ps

# 메모리 사용량
adb shell dumpsys meminfo

# 저장 공간
adb shell df -h

# 화면 해상도
adb shell wm size
adb shell wm density
```

### 2.3 Content Provider를 통한 데이터 접근

```bash
# 연락처 조회
adb shell content query --uri content://com.android.contacts/contacts

# 상세 연락처 (이름, 번호 등)
adb shell content query --uri content://com.android.contacts/raw_contacts

# 통화 기록 조회
adb shell content query --uri content://call_log/calls

# SMS 메시지 조회
adb shell content query --uri content://sms/

# 수신 SMS만
adb shell content query --uri content://sms/inbox

# 발신 SMS만
adb shell content query --uri content://sms/sent

# 캘린더 이벤트
adb shell content query --uri content://com.android.calendar/events

# 미디어 파일 목록 (이미지)
adb shell content query --uri content://media/external/images/media

# 미디어 파일 목록 (비디오)
adb shell content query --uri content://media/external/video/media

# 특정 컬럼만 조회 (예: SMS의 주소와 본문)
adb shell content query --uri content://sms/ --projection "address:body:date"
```

**주의**: Android 11+ 이후 Google의 개인정보 보호 정책 강화로, 통화 기록과 SMS 접근은 기본 전화/메시지 앱 핸들러에 따라 제한될 수 있음.

### 2.4 접근 불가능한 디렉토리 (루트 필요)

```
/data/data/          → 앱 내부 데이터 (DB, SharedPreferences 등)
/data/system/        → 시스템 설정, 잠금화면 정보
/data/app/           → 설치된 APK 파일
/data/user/          → 사용자별 데이터
/system/             → OS 시스템 파일
```

---

## 3. adb backup vs adb pull 비교

### 3.1 `adb backup` 방식

```bash
# 전체 백업 (앱 + 공유 저장소)
adb backup -apk -shared -all -f full_backup.ab

# 특정 앱만 백업
adb backup -apk -f kakao_backup.ab com.kakao.talk

# 시스템 앱 포함 전체 백업
adb backup -apk -shared -all -system -f full_system_backup.ab

# 앱 데이터만 (APK 제외)
adb backup -noapk -shared -all -f data_only_backup.ab
```

**백업 파일 추출**:

```bash
# .ab 파일을 tar로 변환 (android-backup-extractor 사용)
# Java 필요: https://github.com/nelenkov/android-backup-extractor
java -jar abe.jar unpack full_backup.ab full_backup.tar

# tar 압축 해제
tar xvf full_backup.tar

# 또는 dd + openssl로 직접 변환 (암호 미설정 시)
dd if=full_backup.ab bs=24 skip=1 | python3 -c "import zlib,sys; sys.stdout.buffer.write(zlib.decompress(sys.stdin.buffer.read()))" > full_backup.tar
```

**adb backup의 한계점**:

| 항목 | 상세 |
|------|------|
| **Deprecated** | Google이 공식적으로 deprecated 선언, 향후 버전에서 제거 가능 |
| **Android 12+ 제한** | API 31+ 타겟 앱은 기본적으로 백업 데이터에서 제외 |
| **사용자 확인 필요** | 백업 시 폰 화면에서 수동으로 "백업" 버튼 터치 필요 |
| **속도** | 대용량 데이터의 경우 매우 느림 |
| **앱 호환성** | `android:allowBackup="false"`인 앱은 백업 불가 |
| **암호화** | 비밀번호 설정 시 AES-256으로 암호화되어 추출 복잡 |

### 3.2 `adb pull` 방식

```bash
# 단일 파일 가져오기
adb pull /sdcard/DCIM/Camera/20260401_photo.jpg ./

# 폴더 전체 가져오기 (재귀적)
adb pull /sdcard/DCIM/ ./DCIM_backup/

# 진행 상황 표시
adb pull -a /sdcard/Download/ ./downloads/   # -a: 타임스탬프 보존

# 전체 내부 저장소 백업
adb pull /sdcard/ ./phone_backup/
```

**adb pull의 장단점**:

| 장점 | 단점 |
|------|------|
| 직접적이고 빠름 | /data/data/ 접근 불가 (루트 없이) |
| 사용자 확인 불필요 | Content Provider 데이터 직접 접근 불가 |
| 특정 파일/폴더 선택 가능 | 앱 내부 DB 접근 불가 |
| 스크립트 자동화 용이 | 앱 설정/캐시 백업 불가 |
| deprecated 아님 | |

### 3.3 권장 전략: 하이브리드 접근

```bash
# 1단계: adb pull로 공개 파일 추출 (빠르고 안정적)
adb pull /sdcard/ ./backup/storage/

# 2단계: content provider로 연락처/SMS/통화기록 추출
adb shell content query --uri content://sms/ > ./backup/sms_dump.txt
adb shell content query --uri content://call_log/calls > ./backup/call_log_dump.txt
adb shell content query --uri content://com.android.contacts/contacts > ./backup/contacts_dump.txt

# 3단계: dumpsys로 시스템 정보 수집
adb shell dumpsys battery > ./backup/system/battery_info.txt
adb shell dumpsys wifi > ./backup/system/wifi_info.txt
adb shell pm list packages -3 > ./backup/system/installed_apps.txt

# 4단계: (선택) adb backup으로 앱 데이터 백업
adb backup -apk -noshared -f ./backup/apps_backup.ab com.kakao.talk
```

---

## 4. 앱별 데이터 디렉토리 접근

### 4.1 디렉토리 구조

```
/data/data/<패키지명>/           ← 루트 필요 (접근 불가)
    ├── databases/              ← SQLite DB 파일
    ├── shared_prefs/           ← XML 설정 파일
    ├── cache/                  ← 캐시 데이터
    ├── files/                  ← 앱 내부 파일
    └── lib/                    ← 네이티브 라이브러리

/sdcard/Android/data/<패키지명>/ ← Android 11+ 제한적 접근
/sdcard/Android/media/<패키지명>/ ← 미디어 파일 (접근 가능할 수 있음)
```

### 4.2 루트 없이 앱 데이터 접근하는 우회 방법

**방법 1: adb backup + 추출**

```bash
# 특정 앱 백업
adb backup -noapk -f app_data.ab com.example.app

# 폰에서 "백업" 터치 (비밀번호 미설정 권장)

# .ab 파일에서 데이터 추출
java -jar abe.jar unpack app_data.ab app_data.tar
tar xvf app_data.tar
# → apps/com.example.app/ 디렉토리에 데이터 추출됨
```

**방법 2: run-as 명령 (디버그 가능 앱만)**

```bash
# 디버그 가능한 앱의 경우에만 작동
adb shell run-as com.example.app ls files/
adb shell run-as com.example.app cat databases/data.db > /sdcard/data.db
adb pull /sdcard/data.db ./

# 주의: 대부분의 릴리스 앱은 디버그 불가능하므로 작동하지 않음
```

**방법 3: Content Provider 쿼리**

```bash
# 앱이 Content Provider를 노출한 경우
adb shell content query --uri content://com.example.app.provider/data
```

**방법 4: 외부 저장소 미디어 접근**

```bash
# 카카오톡 미디어 파일
adb pull /sdcard/Android/media/com.kakao.talk/ ./kakao_media/

# 텔레그램 미디어
adb pull /sdcard/Android/media/org.telegram.messenger/ ./telegram_media/

# WhatsApp 미디어
adb pull /sdcard/Android/media/com.whatsapp/ ./whatsapp_media/
```

---

## 5. 삼성 전용 ADB 명령어 및 도구

### 5.1 삼성 특화 명령어

```bash
# 삼성 펌웨어 정보
adb shell getprop ro.build.display.id
adb shell getprop ro.build.version.oneui    # One UI 버전

# 삼성 녹스(Knox) 버전
adb shell getprop ro.boot.warranty_bit
adb shell getprop ro.knox.enhance.zygote.aslr

# CSC (국가/통신사 코드)
adb shell getprop ro.csc.sales_code         # 예: SKT, KTC, LUC

# 삼성 앱 목록
adb shell pm list packages | grep samsung
adb shell pm list packages | grep sec       # SEC (Samsung Electronics Co.)

# 삼성 갤러리 DB 위치 확인
adb shell content query --uri content://media/external/images/media --projection "_id:_display_name:_data:date_added" --sort "date_added DESC"

# 삼성 메모 (Samsung Notes) 외부 파일
adb pull /sdcard/Android/media/com.samsung.android.app.notes/ ./samsung_notes/

# 삼성 캘린더 데이터
adb shell content query --uri content://com.android.calendar/events

# 삼성 건강 (Samsung Health) 데이터 내보내기
# Samsung Health 앱 > 설정 > 데이터 다운로드 후 pull
adb pull /sdcard/Download/samsung_health_data/ ./samsung_health/

# S펜 관련 데이터
adb pull /sdcard/Android/media/com.samsung.android.app.notes/ ./spen_notes/
```

### 5.2 삼성 블로트웨어 관리

```bash
# 비활성화 가능한 삼성 앱 확인
adb shell pm list packages -d    # disabled packages

# 특정 삼성 앱 비활성화 (삭제가 아닌 비활성화)
adb shell pm disable-user --user 0 com.samsung.android.app.spage  # 삼성 프리(Bixby)

# 비활성화한 앱 재활성화
adb shell pm enable com.samsung.android.app.spage

# 주의: 시스템 앱 비활성화 시 기기 불안정 가능성
```

### 5.3 삼성 진단 정보

```bash
# 삼성 서비스 모드 접근 (전화 앱에서)
# *#0*#    → 하드웨어 테스트
# *#1234#  → 펌웨어 버전
# *#0228#  → 배터리 상태

# ADB로 삼성 진단 정보
adb shell dumpsys SamsungKeyProvisioningService
adb shell dumpsys SamsungAccountService
adb shell settings get system samsung_pref_index
```

---

## 6. scrcpy 및 미러링/제어 도구

### 6.1 scrcpy 설치 및 사용

scrcpy는 무료 오픈소스 도구로, ADB를 통해 Android 화면을 Mac에 미러링하고 제어할 수 있다.

```bash
# 설치 (Mac)
brew install scrcpy

# 기본 실행 (USB 연결 상태)
scrcpy

# 고화질 실행
scrcpy --max-size 1920 --bit-rate 8M

# 화면 녹화 동시 진행
scrcpy --record screen_recording.mp4

# 오디오 포함 녹화 (Android 11+)
scrcpy --record-format=mp4 --record=output.mp4 --audio-codec=aac

# 창 타이틀 지정
scrcpy --window-title "Galaxy S26 Ultra"

# 화면만 보기 (제어 불가)
scrcpy --no-control

# 화면 끈 상태에서 미러링 (배터리 절약)
scrcpy --turn-screen-off

# 무선 연결로 전환
adb tcpip 5555
adb connect 192.168.1.XXX:5555
scrcpy --tcpip=192.168.1.XXX:5555

# 특정 디스플레이 미러링
scrcpy --display 0

# 클립보드 동기화 (Mac ↔ Phone)
scrcpy --no-clipboard-autosync   # 자동 동기화 비활성화

# 파일 드래그 앤 드롭으로 전송
# scrcpy 창에 파일을 드래그하면 /sdcard/Download/에 자동 전송
```

**scrcpy 주요 단축키**:

| 단축키 | 기능 |
|--------|------|
| Cmd+H | 홈 버튼 |
| Cmd+B | 뒤로가기 |
| Cmd+S | 앱 전환 |
| Cmd+M | 메뉴 |
| Cmd+↑ | 볼륨 업 |
| Cmd+↓ | 볼륨 다운 |
| Cmd+P | 전원 |
| Cmd+O | 화면 끄기 |
| Cmd+N | 알림 패널 열기 |
| Cmd+Shift+N | 알림 패널 닫기 |
| Cmd+R | 90도 회전 |
| Cmd+F | 전체화면 |

### 6.2 기타 미러링/제어 도구

| 도구 | 특징 | 설치 |
|------|------|------|
| **scrcpy** | 오픈소스, 무료, 저지연 (35-70ms) | `brew install scrcpy` |
| **Vysor** | Chrome 확장, GUI 친화적 | vysor.io |
| **AirDroid** | 무선, 웹 기반, 파일 관리 | airdroid.com |
| **Samsung Flow** | 삼성 공식, 알림 동기화 | 삼성 스토어 |
| **QtScrcpy** | scrcpy GUI 래퍼, 키 매핑 | GitHub |

---

## 7. Python으로 ADB 자동화 (adbutils)

### 7.1 라이브러리 설치

```bash
# adbutils (권장 - 활발한 유지보수, v2.12.0+)
pip install adbutils

# pure-python-adb (대안)
pip install pure-python-adb

# ppadb (deprecated이지만 참고용)
pip install ppadb
```

### 7.2 adbutils 기본 사용법

```python
#!/usr/bin/env python3
"""adbutils를 활용한 Galaxy S26 Ultra 기본 연결 및 정보 조회"""

from adbutils import adb

# ========================================
# 1. 디바이스 연결 확인
# ========================================
devices = adb.device_list()
print(f"연결된 디바이스 수: {len(devices)}")

for d in devices:
    print(f"  시리얼: {d.serial}")
    print(f"  모델: {d.prop.model}")
    print(f"  Android 버전: {d.prop.get('ro.build.version.release')}")

# 첫 번째 디바이스 선택
d = adb.device()

# ========================================
# 2. 기기 정보 조회
# ========================================
print(f"모델명: {d.shell('getprop ro.product.model')}")
print(f"시리얼: {d.shell('getprop ro.serialno')}")
print(f"Android 버전: {d.shell('getprop ro.build.version.release')}")
print(f"One UI 버전: {d.shell('getprop ro.build.version.oneui')}")
print(f"배터리: {d.shell('dumpsys battery | grep level')}")

# ========================================
# 3. 설치된 앱 목록
# ========================================
packages = d.shell("pm list packages -3").strip().split("\n")
print(f"\n설치된 서드파티 앱 수: {len(packages)}")
for pkg in packages[:10]:  # 처음 10개만 출력
    print(f"  {pkg}")

# ========================================
# 4. 저장소 사용량
# ========================================
storage = d.shell("df -h /sdcard")
print(f"\n저장소 정보:\n{storage}")
```

### 7.3 파일 전송 자동화

```python
#!/usr/bin/env python3
"""adbutils를 활용한 파일 동기화 및 백업 자동화"""

import os
import time
from pathlib import Path
from adbutils import adb

d = adb.device()

# ========================================
# 파일 Pull (디바이스 → Mac)
# ========================================
def pull_directory(remote_path: str, local_path: str):
    """원격 디렉토리의 파일을 로컬로 복사"""
    local = Path(local_path)
    local.mkdir(parents=True, exist_ok=True)

    # 원격 디렉토리 파일 목록 가져오기
    result = d.shell(f"find {remote_path} -type f 2>/dev/null")
    files = [f.strip() for f in result.strip().split("\n") if f.strip()]

    print(f"총 {len(files)}개 파일 발견: {remote_path}")

    for i, remote_file in enumerate(files, 1):
        # 상대 경로 계산
        rel_path = remote_file.replace(remote_path, "").lstrip("/")
        local_file = local / rel_path

        # 로컬 디렉토리 생성
        local_file.parent.mkdir(parents=True, exist_ok=True)

        # 파일 복사
        try:
            d.sync.pull(remote_file, str(local_file))
            print(f"  [{i}/{len(files)}] {rel_path}")
        except Exception as e:
            print(f"  [오류] {rel_path}: {e}")

    print(f"완료: {local_path}")


# ========================================
# 파일 Push (Mac → 디바이스)
# ========================================
def push_file(local_path: str, remote_path: str):
    """로컬 파일을 디바이스로 전송"""
    d.sync.push(local_path, remote_path)
    print(f"전송 완료: {local_path} → {remote_path}")


# ========================================
# 사용 예시
# ========================================
if __name__ == "__main__":
    backup_dir = f"./galaxy_backup_{time.strftime('%Y%m%d_%H%M%S')}"

    # 사진 백업
    pull_directory("/sdcard/DCIM/Camera/", f"{backup_dir}/Camera/")

    # 다운로드 백업
    pull_directory("/sdcard/Download/", f"{backup_dir}/Download/")

    # 문서 백업
    pull_directory("/sdcard/Documents/", f"{backup_dir}/Documents/")
```

### 7.4 Content Provider 데이터 추출

```python
#!/usr/bin/env python3
"""Content Provider를 통한 연락처, SMS, 통화기록 추출"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from adbutils import adb

d = adb.device()
OUTPUT_DIR = Path("./extracted_data")
OUTPUT_DIR.mkdir(exist_ok=True)


def parse_content_query(raw_output: str) -> list[dict]:
    """adb shell content query 결과를 파싱하여 딕셔너리 리스트로 변환"""
    rows = []
    for line in raw_output.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("Row:"):
            continue
        # "Row: N key1=value1, key2=value2, ..." 형태 파싱
        match = re.match(r"Row:\s*\d+\s*(.*)", line)
        if match:
            pairs = match.group(1)
        else:
            pairs = line

        row = {}
        # key=value 쌍 파싱 (값에 쉼표가 포함될 수 있으므로 주의)
        for pair in re.findall(r"(\w+)=(.*?)(?:,\s*(?=\w+=)|$)", pairs):
            key, value = pair
            row[key] = value.strip()
        if row:
            rows.append(row)
    return rows


def extract_contacts():
    """연락처 추출"""
    print("연락처 추출 중...")
    raw = d.shell("content query --uri content://com.android.contacts/contacts "
                   "--projection display_name:has_phone_number:contact_last_updated_timestamp")
    contacts = parse_content_query(raw)

    output_file = OUTPUT_DIR / "contacts.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)
    print(f"  → {len(contacts)}개 연락처 저장: {output_file}")
    return contacts


def extract_sms():
    """SMS 메시지 추출"""
    print("SMS 추출 중...")
    raw = d.shell("content query --uri content://sms/ "
                   "--projection address:body:date:type:read")
    messages = parse_content_query(raw)

    # 날짜 변환
    for msg in messages:
        if "date" in msg:
            try:
                ts = int(msg["date"]) / 1000
                msg["date_readable"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                pass
        # type: 1=수신, 2=발신
        msg["direction"] = "수신" if msg.get("type") == "1" else "발신"

    output_file = OUTPUT_DIR / "sms_messages.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    print(f"  → {len(messages)}개 메시지 저장: {output_file}")
    return messages


def extract_call_log():
    """통화 기록 추출"""
    print("통화 기록 추출 중...")
    raw = d.shell("content query --uri content://call_log/calls "
                   "--projection number:date:duration:type:name")
    calls = parse_content_query(raw)

    # 날짜 변환 및 통화 유형 매핑
    type_map = {"1": "수신", "2": "발신", "3": "부재중", "5": "거절"}
    for call in calls:
        if "date" in call:
            try:
                ts = int(call["date"]) / 1000
                call["date_readable"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError):
                pass
        call["call_type"] = type_map.get(call.get("type", ""), "기타")

    output_file = OUTPUT_DIR / "call_log.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(calls, f, ensure_ascii=False, indent=2)
    print(f"  → {len(calls)}개 통화 기록 저장: {output_file}")
    return calls


if __name__ == "__main__":
    extract_contacts()
    extract_sms()
    extract_call_log()
    print(f"\n전체 추출 완료: {OUTPUT_DIR.absolute()}")
```

### 7.5 스크린샷 및 화면 녹화

```python
#!/usr/bin/env python3
"""스크린샷 및 화면 녹화 자동화"""

import time
from adbutils import adb

d = adb.device()

# 스크린샷 캡처
def take_screenshot(filename: str = None):
    """스크린샷을 찍어 로컬에 저장"""
    if not filename:
        filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"

    # 방법 1: adbutils 내장 기능
    pilimg = d.screenshot()
    pilimg.save(filename)
    print(f"스크린샷 저장: {filename}")

    # 방법 2: shell 명령
    # d.shell("screencap -p /sdcard/screen.png")
    # d.sync.pull("/sdcard/screen.png", filename)
    # d.shell("rm /sdcard/screen.png")


# 화면 녹화
def record_screen(duration: int = 30, filename: str = "recording.mp4"):
    """화면을 녹화하여 로컬에 저장"""
    remote_path = "/sdcard/screen_record.mp4"

    print(f"녹화 시작 ({duration}초)...")
    d.shell(f"screenrecord --time-limit {duration} {remote_path}")

    d.sync.pull(remote_path, filename)
    d.shell(f"rm {remote_path}")
    print(f"녹화 저장: {filename}")


if __name__ == "__main__":
    take_screenshot()
```

---

## 8. 파일 전송 속도 및 제한사항

### 8.1 전송 속도 벤치마크

| 전송 방법 | 예상 속도 | 비고 |
|-----------|-----------|------|
| **ADB pull (USB 3.2)** | 30-80 MB/s | 파일 크기/개수에 따라 편차 |
| **ADB pull (USB 2.0)** | 10-25 MB/s | 저품질 케이블 주의 |
| **MTP 파일 전송** | 5-15 MB/s | OS 파일 관리자 기본 |
| **ADB pull (Wi-Fi)** | 5-20 MB/s | 네트워크 상태 의존 |
| **adb push/pull + tar** | 50-100 MB/s | 소용량 다수 파일 시 효과적 |

### 8.2 전송 최적화 기법

```bash
# 방법 1: tar로 압축 후 전송 (소용량 파일 다수일 때 효과적)
# 디바이스에서 tar 생성 → stdout으로 전송 → 로컬에서 압축 해제
adb exec-out tar -cf - /sdcard/DCIM/Camera/ | tar -xf - -C ./backup/

# 방법 2: gzip 압축 병행 (느린 연결 시)
adb exec-out tar -czf - /sdcard/DCIM/Camera/ | tar -xzf - -C ./backup/

# 방법 3: 특정 확장자만 필터링
adb exec-out find /sdcard/DCIM/ -name "*.jpg" -o -name "*.mp4" | \
  while read f; do adb pull "$f" ./backup/; done

# 방법 4: 증분 백업 (변경된 파일만)
# 마지막 백업 이후 변경된 파일만 전송
adb shell find /sdcard/DCIM/ -newer /sdcard/.last_backup -type f | \
  while read f; do adb pull "$f" ./backup/; done
adb shell touch /sdcard/.last_backup
```

### 8.3 전송 제한사항

- **단일 파일 크기 제한**: 일반적으로 4GB 제한 없음 (USB 3.x)
- **동시 연결**: ADB는 단일 스트림만 지원 (병렬 전송 불가)
- **타임아웃**: 대용량 파일 전송 시 타임아웃 발생 가능
  ```bash
  # 타임아웃 방지: 환경변수 설정
  export ADB_TRACE=all
  # 또는 장시간 작업 시 keep-alive
  ```
- **USB 케이블 품질**: 데이터 핀이 있는 고품질 USB-C 케이블 필수
- **파일 이름**: 한글, 특수문자가 포함된 파일명은 인코딩 문제 발생 가능

---

## 9. 보안 고려사항

### 9.1 개발자 모드 및 USB 디버깅 위험

| 위험 요소 | 설명 |
|-----------|------|
| **무단 앱 설치** | USB 디버깅 활성화 시 비공식 앱 사이드로딩 가능 |
| **데이터 유출** | ADB 연결로 기기 로그, 파일에 완전 접근 가능 |
| **화면 잠금 우회** | ADB를 통해 잠금 화면 없이 파일 접근 가능한 경우 있음 |
| **원격 ADB** | tcpip 모드 활성화 시 네트워크 상 다른 기기에서 접근 가능 |

### 9.2 Samsung Knox 보안

```
Knox 컨테이너가 설정된 기기:
- USB 디버깅이 기본적으로 비활성화
- Knox EMM(Enterprise Mobile Management)으로 ADB 차단 가능
- Android 11+에서는 Knox Guard가 개발자 옵션 메뉴 자체를 차단 가능
```

### 9.3 보안 권장사항

```bash
# 작업 완료 후 반드시 USB 디버깅 비활성화
adb shell settings put global adb_enabled 0

# 또는 개발자 옵션 자체를 비활성화
# 설정 > 개발자 옵션 > 토글 OFF

# RSA 키 인증 철회 (모든 컴퓨터 인증 해제)
# 설정 > 개발자 옵션 > "USB 디버깅 승인 취소"

# Wi-Fi ADB 비활성화 (사용 후)
adb usb   # USB 모드로 복귀

# ADB 서버 종료
adb kill-server
```

### 9.4 데이터 보안 체크리스트

```
□ 작업 전: USB 디버깅 활성화
□ 작업 전: RSA 키 인증 (신뢰할 수 있는 컴퓨터만)
□ 작업 중: 공공 Wi-Fi에서 무선 ADB 사용 금지
□ 작업 후: USB 디버깅 비활성화
□ 작업 후: RSA 키 인증 취소
□ 백업 데이터: 로컬 디스크 암호화 저장
□ 전송 완료: ADB 서버 종료
```

---

## 10. Samsung DeX 모드 데이터 접근

### 10.1 DeX 연결 방법

```
방법 1: USB-C 케이블로 Mac/모니터에 직접 연결
방법 2: HDMI 어댑터/케이블 사용
방법 3: 무선 DeX (Miracast/Smart View 지원 TV)
방법 4: Samsung DeX for PC 앱 (Windows/Mac)
```

### 10.2 DeX에서의 파일 접근

```
DeX 모드에서 가능한 작업:
- 내 파일(My Files) 앱으로 전체 내부 저장소 탐색
- 드래그 앤 드롭으로 PC ↔ 폰 파일 전송
- 갤러리 앱에서 사진/동영상 직접 복사
- USB 메모리를 통한 OTG 파일 전송
- Samsung Notes, 캘린더 등 앱 데이터 직접 접근

DeX의 한계:
- /data/data/ 등 시스템 영역 접근 불가 (ADB와 동일)
- Smart Switch는 DeX 모드에서 작동하지 않음
- 파일 관리 프로토콜이 다르기 때문
- ADB보다 대량 파일 전송 속도가 느릴 수 있음
```

### 10.3 DeX + ADB 동시 활용

```bash
# DeX 모드에서도 ADB 사용 가능
# USB-C로 DeX 연결 후 같은 케이블로 ADB 접근

# DeX 모드 확인
adb shell settings get global force_desktop_mode_on_external_displays

# DeX 모드에서 특정 앱 실행
adb shell am start -n com.sec.android.app.myfiles/.common.MainActivity
```

---

## 11. Samsung Smart Switch 데이터 내보내기 형식

### 11.1 백업 파일 위치

```
Windows: C:\Users\{사용자}\Documents\Samsung\SmartSwitch\backup\{모델}\{폰번호}\
Mac: ~/Documents/Samsung/SmartSwitch/backup/{모델}/{폰번호}/

디렉토리 구조:
backup/
├── device_info.xml          ← 기기 정보 (모델, IMEI, OS 버전)
├── BackupType.xml           ← 백업 유형 정보
├── Contacts/
│   └── contacts.spbm        ← 삼성 독점 연락처 형식
├── Messages/
│   └── messages.bk          ← SMS/MMS 메시지
├── CallLog/
│   └── calllogs.bk          ← 통화 기록
├── Calendar/
│   └── calendar.bk          ← 캘린더 데이터
├── Apps/
│   └── *.apk                ← 설치된 앱 APK
├── Media/
│   ├── images/              ← 사진
│   ├── videos/              ← 동영상
│   └── audio/               ← 음악/녹음
├── Documents/
│   └── ...                  ← 문서 파일
└── Settings/
    └── settings.bk          ← 기기 설정
```

### 11.2 파일 형식 상세

| 확장자 | 형식 | 설명 |
|--------|------|------|
| `.spbm` | 삼성 독점 | 연락처 백업 (SPB Manager) |
| `.bk` | 삼성 독점 | 일반 백업 데이터 |
| `.json` | JSON | PC/Mac 백업 시 설정 파일 |
| `.xml` | XML | 기기 정보, 메타데이터 |

### 11.3 Smart Switch 백업에서 데이터 추출

```bash
# .spbm 파일에서 연락처 추출 (vCard 형식으로 변환)
# 온라인 도구: https://convert.guru/spbm-converter

# Smart Switch 백업은 독점 형식이라 직접 파싱이 어려움
# 권장: ADB content provider 방식이 더 유연함

# 대안: 연락처를 VCF로 내보내기 (폰에서 직접)
# 연락처 앱 > 메뉴 > 연락처 관리 > 연락처 가져오기/내보내기 > 내보내기
# → /sdcard/Download/Contacts.vcf 생성
adb pull /sdcard/Download/Contacts.vcf ./
```

---

## 12. Python/Shell 자동화 스크립트

### 12.1 종합 백업 Shell 스크립트

```bash
#!/bin/bash
# ============================================================
# Samsung Galaxy S26 Ultra 종합 ADB 백업 스크립트
# 사용법: chmod +x galaxy_backup.sh && ./galaxy_backup.sh
# ============================================================

set -euo pipefail

# ============ 설정 ============
BACKUP_ROOT="$HOME/GalaxyBackup"
DATE=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="${BACKUP_ROOT}/${DATE}"
LOG_FILE="${BACKUP_DIR}/backup.log"

# 색상 코드
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ============ 함수 ============
log() {
    local msg="[$(date '+%H:%M:%S')] $1"
    echo -e "${GREEN}${msg}${NC}"
    echo "$msg" >> "$LOG_FILE"
}

error() {
    local msg="[$(date '+%H:%M:%S')] 오류: $1"
    echo -e "${RED}${msg}${NC}"
    echo "$msg" >> "$LOG_FILE"
}

warn() {
    local msg="[$(date '+%H:%M:%S')] 주의: $1"
    echo -e "${YELLOW}${msg}${NC}"
    echo "$msg" >> "$LOG_FILE"
}

check_device() {
    local device_count
    device_count=$(adb devices | grep -c "device$" || true)
    if [ "$device_count" -eq 0 ]; then
        error "연결된 디바이스가 없습니다."
        error "1. USB-C 케이블 연결 확인"
        error "2. USB 디버깅 활성화 확인"
        error "3. RSA 키 인증 확인"
        exit 1
    fi
    log "디바이스 감지됨 (${device_count}대)"
}

get_device_info() {
    local info_dir="${BACKUP_DIR}/device_info"
    mkdir -p "$info_dir"

    log "기기 정보 수집 중..."
    adb shell getprop ro.product.model > "${info_dir}/model.txt"
    adb shell getprop ro.build.version.release > "${info_dir}/android_version.txt"
    adb shell getprop ro.serialno > "${info_dir}/serial.txt"
    adb shell dumpsys battery > "${info_dir}/battery.txt"
    adb shell df -h > "${info_dir}/storage.txt"
    adb shell pm list packages -3 > "${info_dir}/installed_apps.txt"
    adb shell settings list global > "${info_dir}/global_settings.txt"
    adb shell settings list system > "${info_dir}/system_settings.txt"

    local model=$(cat "${info_dir}/model.txt")
    local version=$(cat "${info_dir}/android_version.txt")
    log "기기: ${model} (Android ${version})"
}

backup_media() {
    log "=== 미디어 파일 백업 시작 ==="
    local media_dir="${BACKUP_DIR}/media"
    mkdir -p "$media_dir"

    # 카메라 사진/동영상
    log "카메라 파일 백업 중..."
    adb pull /sdcard/DCIM/Camera/ "${media_dir}/Camera/" 2>> "$LOG_FILE" || warn "Camera 폴더 없음"

    # 스크린샷
    log "스크린샷 백업 중..."
    adb pull /sdcard/DCIM/Screenshots/ "${media_dir}/Screenshots/" 2>> "$LOG_FILE" || \
    adb pull /sdcard/Pictures/Screenshots/ "${media_dir}/Screenshots/" 2>> "$LOG_FILE" || warn "Screenshots 폴더 없음"

    # 사진
    log "Pictures 백업 중..."
    adb pull /sdcard/Pictures/ "${media_dir}/Pictures/" 2>> "$LOG_FILE" || warn "Pictures 폴더 없음"

    # 동영상
    log "Movies 백업 중..."
    adb pull /sdcard/Movies/ "${media_dir}/Movies/" 2>> "$LOG_FILE" || warn "Movies 폴더 없음"

    # 음악
    log "Music 백업 중..."
    adb pull /sdcard/Music/ "${media_dir}/Music/" 2>> "$LOG_FILE" || warn "Music 폴더 없음"

    # 녹음
    log "Recordings 백업 중..."
    adb pull /sdcard/Recordings/ "${media_dir}/Recordings/" 2>> "$LOG_FILE" || warn "Recordings 폴더 없음"

    log "=== 미디어 파일 백업 완료 ==="
}

backup_documents() {
    log "=== 문서 백업 시작 ==="
    local docs_dir="${BACKUP_DIR}/documents"
    mkdir -p "$docs_dir"

    adb pull /sdcard/Documents/ "${docs_dir}/Documents/" 2>> "$LOG_FILE" || warn "Documents 폴더 없음"
    adb pull /sdcard/Download/ "${docs_dir}/Download/" 2>> "$LOG_FILE" || warn "Download 폴더 없음"

    log "=== 문서 백업 완료 ==="
}

backup_messenger_media() {
    log "=== 메신저 미디어 백업 시작 ==="
    local msg_dir="${BACKUP_DIR}/messenger_media"
    mkdir -p "$msg_dir"

    # 카카오톡
    log "카카오톡 미디어 백업 중..."
    adb pull /sdcard/Android/media/com.kakao.talk/ "${msg_dir}/KakaoTalk/" 2>> "$LOG_FILE" || warn "카카오톡 미디어 없음"

    # 텔레그램
    log "텔레그램 미디어 백업 중..."
    adb pull /sdcard/Android/media/org.telegram.messenger/ "${msg_dir}/Telegram/" 2>> "$LOG_FILE" || warn "텔레그램 미디어 없음"

    # WhatsApp
    log "WhatsApp 미디어 백업 중..."
    adb pull /sdcard/Android/media/com.whatsapp/ "${msg_dir}/WhatsApp/" 2>> "$LOG_FILE" || warn "WhatsApp 미디어 없음"

    # Samsung Notes
    log "삼성 노트 백업 중..."
    adb pull /sdcard/Android/media/com.samsung.android.app.notes/ "${msg_dir}/SamsungNotes/" 2>> "$LOG_FILE" || warn "삼성 노트 없음"

    log "=== 메신저 미디어 백업 완료 ==="
}

backup_contacts_sms() {
    log "=== 연락처/SMS/통화기록 백업 시작 ==="
    local data_dir="${BACKUP_DIR}/personal_data"
    mkdir -p "$data_dir"

    # 연락처
    log "연락처 추출 중..."
    adb shell content query --uri content://com.android.contacts/contacts \
        --projection "display_name:has_phone_number:contact_last_updated_timestamp" \
        > "${data_dir}/contacts_raw.txt" 2>> "$LOG_FILE" || warn "연락처 접근 실패"

    # SMS
    log "SMS 추출 중..."
    adb shell content query --uri content://sms/ \
        --projection "address:body:date:type:read" \
        > "${data_dir}/sms_raw.txt" 2>> "$LOG_FILE" || warn "SMS 접근 실패"

    # 통화 기록
    log "통화 기록 추출 중..."
    adb shell content query --uri content://call_log/calls \
        --projection "number:date:duration:type:name" \
        > "${data_dir}/call_log_raw.txt" 2>> "$LOG_FILE" || warn "통화 기록 접근 실패"

    # 캘린더
    log "캘린더 이벤트 추출 중..."
    adb shell content query --uri content://com.android.calendar/events \
        > "${data_dir}/calendar_events.txt" 2>> "$LOG_FILE" || warn "캘린더 접근 실패"

    # VCF 내보내기 안내
    warn "VCF 연락처 파일이 필요하면 폰에서 직접 내보내기 후 pull하세요"
    warn "연락처 앱 > 메뉴 > 연락처 관리 > 내보내기 > 내부 저장소"

    log "=== 연락처/SMS/통화기록 백업 완료 ==="
}

backup_summary() {
    log "========================================"
    log "          백업 완료 요약"
    log "========================================"
    log "백업 위치: ${BACKUP_DIR}"

    # 백업 크기 계산
    local total_size
    total_size=$(du -sh "$BACKUP_DIR" | cut -f1)
    log "총 백업 크기: ${total_size}"

    # 파일 수 계산
    local file_count
    file_count=$(find "$BACKUP_DIR" -type f | wc -l | tr -d ' ')
    log "총 파일 수: ${file_count}개"

    log "========================================"
}

# ============ 메인 실행 ============
main() {
    echo ""
    echo "============================================"
    echo "  Galaxy S26 Ultra ADB 종합 백업 스크립트"
    echo "============================================"
    echo ""

    # 백업 디렉토리 생성
    mkdir -p "$BACKUP_DIR"
    touch "$LOG_FILE"

    log "백업 시작: ${DATE}"

    # 1. 디바이스 확인
    check_device

    # 2. 기기 정보 수집
    get_device_info

    # 3. 미디어 백업
    backup_media

    # 4. 문서 백업
    backup_documents

    # 5. 메신저 미디어 백업
    backup_messenger_media

    # 6. 연락처/SMS/통화기록
    backup_contacts_sms

    # 7. 요약
    backup_summary

    echo ""
    echo "로그 파일: ${LOG_FILE}"
}

# 스크립트 실행
main "$@"
```

### 12.2 종합 백업 Python 스크립트

```python
#!/usr/bin/env python3
"""
Samsung Galaxy S26 Ultra 종합 ADB 데이터 추출 스크립트
====================================================
기능:
  - 미디어 파일 백업 (사진, 동영상, 음악, 녹음)
  - 문서/다운로드 백업
  - 메신저 미디어 백업 (카카오톡, 텔레그램 등)
  - 연락처/SMS/통화기록 추출 (Content Provider)
  - 시스템 정보 수집 (dumpsys)
  - 설치된 앱 목록 및 APK 추출

사용법:
  pip install adbutils
  python3 galaxy_backup.py
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from adbutils import adb, AdbDevice
except ImportError:
    print("adbutils가 설치되지 않았습니다.")
    print("설치: pip install adbutils")
    sys.exit(1)


# ============================================================
# 설정
# ============================================================
@dataclass
class BackupConfig:
    """백업 설정"""
    backup_root: Path = Path.home() / "GalaxyBackup"
    backup_media: bool = True
    backup_documents: bool = True
    backup_messenger: bool = True
    backup_contacts_sms: bool = True
    backup_system_info: bool = True
    backup_apks: bool = False  # APK 추출 (용량 큼)

    # 메신저 패키지명
    messenger_packages: list = field(default_factory=lambda: [
        ("com.kakao.talk", "KakaoTalk"),
        ("org.telegram.messenger", "Telegram"),
        ("com.whatsapp", "WhatsApp"),
        ("com.facebook.orca", "Messenger"),
        ("jp.naver.line.android", "LINE"),
        ("com.samsung.android.app.notes", "SamsungNotes"),
    ])

    # 백업할 미디어 디렉토리
    media_dirs: list = field(default_factory=lambda: [
        ("/sdcard/DCIM/Camera/", "Camera"),
        ("/sdcard/DCIM/Screenshots/", "Screenshots"),
        ("/sdcard/Pictures/", "Pictures"),
        ("/sdcard/Movies/", "Movies"),
        ("/sdcard/Music/", "Music"),
        ("/sdcard/Recordings/", "Recordings"),
    ])


# ============================================================
# 유틸리티
# ============================================================
class Logger:
    """컬러 로깅"""
    COLORS = {
        "info": "\033[92m",     # 초록
        "warn": "\033[93m",     # 노랑
        "error": "\033[91m",    # 빨강
        "reset": "\033[0m",
        "bold": "\033[1m",
    }

    def __init__(self, log_file: Optional[Path] = None):
        self.log_file = log_file

    def _log(self, level: str, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = self.COLORS.get(level, "")
        reset = self.COLORS["reset"]
        formatted = f"[{timestamp}] {msg}"
        print(f"{color}{formatted}{reset}")
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")

    def info(self, msg): self._log("info", msg)
    def warn(self, msg): self._log("warn", f"주의: {msg}")
    def error(self, msg): self._log("error", f"오류: {msg}")
    def header(self, msg):
        self._log("info", "=" * 50)
        self._log("info", f"  {msg}")
        self._log("info", "=" * 50)


def parse_content_query(raw: str) -> list[dict]:
    """adb shell content query 출력을 파싱"""
    rows = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r"Row:\s*\d+\s*(.*)", line)
        if not match:
            continue
        pairs_str = match.group(1)
        row = {}
        for m in re.finditer(r"(\w+)=(.*?)(?:,\s*(?=\w+=)|$)", pairs_str):
            row[m.group(1)] = m.group(2).strip()
        if row:
            rows.append(row)
    return rows


def get_dir_size(path: Path) -> str:
    """디렉토리 크기를 사람이 읽을 수 있는 형식으로 반환"""
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    for unit in ["B", "KB", "MB", "GB"]:
        if total < 1024:
            return f"{total:.1f} {unit}"
        total /= 1024
    return f"{total:.1f} TB"


def count_files(path: Path) -> int:
    """디렉토리 내 파일 수 반환"""
    return sum(1 for _ in path.rglob("*") if _.is_file())


# ============================================================
# 백업 클래스
# ============================================================
class GalaxyBackup:
    """Galaxy S26 Ultra ADB 백업 매니저"""

    def __init__(self, config: Optional[BackupConfig] = None):
        self.config = config or BackupConfig()
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_dir = self.config.backup_root / self.timestamp
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.log = Logger(self.backup_dir / "backup.log")
        self.device: Optional[AdbDevice] = None

    def connect(self) -> bool:
        """디바이스 연결 확인"""
        devices = adb.device_list()
        if not devices:
            self.log.error("연결된 디바이스가 없습니다.")
            self.log.error("확인사항:")
            self.log.error("  1. USB-C 케이블 연결 (데이터 전송 가능 케이블)")
            self.log.error("  2. USB 디버깅 활성화")
            self.log.error("  3. RSA 키 인증 승인")
            return False

        self.device = devices[0]
        model = self.device.shell("getprop ro.product.model").strip()
        android_ver = self.device.shell("getprop ro.build.version.release").strip()
        self.log.info(f"디바이스 연결됨: {model} (Android {android_ver})")
        self.log.info(f"시리얼: {self.device.serial}")
        return True

    def _remote_dir_exists(self, path: str) -> bool:
        """원격 디렉토리 존재 여부 확인"""
        result = self.device.shell(f"[ -d '{path}' ] && echo EXISTS || echo NOTFOUND")
        return "EXISTS" in result

    def _pull_directory(self, remote: str, local_name: str, category: str = "") -> int:
        """원격 디렉토리를 로컬로 복사하고 파일 수 반환"""
        if not self._remote_dir_exists(remote):
            self.log.warn(f"{remote} 경로 없음 - 건너뜀")
            return 0

        local_path = self.backup_dir / category / local_name
        local_path.mkdir(parents=True, exist_ok=True)

        try:
            # subprocess로 adb pull 실행 (adbutils sync보다 대량 복사에 적합)
            result = subprocess.run(
                ["adb", "-s", self.device.serial, "pull", remote, str(local_path)],
                capture_output=True, text=True, timeout=3600
            )
            pulled = count_files(local_path)
            size = get_dir_size(local_path)
            self.log.info(f"  {local_name}: {pulled}개 파일 ({size})")
            return pulled
        except subprocess.TimeoutExpired:
            self.log.error(f"  {local_name}: 타임아웃 (1시간 초과)")
            return 0
        except Exception as e:
            self.log.error(f"  {local_name}: {e}")
            return 0

    def backup_device_info(self):
        """기기 정보 수집"""
        self.log.header("기기 정보 수집")
        info_dir = self.backup_dir / "device_info"
        info_dir.mkdir(exist_ok=True)

        info = {
            "model": self.device.shell("getprop ro.product.model").strip(),
            "manufacturer": self.device.shell("getprop ro.product.manufacturer").strip(),
            "android_version": self.device.shell("getprop ro.build.version.release").strip(),
            "sdk_version": self.device.shell("getprop ro.build.version.sdk").strip(),
            "serial": self.device.shell("getprop ro.serialno").strip(),
            "build_id": self.device.shell("getprop ro.build.display.id").strip(),
            "oneui_version": self.device.shell("getprop ro.build.version.oneui").strip(),
            "security_patch": self.device.shell("getprop ro.build.version.security_patch").strip(),
            "csc_sales_code": self.device.shell("getprop ro.csc.sales_code").strip(),
        }

        with open(info_dir / "device_info.json", "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        # dumpsys 정보
        for cmd_name, cmd in [
            ("battery", "dumpsys battery"),
            ("wifi", "dumpsys wifi"),
            ("storage", "df -h"),
            ("memory", "dumpsys meminfo"),
        ]:
            output = self.device.shell(cmd)
            with open(info_dir / f"{cmd_name}.txt", "w", encoding="utf-8") as f:
                f.write(output)

        # 설치된 앱 목록
        packages = self.device.shell("pm list packages -3").strip().split("\n")
        with open(info_dir / "installed_apps.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(packages)))

        self.log.info(f"기기 정보 저장 완료 ({len(packages)}개 서드파티 앱)")

    def backup_media(self):
        """미디어 파일 백업"""
        self.log.header("미디어 파일 백업")
        total = 0
        for remote, name in self.config.media_dirs:
            total += self._pull_directory(remote, name, "media")
        self.log.info(f"미디어 백업 완료: 총 {total}개 파일")

    def backup_documents(self):
        """문서/다운로드 백업"""
        self.log.header("문서/다운로드 백업")
        total = 0
        total += self._pull_directory("/sdcard/Documents/", "Documents", "documents")
        total += self._pull_directory("/sdcard/Download/", "Download", "documents")
        self.log.info(f"문서 백업 완료: 총 {total}개 파일")

    def backup_messenger_media(self):
        """메신저 미디어 파일 백업"""
        self.log.header("메신저 미디어 백업")
        total = 0
        for pkg, name in self.config.messenger_packages:
            remote = f"/sdcard/Android/media/{pkg}/"
            total += self._pull_directory(remote, name, "messenger")
        self.log.info(f"메신저 미디어 백업 완료: 총 {total}개 파일")

    def backup_contacts_sms_calllog(self):
        """연락처, SMS, 통화기록 추출"""
        self.log.header("연락처/SMS/통화기록 추출")
        data_dir = self.backup_dir / "personal_data"
        data_dir.mkdir(exist_ok=True)

        # 연락처
        self.log.info("연락처 추출 중...")
        try:
            raw = self.device.shell(
                "content query --uri content://com.android.contacts/contacts "
                "--projection display_name:has_phone_number:contact_last_updated_timestamp"
            )
            contacts = parse_content_query(raw)
            with open(data_dir / "contacts.json", "w", encoding="utf-8") as f:
                json.dump(contacts, f, ensure_ascii=False, indent=2)
            self.log.info(f"  연락처: {len(contacts)}개 추출")
        except Exception as e:
            self.log.error(f"  연락처 추출 실패: {e}")

        # SMS
        self.log.info("SMS 추출 중...")
        try:
            raw = self.device.shell(
                "content query --uri content://sms/ "
                "--projection address:body:date:type:read"
            )
            messages = parse_content_query(raw)
            for msg in messages:
                if "date" in msg:
                    try:
                        ts = int(msg["date"]) / 1000
                        msg["date_readable"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, OSError):
                        pass
                msg["direction"] = "수신" if msg.get("type") == "1" else "발신"
            with open(data_dir / "sms.json", "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            self.log.info(f"  SMS: {len(messages)}개 추출")
        except Exception as e:
            self.log.error(f"  SMS 추출 실패: {e}")

        # 통화기록
        self.log.info("통화 기록 추출 중...")
        try:
            raw = self.device.shell(
                "content query --uri content://call_log/calls "
                "--projection number:date:duration:type:name"
            )
            calls = parse_content_query(raw)
            type_map = {"1": "수신", "2": "발신", "3": "부재중", "5": "거절"}
            for call in calls:
                if "date" in call:
                    try:
                        ts = int(call["date"]) / 1000
                        call["date_readable"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, OSError):
                        pass
                call["call_type"] = type_map.get(call.get("type", ""), "기타")
            with open(data_dir / "call_log.json", "w", encoding="utf-8") as f:
                json.dump(calls, f, ensure_ascii=False, indent=2)
            self.log.info(f"  통화기록: {len(calls)}개 추출")
        except Exception as e:
            self.log.error(f"  통화기록 추출 실패: {e}")

        # 캘린더
        self.log.info("캘린더 이벤트 추출 중...")
        try:
            raw = self.device.shell("content query --uri content://com.android.calendar/events")
            events = parse_content_query(raw)
            with open(data_dir / "calendar.json", "w", encoding="utf-8") as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
            self.log.info(f"  캘린더: {len(events)}개 이벤트 추출")
        except Exception as e:
            self.log.error(f"  캘린더 추출 실패: {e}")

    def backup_apks(self):
        """설치된 서드파티 앱 APK 추출"""
        self.log.header("APK 추출")
        apk_dir = self.backup_dir / "apks"
        apk_dir.mkdir(exist_ok=True)

        packages = self.device.shell("pm list packages -3").strip().split("\n")
        total = 0

        for pkg_line in packages:
            pkg = pkg_line.replace("package:", "").strip()
            if not pkg:
                continue
            try:
                apk_path = self.device.shell(f"pm path {pkg}").strip()
                apk_path = apk_path.replace("package:", "").strip()
                if apk_path:
                    local_apk = apk_dir / f"{pkg}.apk"
                    subprocess.run(
                        ["adb", "-s", self.device.serial, "pull", apk_path, str(local_apk)],
                        capture_output=True, timeout=120
                    )
                    total += 1
            except Exception as e:
                self.log.warn(f"  {pkg}: APK 추출 실패 - {e}")

        self.log.info(f"APK 추출 완료: {total}개")

    def run(self):
        """전체 백업 실행"""
        print()
        self.log.header("Galaxy S26 Ultra ADB 종합 백업")
        self.log.info(f"백업 위치: {self.backup_dir}")
        print()

        start_time = time.time()

        # 디바이스 연결 확인
        if not self.connect():
            return

        # 순차 백업 실행
        if self.config.backup_system_info:
            self.backup_device_info()

        if self.config.backup_media:
            self.backup_media()

        if self.config.backup_documents:
            self.backup_documents()

        if self.config.backup_messenger:
            self.backup_messenger_media()

        if self.config.backup_contacts_sms:
            self.backup_contacts_sms_calllog()

        if self.config.backup_apks:
            self.backup_apks()

        # 요약
        elapsed = time.time() - start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        print()
        self.log.header("백업 완료 요약")
        self.log.info(f"백업 위치: {self.backup_dir}")
        self.log.info(f"총 크기: {get_dir_size(self.backup_dir)}")
        self.log.info(f"총 파일 수: {count_files(self.backup_dir)}개")
        self.log.info(f"소요 시간: {minutes}분 {seconds}초")
        self.log.info(f"로그 파일: {self.backup_dir / 'backup.log'}")


# ============================================================
# 메인 실행
# ============================================================
if __name__ == "__main__":
    config = BackupConfig(
        backup_root=Path.home() / "GalaxyBackup",
        backup_media=True,
        backup_documents=True,
        backup_messenger=True,
        backup_contacts_sms=True,
        backup_system_info=True,
        backup_apks=False,  # True로 변경하면 APK도 추출
    )

    backup = GalaxyBackup(config)
    backup.run()
```

### 12.3 증분 백업 스크립트 (변경분만)

```python
#!/usr/bin/env python3
"""
증분 백업 스크립트 - 마지막 백업 이후 변경된 파일만 백업
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from adbutils import adb


def incremental_backup(
    remote_dir: str = "/sdcard/DCIM/Camera/",
    local_backup_root: str = "./incremental_backup",
    state_file: str = ".last_backup_state.json"
):
    """증분 백업 수행"""
    d = adb.device()
    backup_root = Path(local_backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    state_path = backup_root / state_file

    # 이전 백업 상태 로드
    previous_state = {}
    if state_path.exists():
        with open(state_path, "r") as f:
            previous_state = json.load(f)

    # 현재 파일 목록과 수정 시각 수집
    print(f"원격 파일 목록 수집 중: {remote_dir}")
    result = d.shell(f"find {remote_dir} -type f -exec stat -c '%n|%Y|%s' {{}} \\;")

    current_state = {}
    new_files = []
    modified_files = []

    for line in result.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        filepath, mtime, size = parts[0], parts[1], parts[2]
        current_state[filepath] = {"mtime": mtime, "size": size}

        prev = previous_state.get(filepath)
        if prev is None:
            new_files.append(filepath)
        elif prev["mtime"] != mtime or prev["size"] != size:
            modified_files.append(filepath)

    files_to_pull = new_files + modified_files
    print(f"새 파일: {len(new_files)}개, 변경 파일: {len(modified_files)}개")
    print(f"총 전송할 파일: {len(files_to_pull)}개")

    # 파일 다운로드
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = backup_root / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)

    for i, filepath in enumerate(files_to_pull, 1):
        rel_path = filepath.replace(remote_dir, "").lstrip("/")
        local_file = session_dir / rel_path
        local_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                ["adb", "-s", d.serial, "pull", filepath, str(local_file)],
                capture_output=True, timeout=300
            )
            print(f"  [{i}/{len(files_to_pull)}] {rel_path}")
        except Exception as e:
            print(f"  [오류] {rel_path}: {e}")

    # 상태 저장
    with open(state_path, "w") as f:
        json.dump(current_state, f, indent=2)

    print(f"\n증분 백업 완료: {session_dir}")
    print(f"전송된 파일: {len(files_to_pull)}개")


if __name__ == "__main__":
    # 카메라 사진 증분 백업
    incremental_backup(
        remote_dir="/sdcard/DCIM/Camera/",
        local_backup_root="./camera_incremental"
    )
```

---

## 부록: 빠른 참조 명령어 모음

### 자주 쓰는 ADB 명령어

```bash
# === 연결 ===
adb devices                              # 연결된 디바이스 목록
adb devices -l                           # 상세 정보 포함
adb kill-server && adb start-server      # ADB 서버 재시작

# === 파일 전송 ===
adb pull <원격경로> <로컬경로>            # 디바이스 → PC
adb push <로컬경로> <원격경로>            # PC → 디바이스
adb pull /sdcard/ ./phone_backup/        # 전체 내부저장소 백업

# === 쉘 명령 ===
adb shell                                # 대화형 쉘 진입
adb shell ls /sdcard/                    # 파일 목록
adb shell df -h                          # 저장소 사용량
adb shell screencap -p /sdcard/sc.png    # 스크린샷
adb shell screenrecord /sdcard/rec.mp4   # 화면 녹화

# === 앱 관리 ===
adb shell pm list packages               # 전체 앱 목록
adb shell pm list packages -3            # 서드파티 앱만
adb install app.apk                      # 앱 설치
adb uninstall com.example.app            # 앱 삭제

# === 데이터 조회 ===
adb shell content query --uri content://sms/          # SMS
adb shell content query --uri content://call_log/calls # 통화기록
adb shell content query --uri content://com.android.contacts/contacts  # 연락처

# === 시스템 정보 ===
adb shell getprop ro.product.model       # 모델명
adb shell dumpsys battery                # 배터리 상태
adb shell dumpsys wifi                   # Wi-Fi 정보

# === 고급 전송 (tar 활용) ===
adb exec-out tar -cf - /sdcard/DCIM/ | tar -xf - -C ./backup/

# === 미러링 ===
scrcpy                                   # 화면 미러링
scrcpy --record output.mp4              # 녹화 포함
```

---

## 참고 자료

- [Android 공식 ADB 문서](https://developer.android.com/tools/adb)
- [adbutils GitHub](https://github.com/openatx/adbutils)
- [scrcpy GitHub](https://github.com/Genymobile/scrcpy)
- [Samsung Knox 문서](https://docs.samsungknox.com/admin/knox-guard/how-to-guides/manage-devices/block-and-unblock-adb-command/)
- [XDA ADB 명령어 모음](https://gist.github.com/Pulimet/5013acf2cd5b28e55036c82c91bd56d8)
- [Samsung Smart Switch 백업 형식](http://fileformats.archiveteam.org/wiki/Samsung_Smart_Switch_backup)
- [Android Backup Extractor](https://github.com/nelenkov/android-backup-extractor)
- [ADB Content Provider 명령어](https://www.adb-shell.com/android/content/)
- [ADB 전송 속도 최적화](https://avivace.com/notes/android-copy/)
- [Samsung Galaxy S26 Ultra 스펙 (GSMArena)](https://www.gsmarena.com/samsung_galaxy_s26_ultra_5g-14320.php)
