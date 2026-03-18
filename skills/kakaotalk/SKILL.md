---
name: kakaotalk
description: macOS에서 KakaoTalk 메시지를 읽고 보내는 CLI 도구 (kmsg)
metadata:
  openclaw:
    emoji: "💬"
    requires:
      bins:
        - kmsg
    install:
      - id: brew
        kind: brew
        formula: channprj/tap/kmsg
        bins:
          - kmsg
        label: "Install kmsg (brew)"
    os:
      - macos
---

# KakaoTalk (kmsg)

macOS에서 KakaoTalk 앱의 메시지를 읽고 보내는 CLI 도구입니다.
Accessibility API를 사용하여 KakaoTalk UI를 자동화합니다.

## 상태 확인

```bash
kmsg status
```

KakaoTalk 실행 여부와 Accessibility 권한을 확인합니다.

## 채팅방 목록

```bash
kmsg chats
kmsg chats --limit 20
```

현재 카카오톡의 채팅방 목록을 출력합니다.

## 메시지 읽기

```bash
kmsg read "채팅방이름" --limit 20 --json
```

특정 채팅방의 최근 메시지를 읽습니다. `--json` 플래그를 사용하면 구조화된 JSON으로 출력됩니다.

JSON 출력 형식:
```json
{
  "chat": "채팅방이름",
  "fetched_at": "2026-03-18T10:30:00.000Z",
  "count": 20,
  "messages": [
    { "author": "발신자", "time_raw": "10:32", "body": "메시지 내용" }
  ]
}
```

## 메시지 보내기

```bash
kmsg send "수신자" "메시지 내용"
kmsg send "수신자" "메시지 내용" --dry-run
```

### 중요: 발신 안전 규칙

1. 메시지를 보내기 전에 반드시 `--dry-run`으로 미리보기를 보여주세요
2. 사용자가 수신자와 내용을 명시적으로 확인한 후에만 실제 발신하세요
3. 절대 사용자 확인 없이 메시지를 보내지 마세요

## 이미지 보내기

```bash
kmsg send-image "수신자" "/path/to/image.png"
```

## 캐시 관리

```bash
kmsg cache status    # 캐시 상태 확인
kmsg cache clear     # 캐시 초기화
kmsg cache warmup    # 캐시 워밍업 (성능 향상)
```

## 옵션

- `--keep-window`: 작업 후 카톡 창을 닫지 않음
- `--deep-recovery`: UI 탐색 실패 시 대체 경로로 복구
- `--trace-ax`: 디버깅용 AX 요소 탐색 로그 출력
- `--no-cache`: 캐시 사용하지 않음
- `--refresh-cache`: 캐시 갱신
