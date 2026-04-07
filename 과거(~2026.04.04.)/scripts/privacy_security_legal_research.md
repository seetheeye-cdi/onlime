# 개인 데이터 처리 앱의 프라이버시, 보안, 법적 고려사항 종합 조사

> 조사일: 2026-04-02
> 목적: Onlime 프로젝트(카카오톡 알림 수집, 녹음 전사, 캘린더 매칭, AI 보고서 생성)의 Android 앱 개발 시 법적 리스크 및 보안 아키텍처 설계 가이드

---

## 목차
1. [개인정보보호법(PIPA) 분석](#1-개인정보보호법)
2. [통신비밀보호법 - 녹음 동의 법률](#2-통신비밀보호법)
3. [카카오톡 이용약관 - 데이터 수집 제한](#3-카카오톡-이용약관)
4. [Google Calendar API 이용약관](#4-google-calendar-api)
5. [기기 내 대화 데이터 안전 저장](#5-기기-내-데이터-저장)
6. [로컬 데이터베이스 암호화 모범 사례](#6-데이터베이스-암호화)
7. [Android Keystore 보안 자격증명 관리](#7-android-keystore)
8. [데이터 보존 및 삭제 정책](#8-데이터-보존-삭제)
9. [GDPR 유사 고려사항 - 개인 도구에도 적용되는가](#9-gdpr-유사-고려사항)
10. [타인의 대화 데이터 처리 모범 사례](#10-타인-데이터-처리)
11. [Samsung Knox 보안 프레임워크 통합](#11-samsung-knox)
12. [실전 보안 아키텍처 설계](#12-보안-아키텍처)

---

## 1. 개인정보보호법(PIPA) 분석 {#1-개인정보보호법}

### 1.1 관련 법령

**개인정보 보호법** (법률 제20897호, 2025.04.01. 일부개정, 2025.10.02. 시행)

- 법령 원문: https://www.law.go.kr/법령/개인정보보호법
- 시행령 원문: https://www.law.go.kr/LSW/lsInfoP.do?lsId=011468

### 1.2 Onlime 프로젝트에 대한 PIPA 적용 여부

#### 핵심 쟁점: "개인적 활동" 예외가 있는가?

**결론: 한국 개인정보보호법에는 GDPR과 달리 "순수한 개인적/가정적 활동" 적용 제외 조항이 명시적으로 존재하지 않는다.**

개인정보보호법 제58조(적용의 일부 제외)는 다음 경우에만 제3장~제8장의 적용을 면제한다:

| 적용 제외 대상 | 조항 |
|----------------|------|
| 국가안전보장 관련 정보 분석 목적 | 제58조 제1항 제2호 |
| 언론의 취재/보도 목적 | 제58조 제1항 제4호 |
| 종교단체의 선교 목적 | 제58조 제1항 제4호 |
| 정당의 선거 입후보자 추천 목적 | 제58조 제1항 제4호 |

**"개인적 목적의 데이터 처리"는 적용 제외 사유에 포함되어 있지 않다.**

따라서 비록 Onlime이 순수 개인용 도구라 하더라도, 타인의 개인정보(카카오톡 메시지 발신자 이름, 대화 내용 등)를 처리하는 한 PIPA의 규율 대상이 될 수 있다.

#### 학술적 논의

외국 입법례 연구에 따르면 EU GDPR, 일본 개인정보보호법 등에서는 "순수한 사적 활동/가사 활동"을 적용 제외 사유로 인정하고 있으나, 한국 PIPA는 이를 채택하지 않았다. 학계에서는 "적용배제 대상과 그 범위가 과도하거나 체계상 맞지 않다"는 비판이 존재한다.

> 참고: "개인정보 보호법 적용 배제사유에 관한 연구" (한국정보법학회) - https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002421055

### 1.3 2025년 주요 개정 내용 (Onlime 관련)

#### (1) 자동화된 결정에 대한 거부권 및 설명 요구권 (신설)

정보주체는 완전히 자동화된 시스템(AI 포함)으로 개인정보를 처리하여 이루어지는 결정에 대해:
- **거부권**: 자동화된 결정을 거부할 수 있음
- **설명 요구권**: 자동화된 결정의 근거에 대한 설명을 요구할 수 있음

**Onlime 영향**: LLM을 통한 일간 브리핑 생성, 메시지 분류/우선순위 결정 등이 "자동화된 결정"에 해당할 수 있다. 단, 개인용 도구이므로 타인에게 영향을 미치는 결정이 아닌 경우 실질적 리스크는 낮다.

#### (2) 개인정보 전송 요구권 (2025.04.01. 시행)

정보주체가 본인의 개인정보를 본인 또는 지정된 기관으로 전송 요구할 수 있는 권리가 신설되었다.

- 전송 내역은 최소 3년간 보관 의무
- 적용 대상: 보건의료정보전송자, 통신정보전송자, 에너지정보전송자 등

**Onlime 영향**: 직접적 적용 대상은 아니지만, 향후 카카오 등 플랫폼에서 사용자 데이터 전송을 공식 지원할 가능성이 있어 합법적 데이터 수집 경로가 확대될 수 있다.

### 1.4 PIPA 준수를 위한 실무 권장사항

| 원칙 | Onlime 적용 방안 |
|------|-------------------|
| **최소 수집 원칙** (제3조) | 브리핑 생성에 필요한 최소한의 정보만 수집. 알림 텍스트 전문이 아닌 요약/키워드만 저장 고려 |
| **목적 외 이용 금지** (제18조) | 수집된 데이터를 브리핑 생성 외 목적에 사용하지 않을 것 |
| **안전성 확보 조치** (제29조) | 기기 내 암호화 저장, 접근 통제 등 기술적 보호조치 이행 |
| **개인정보 파기** (제21조) | 보존 기간 경과 후 즉시 파기. 자동 삭제 스케줄 구현 |

---

## 2. 통신비밀보호법 - 녹음 동의 법률 {#2-통신비밀보호법}

### 2.1 핵심 법 조문

**통신비밀보호법 제3조 (통신 및 대화비밀의 보호)**

> "누구든지 이 법과 형사소송법 또는 군사법원법의 규정에 의하지 아니하고는 우편물의 검열, 전기통신의 감청 또는 통신사실확인자료의 제공을 하거나 **공개되지 아니한 타인간의 대화를 녹음 또는 청취하지 못한다.**"

**통신비밀보호법 제14조 (타인의 대화비밀 침해금지)**

> 누구든지 공개되지 아니한 타인간의 대화를 녹음하거나 전자장치 또는 기계적 수단을 이용하여 청취할 수 없다.

**위반 시 처벌**: 1년 이상 10년 이하의 징역 + 5년 이하의 자격정지 (제16조)

- 법령 원문: https://casenote.kr/법령/통신비밀보호법/제3조
- 대법원 판례: https://casenote.kr/대법원/2023도8603

### 2.2 녹음 유형별 법적 판단

| 녹음 유형 | 법적 판단 | 근거 |
|-----------|-----------|------|
| **대화 당사자가 자신이 참여한 대화를 녹음** | 합법 (형사 처벌 대상 아님) | 대법원 판례: "대화 당사자 일방이 상대방 모르게 통화내용을 녹음하는 것은 감청에 해당하지 않는다" |
| **대화에 참여하지 않은 제3자가 녹음** | 불법 (형사 처벌 대상) | 통신비밀보호법 제3조 제1항 위반 |
| **당사자 녹음 후 제3자에게 공개** | 민사상 불법행위 가능 | 음성권 및 사생활 비밀 침해 (민법 제750조 불법행위) |
| **당사자 녹음물의 개인적 보관** | 합법 | 공개하지 않는 한 법적 문제 없음 |

### 2.3 Onlime 프로젝트 관련 구체적 시나리오

#### 시나리오 1: Plaud 등 녹음기로 자신이 참여한 미팅 녹음
- **판단**: 합법. 대화 당사자로서 녹음하는 것은 허용됨.
- **주의**: 녹음물을 제3자에게 공유하거나 공개하면 민사 책임 발생 가능.
- **권장**: 녹음 전 참석자에게 녹음 사실을 고지하는 것이 바람직함 (법적 의무는 아니나 윤리적 권장).

#### 시나리오 2: 카카오톡 메시지를 AI 서비스(외부 API)로 전송하여 처리
- **판단**: 회색지대. 대화 당사자로서 메시지를 열람하는 것은 합법이나, 타인의 대화 내용을 외부 서버로 전송하는 것은 정보통신망법 제49조 위반 가능성이 있음.
- **권장**: 가능한 한 온디바이스(로컬) 처리를 우선하고, 외부 API 전송 시 개인식별정보를 제거(익명화/가명처리)한 후 전송.

#### 시나리오 3: 통화 녹음을 Whisper API로 전사
- **판단**: 자신이 참여한 통화 녹음의 전사 자체는 합법이나, 녹음 파일을 외부 서버(OpenAI)에 업로드하는 것은 상대방 동의 없이 음성 데이터를 제3자에게 제공하는 것에 해당할 수 있음.
- **권장**: 가능하면 로컬 Whisper 모델 사용. 외부 API 사용 시 상대방에게 사전 고지 또는 동의 확보.

### 2.4 대법원 최신 판례 (2024.02.29.)

대법원 2023도8603 판결에서 "종료된 대화의 녹음물을 재생하여 듣는 것이 통신비밀보호법상 '청취'에 해당하는지"가 쟁점이 된 사건이 있었다.

> 참고: https://www.scourt.go.kr/portal/news/NewsViewAction.work?seqnum=9749

---

## 3. 카카오톡 이용약관 - 데이터 수집 제한 {#3-카카오톡-이용약관}

### 3.1 카카오 운영정책 관련 조항

카카오 운영정책 (2024.08.14. 개정) 원문: https://t1.kakaocdn.net/talksafety/file/카카오톡_운영정책_20240814.pdf

#### 금지 행위

카카오 운영정책 제3조 제2항에 따르면 다음 행위가 금지된다:

> **(4) "컴퓨터 소프트웨어, 하드웨어, 전기통신 장비의 정상적인 가동을 방해, 파괴하거나, 할 수 있는 방법으로 서비스에 접근, 이용하는 행위"**

이 조항은 명시적으로 "크롤링" 또는 "스크래핑"을 언급하지 않지만, **"카카오톡이 허용하지 않는 방법에 의한 서비스 이용"**을 포괄적으로 금지한다.

#### 개인정보보호 위반 관련 (카카오톡 안녕가이드)

> "카카오톡을 이용하여 타인의 개인정보를 유포, 게재하거나 개인정보보호법을 위반하여 무단으로 개인정보를 수집, 탈취, 거래하는 등 관계 법령을 위반하는 행위는 허용되지 않습니다."

참고: https://kakao.com/talksafety/policy/usersafety/privacyviolations

### 3.2 카카오톡 데이터 수집 방법별 리스크 평가

| 수집 방법 | 약관 위반 리스크 | 기술적 실현 가능성 | 권장 여부 |
|-----------|-----------------|-------------------|-----------|
| **알림(Notification) 기반 수집** (Tasker) | **낮음** - 안드로이드 OS 알림 API를 통한 수집으로 카카오톡 서비스에 직접 접근하지 않음 | 높음 | 권장 |
| **공식 내보내기 기능** (수동) | **없음** - 카카오톡이 공식 제공하는 기능 사용 | 높음 (수동) | 가장 안전 |
| **UI 자동화 내보내기** (AutoInput) | **중간** - UI 자동화는 "허용하지 않는 방법" 해석 가능 | 중간 (UI 변경에 취약) | 주의 필요 |
| **API 직접 호출/크롤링** | **높음** - 비인가 API 접근은 명백한 약관 위반 | 낮음 (보안 강화) | 비권장 |
| **DB 직접 접근** (루팅 필요) | **매우 높음** - 서비스 보안 우회 | 매우 낮음 (암호화) | 절대 비권장 |

### 3.3 2026년 카카오 약관 개정 동향

2026년 2월 4일부터 시행된 개정 약관에서 카카오는 수집 범위를 대폭 확대했다:

- 프로필 변경 내역부터 게시/조회 흔적까지 "이용자의 행동 데이터 전부"에 가까운 수집
- 비동의 시 서비스 이용 불가
- 이에 대한 "강제 수집" 논란이 진행 중

> 참고: https://www.khan.co.kr/article/202512211730001

### 3.4 권장 접근 방식

**알림(Notification) 기반 수집을 권장한다.** 이유:

1. Android OS의 공식 Notification Listener API를 사용하므로 카카오톡 서비스에 직접 접근하지 않음
2. 사용자가 자신의 기기에서 자신에게 온 알림을 읽는 행위이므로 약관 위반 논란이 적음
3. 기술적으로 안정적이며 카카오톡 업데이트에 영향받지 않음
4. 수집되는 데이터가 알림 내용으로 제한되어 최소 수집 원칙에 부합

**단, 알림으로 수집되는 정보는 제한적이다** (보낸 사람 이름, 메시지 미리보기 등). 전체 대화 내역이 필요한 경우 카카오톡의 공식 "대화 내보내기" 기능을 활용하되, 내보낸 파일의 처리는 로컬에서 수행할 것을 권장한다.

---

## 4. Google Calendar API 이용약관 {#4-google-calendar-api}

### 4.1 적용되는 정책

Onlime은 이미 Google Calendar API를 사용하고 있으므로 다음 정책을 준수해야 한다:

1. **Google APIs Terms of Service**: https://developers.google.com/terms
2. **Google API Services User Data Policy**: https://developers.google.com/terms/api-services-user-data-policy
3. **Google Workspace API User Data and Developer Policy**: https://developers.google.com/workspace/workspace-api-user-data-developer-policy

### 4.2 Limited Use Requirements (제한적 사용 요건)

Google API를 통해 얻은 사용자 데이터에 대해 다음이 **금지**된다:

| 금지 사항 | 설명 |
|-----------|------|
| 광고 목적 전용/판매 | 리타겟팅, 맞춤형 광고 등에 데이터 사용 금지 |
| 제3자 전송/판매 | 광고 플랫폼, 데이터 브로커 등에 판매 금지 |
| 신용도 판단 | 대출 등 신용도 판단 목적 사용 금지 |
| 감시 목적 | 제3자의 감시 활동에 데이터 제공 금지 |

### 4.3 허용되는 사용 범위

| 허용 사항 | 조건 |
|-----------|------|
| 사용자 대면 기능 제공/개선 | 앱 UI에서 두드러지는(prominent) 기능이어야 함 |
| 보안 목적 | 남용/버그 조사 |
| 법적 준수 | 관련 법규 준수 목적 |
| 합병/인수 | 사용자 명시적 동의 하에 |

### 4.4 Onlime 프로젝트 준수 사항

현재 Onlime의 Google Calendar API 사용 (`calendar.readonly` 스코프):

```python
# onlime.toml에서
[gcal]
calendar_ids = ["primary", "seetheeye@chamchi.kr"]
sync_days_back = 7
sync_days_forward = 14
```

**준수 확인사항:**

1. **Sensitive Scope**: `calendar.readonly`는 sensitive scope에 해당. 개인용이므로 OAuth 검증은 불필요하지만, 앱을 배포하는 경우 Google의 OAuth 앱 검증 절차 필요.
2. **데이터 사용 제한**: 캘린더 데이터는 오직 브리핑 보고서 생성(사용자 대면 기능)에만 사용해야 함.
3. **저장 보안**: 캘린더 데이터를 로컬에 저장할 경우 암호화 필수.
4. **OAuth 토큰 관리**: `google_token.json` 등 자격증명 파일은 암호화하여 저장.

### 4.5 개인 사용 시 실무 고려

개인 프로젝트에서 Google API를 사용하는 경우:

- OAuth 동의 화면에서 "테스트" 모드로 유지 가능 (100명 미만 테스트 사용자)
- 자기 자신의 계정 데이터만 접근하므로 실질적 제한 없음
- 단, OAuth 자격증명(`client_secret.json`, `token.json`)은 절대 공개 저장소에 커밋하지 말 것
- API 키/토큰 유출 시 즉시 갱신(revoke + regenerate)

---

## 5. 기기 내 대화 데이터 안전 저장 {#5-기기-내-데이터-저장}

### 5.1 Android 데이터 저장 계층

```
┌─────────────────────────────────────────────┐
│              Android 데이터 저장 계층          │
├─────────────────────────────────────────────┤
│                                              │
│  [1층] App Internal Storage                  │
│  /data/data/<package>/                       │
│  - 앱 전용, 다른 앱 접근 불가                   │
│  - 앱 삭제 시 자동 삭제                        │
│  - 루팅 시에만 접근 가능                        │
│  -> 카카오톡 로그, API 토큰 저장에 적합          │
│                                              │
│  [2층] Encrypted Internal Storage            │
│  EncryptedSharedPreferences / EncryptedFile   │
│  - AES-256 암호화                             │
│  - Android Keystore 키 관리                   │
│  -> 민감 설정값, OAuth 토큰 저장에 적합          │
│                                              │
│  [3층] Encrypted Database                    │
│  Room + SQLCipher (AES-256)                   │
│  - 전체 DB 암호화                              │
│  - 키는 Keystore에서 관리                      │
│  -> 대화 내역, 전사 결과 저장에 적합             │
│                                              │
│  [4층] External Storage (주의!)               │
│  /sdcard/                                    │
│  - 다른 앱에서 접근 가능                        │
│  - 사용자가 파일 관리자로 열람 가능              │
│  -> 민감 데이터 저장 금지                       │
│                                              │
└─────────────────────────────────────────────┘
```

### 5.2 데이터 유형별 저장 전략

| 데이터 유형 | 저장 위치 | 암호화 방식 | 접근 제어 |
|-------------|-----------|-------------|-----------|
| OAuth 토큰 (Google, Plaud) | EncryptedSharedPreferences | AES-256-SIV (키) + AES-256-GCM (값) | Android Keystore |
| API 키 (OpenAI, Anthropic) | EncryptedSharedPreferences | AES-256-SIV + AES-256-GCM | Android Keystore + 생체인증 |
| 카카오톡 알림 로그 | Room + SQLCipher | AES-256 (전체 DB) | 앱 내부 저장소 |
| 녹음 전사 결과 | Room + SQLCipher | AES-256 (전체 DB) | 앱 내부 저장소 |
| 캘린더 이벤트 캐시 | Room + SQLCipher | AES-256 (전체 DB) | 앱 내부 저장소 |
| 생성된 보고서 | EncryptedFile | AES-256-GCM (Streaming AEAD) | 앱 내부 저장소 |
| 녹음 원본 파일 (임시) | 앱 내부 캐시 | File-Based Encryption (FBE) | 처리 후 즉시 삭제 |

### 5.3 Jetpack Security 구현 가이드

#### EncryptedSharedPreferences (토큰/API 키 저장)

```kotlin
// build.gradle
implementation "androidx.security:security-crypto:1.1.0-alpha06"

// 사용
val masterKey = MasterKey.Builder(context)
    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
    .setRequestStrongBoxBacked(true)  // StrongBox 우선
    .setUserAuthenticationRequired(true, 300)  // 5분 생체인증
    .build()

val securePrefs = EncryptedSharedPreferences.create(
    context,
    "onlime_secure_prefs",
    masterKey,
    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
)

// 토큰 저장
securePrefs.edit()
    .putString("google_oauth_token", token)
    .putString("anthropic_api_key", apiKey)
    .apply()
```

#### EncryptedFile (보고서 파일 암호화)

```kotlin
val encryptedFile = EncryptedFile.Builder(
    context,
    File(context.filesDir, "daily_briefing_2026-04-02.md"),
    masterKey,
    EncryptedFile.FileEncryptionScheme.AES256_GCM_HKDF_4KB
).build()

// 쓰기
encryptedFile.openFileOutput().use { output ->
    output.write(reportContent.toByteArray())
}

// 읽기
encryptedFile.openFileInput().use { input ->
    val content = input.bufferedReader().readText()
}
```

---

## 6. 로컬 데이터베이스 암호화 모범 사례 {#6-데이터베이스-암호화}

### 6.1 Room + SQLCipher 구현

SQLCipher는 SQLite의 드롭인 대체로 AES-256 전체 데이터베이스 암호화를 제공한다.

#### 의존성 설정

```kotlin
// build.gradle
dependencies {
    implementation "androidx.room:room-runtime:2.6.1"
    implementation "androidx.room:room-ktx:2.6.1"
    kapt "androidx.room:room-compiler:2.6.1"

    // SQLCipher
    implementation "net.zetetic:android-database-sqlcipher:4.5.6"
    implementation "androidx.sqlite:sqlite-ktx:2.4.0"
}
```

#### 데이터베이스 정의

```kotlin
@Database(
    entities = [
        KakaoMessage::class,
        TranscriptEntry::class,
        CalendarEvent::class,
        DailyReport::class
    ],
    version = 1
)
abstract class OnlimeDatabase : RoomDatabase() {
    abstract fun kakaoMessageDao(): KakaoMessageDao
    abstract fun transcriptDao(): TranscriptDao
    abstract fun calendarEventDao(): CalendarEventDao
    abstract fun dailyReportDao(): DailyReportDao
}
```

#### 암호화된 DB 생성

```kotlin
object DatabaseProvider {

    @Volatile
    private var INSTANCE: OnlimeDatabase? = null

    fun getDatabase(context: Context): OnlimeDatabase {
        return INSTANCE ?: synchronized(this) {
            // 1. Android Keystore에서 암호화 키 생성/로드
            val dbKey = getOrCreateDatabaseKey(context)

            // 2. SQLCipher SupportFactory 생성
            val passphrase = SQLiteDatabase.getBytes(dbKey.toCharArray())
            val factory = SupportFactory(passphrase)

            // 3. 암호화된 Room DB 빌드
            val instance = Room.databaseBuilder(
                context.applicationContext,
                OnlimeDatabase::class.java,
                "onlime_encrypted.db"
            )
            .openHelperFactory(factory)
            .build()

            INSTANCE = instance

            // 4. 키를 메모리에서 즉시 제거
            dbKey.fill('0')

            instance
        }
    }

    private fun getOrCreateDatabaseKey(context: Context): CharArray {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .setRequestStrongBoxBacked(true)
            .build()

        val securePrefs = EncryptedSharedPreferences.create(
            context,
            "onlime_db_key_store",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )

        var key = securePrefs.getString("db_encryption_key", null)
        if (key == null) {
            // 최초 실행: 256비트 랜덤 키 생성
            key = generateSecureRandomKey()
            securePrefs.edit().putString("db_encryption_key", key).apply()
        }

        return key.toCharArray()
    }

    private fun generateSecureRandomKey(): String {
        val keyBytes = ByteArray(32)  // 256-bit
        java.security.SecureRandom().nextBytes(keyBytes)
        return Base64.encodeToString(keyBytes, Base64.NO_WRAP)
    }
}
```

### 6.2 암호화 모범 사례 체크리스트

| 항목 | 설명 | 구현 |
|------|------|------|
| 키 하드코딩 금지 | 소스코드에 암호화 키를 절대 하드코딩하지 말 것 | Android Keystore + EncryptedSharedPreferences |
| 런타임 키 생성 | 최초 실행 시 SecureRandom으로 256비트 키 생성 | `java.security.SecureRandom` |
| 메모리 내 키 보호 | 사용 후 즉시 키 데이터를 0으로 덮어쓰기 | `charArray.fill('0')` |
| 하드웨어 바인딩 | 키를 TEE/StrongBox에 바인딩 | `setIsStrongBoxBacked(true)` |
| 생체인증 연동 | 민감 데이터 접근 시 생체인증 요구 | `setUserAuthenticationRequired(true)` |
| 백업 제외 | 암호화된 DB가 클라우드 백업에 포함되지 않도록 | `android:allowBackup="false"` |

### 6.3 성능 고려

SQLCipher 사용 시 약 25% 성능 저하가 발생할 수 있다. 대응 방안:

- 적절한 DB 인덱스 설정으로 쿼리 성능 보완
- 대량 삽입 시 트랜잭션 사용
- 읽기 전용 쿼리에 WAL(Write-Ahead Logging) 모드 활용
- 검색이 빈번한 컬럼에 FTS(Full-Text Search) 적용

---

## 7. Android Keystore 보안 자격증명 관리 {#7-android-keystore}

### 7.1 Android Keystore 시스템 개요

Android Keystore는 암호화 키를 안전하게 저장하기 위한 시스템이다. 핵심 보안 특성:

1. **추출 불가**: 키 재료(key material)가 앱 프로세스에 진입하지 않음. 암호화 연산은 시스템 프로세스에서 수행.
2. **하드웨어 바인딩**: TEE(Trusted Execution Environment) 또는 SE(Secure Element)/StrongBox에 키를 바인딩 가능.
3. **사용 제한**: 키 생성 시 허용 용도(암호화/복호화/서명/검증)를 지정하면 이후 변경 불가.

참고: https://developer.android.com/privacy-and-security/keystore

### 7.2 하드웨어 보안 계층

```
┌────────────────────────────────────────────┐
│           보안 수준 (높음 -> 낮음)             │
├────────────────────────────────────────────┤
│                                             │
│  [최상] StrongBox (Secure Element)           │
│  - 독립 CPU, 보안 저장소, TRNG              │
│  - 물리적 변조 방지                          │
│  - Android 9+ (API 28+)                     │
│  - 삼성 기기: Samsung eSE                    │
│  - 지원 알고리즘: RSA 2048, AES 128/256,     │
│    ECDSA P-256, HMAC-SHA256                 │
│                                             │
│  [상] TEE (Trusted Execution Environment)   │
│  - 메인 프로세서 내 격리 영역                  │
│  - ARM TrustZone 기반                       │
│  - 대부분 Android 기기 지원                   │
│                                             │
│  [중] 소프트웨어 Keystore                    │
│  - OS 커널 레벨 보호                         │
│  - 하드웨어 보안 없음                        │
│                                             │
└────────────────────────────────────────────┘
```

### 7.3 Onlime에서의 키 관리 전략

```kotlin
// StrongBox 지원 확인 및 폴백
fun createMasterKey(context: Context): MasterKey {
    val hasStrongBox = context.packageManager
        .hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)

    return if (hasStrongBox) {
        MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .setRequestStrongBoxBacked(true)
            .setUserAuthenticationRequired(true, 300)  // 5분
            .build()
    } else {
        // TEE 기반 폴백
        MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .setUserAuthenticationRequired(true, 300)
            .build()
    }
}
```

### 7.4 키 용도별 구성

| 키 용도 | 알고리즘 | 하드웨어 바인딩 | 인증 요구 | 유효 기간 |
|---------|----------|----------------|-----------|-----------|
| DB 암호화 마스터 키 | AES-256-GCM | StrongBox (우선) / TEE | 5분 타임아웃 | 무기한 (키 로테이션 6개월) |
| API 토큰 암호화 키 | AES-256-GCM | StrongBox / TEE | 매 접근 시 생체인증 | 무기한 |
| 파일 암호화 키 | AES-256-GCM | TEE | 5분 타임아웃 | 무기한 |
| 서명 키 (서버 통신) | ECDSA P-256 | StrongBox | 매 사용 시 | 1년 (자동 갱신) |

### 7.5 생체인증 연동 구현

```kotlin
// 생체인증 후 암호화 키 사용
val biometricPrompt = BiometricPrompt(activity,
    ContextCompat.getMainExecutor(activity),
    object : BiometricPrompt.AuthenticationCallback() {
        override fun onAuthenticationSucceeded(result: AuthenticationResult) {
            // 인증 성공 -> 암호화된 데이터 접근 가능
            val cipher = result.cryptoObject?.cipher
            // cipher를 사용하여 데이터 복호화
        }

        override fun onAuthenticationFailed() {
            // 인증 실패 -> 데이터 접근 차단
        }
    }
)

val promptInfo = BiometricPrompt.PromptInfo.Builder()
    .setTitle("Onlime 인증")
    .setSubtitle("민감 데이터에 접근하려면 인증이 필요합니다")
    .setAllowedAuthenticators(
        BiometricManager.Authenticators.BIOMETRIC_STRONG or
        BiometricManager.Authenticators.DEVICE_CREDENTIAL
    )
    .build()

// KeyStore에서 키를 가져와 CryptoObject 생성
val keyStore = KeyStore.getInstance("AndroidKeyStore")
keyStore.load(null)
val key = keyStore.getKey("onlime_master_key", null) as SecretKey

val cipher = Cipher.getInstance("AES/GCM/NoPadding")
cipher.init(Cipher.DECRYPT_MODE, key, spec)

biometricPrompt.authenticate(
    promptInfo,
    BiometricPrompt.CryptoObject(cipher)
)
```

### 7.6 보안 점검 체크리스트

- [ ] 모든 암호화 키가 Android Keystore에 저장되는가?
- [ ] StrongBox 가용 시 우선 사용하는가?
- [ ] 민감 키에 생체인증이 바인딩되어 있는가?
- [ ] 키 재료가 앱 메모리에 평문으로 남지 않는가?
- [ ] 새로운 생체 정보 등록 시 키 무효화 정책이 있는가?
- [ ] 키 로테이션 일정이 수립되어 있는가?

---

## 8. 데이터 보존 및 삭제 정책 {#8-데이터-보존-삭제}

### 8.1 법적 근거

**개인정보보호법 제21조 (개인정보의 파기)**

> 개인정보처리자는 보유기간의 경과, 개인정보의 처리 목적 달성 등 그 개인정보가 불필요하게 되었을 때에는 지체 없이 그 개인정보를 파기하여야 한다.

**GDPR 제5조 제1항 (e)호 - 저장 기간 제한 원칙**

> 개인 데이터는 처리 목적에 필요한 기간을 초과하여 정보주체를 식별할 수 있는 형태로 보관되어서는 아니 된다.

### 8.2 Onlime 데이터 보존 정책 권장안

| 데이터 유형 | 보존 기간 | 삭제 방법 | 근거 |
|-------------|-----------|-----------|------|
| 카카오톡 알림 원본 | **7일** | 자동 삭제 (스케줄러) | 일간 브리핑 생성 후 원본 불필요 |
| 녹음 원본 파일 | **전사 완료 후 즉시** | 즉시 삭제 | 전사 텍스트로 대체 |
| 전사 텍스트 | **30일** | 자동 삭제 | 월간 보고서 생성 주기 |
| 생성된 보고서 (일간) | **90일** | 자동 삭제 | 분기 리뷰 주기 |
| 생성된 보고서 (주간) | **1년** | 자동 삭제 | 연간 리뷰 주기 |
| 캘린더 이벤트 캐시 | **14일** | 자동 갱신 시 교체 | sync_days_forward 설정 기반 |
| OAuth/API 토큰 | **토큰 만료 시** | 자동 갱신 시 이전 토큰 삭제 | 보안 모범 사례 |

### 8.3 자동 삭제 구현

```kotlin
// 정기 데이터 정리 Worker (WorkManager)
class DataCleanupWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val db = DatabaseProvider.getDatabase(applicationContext)

        // 7일 이전 카카오톡 알림 삭제
        val kakaoRetention = System.currentTimeMillis() - (7 * 24 * 60 * 60 * 1000L)
        db.kakaoMessageDao().deleteOlderThan(kakaoRetention)

        // 30일 이전 전사 텍스트 삭제
        val transcriptRetention = System.currentTimeMillis() - (30 * 24 * 60 * 60 * 1000L)
        db.transcriptDao().deleteOlderThan(transcriptRetention)

        // 90일 이전 일간 보고서 삭제
        val dailyReportRetention = System.currentTimeMillis() - (90 * 24 * 60 * 60 * 1000L)
        db.dailyReportDao().deleteDailyOlderThan(dailyReportRetention)

        // 처리 완료된 녹음 파일 삭제
        cleanupProcessedRecordings()

        return Result.success()
    }

    private fun cleanupProcessedRecordings() {
        val recordingsDir = File(applicationContext.filesDir, "recordings_temp")
        recordingsDir.listFiles()?.forEach { file ->
            // 전사 완료 표시된 파일만 삭제
            if (isTranscribed(file)) {
                secureDelete(file)
            }
        }
    }

    // 안전한 파일 삭제 (덮어쓰기 후 삭제)
    private fun secureDelete(file: File) {
        if (file.exists()) {
            val length = file.length()
            RandomAccessFile(file, "rw").use { raf ->
                val random = SecureRandom()
                val data = ByteArray(1024)
                var written = 0L
                while (written < length) {
                    random.nextBytes(data)
                    val toWrite = minOf(data.size.toLong(), length - written).toInt()
                    raf.write(data, 0, toWrite)
                    written += toWrite
                }
            }
            file.delete()
        }
    }
}

// WorkManager 스케줄링 (매일 새벽 3시)
val cleanupRequest = PeriodicWorkRequestBuilder<DataCleanupWorker>(
    1, TimeUnit.DAYS
)
    .setInitialDelay(calculateDelayUntil3AM(), TimeUnit.MILLISECONDS)
    .addTag("data_cleanup")
    .build()

WorkManager.getInstance(context)
    .enqueueUniquePeriodicWork(
        "onlime_data_cleanup",
        ExistingPeriodicWorkPolicy.KEEP,
        cleanupRequest
    )
```

### 8.4 사용자 데이터 완전 삭제 기능

앱 삭제 시 또는 사용자 요청 시 모든 데이터를 완전 삭제하는 기능을 제공해야 한다:

```kotlin
fun purgeAllData(context: Context) {
    // 1. DB 삭제
    context.deleteDatabase("onlime_encrypted.db")

    // 2. SharedPreferences 삭제
    val prefsDir = File(context.applicationInfo.dataDir, "shared_prefs")
    prefsDir.listFiles()?.forEach { it.delete() }

    // 3. 내부 저장소 파일 삭제
    context.filesDir.deleteRecursively()
    context.cacheDir.deleteRecursively()

    // 4. Keystore 키 삭제
    val keyStore = KeyStore.getInstance("AndroidKeyStore")
    keyStore.load(null)
    keyStore.aliases().toList().filter { it.startsWith("onlime_") }.forEach {
        keyStore.deleteEntry(it)
    }
}
```

---

## 9. GDPR 유사 고려사항 - 개인 도구에도 적용되는가 {#9-gdpr-유사-고려사항}

### 9.1 GDPR Household Exemption (가정용 면제)

**GDPR 제2조 제2항 (c)호**:

> GDPR은 자연인이 순수하게 개인적 또는 가정적 활동(purely personal or household activity) 과정에서 수행하는 개인정보 처리에는 적용되지 않는다.

**Recital 18**:

> 서신 교환, 주소록 보관, 소셜 네트워킹, 이러한 활동 맥락에서의 온라인 활동이 개인적/가정적 활동에 해당할 수 있다.

참고: https://gdpr-info.eu/recitals/no-18/

### 9.2 GDPR Household Exemption의 한계

이 면제는 **매우 좁게 해석**된다:

1. **공개 장소나 일반 접근 가능한 웹사이트는 제외**: 데이터를 공개적으로 게시하면 면제 불적용
2. **법인은 적용 불가**: 자연인(개인)만 면제 대상
3. **서비스 제공자에게는 적용 불가**: 개인 활동을 위한 도구를 제공하는 서비스 제공자(예: 앱 개발자)는 여전히 GDPR 적용

### 9.3 한국법에서의 상황

**한국 개인정보보호법에는 "가정용 면제"에 해당하는 조항이 없다.**

이는 이론적으로 개인이 자신의 폰에서 개인적 목적으로 타인의 개인정보를 처리하는 경우에도 PIPA가 적용될 수 있음을 의미한다.

### 9.4 실무적 리스크 평가

| 시나리오 | 법적 리스크 | 실질적 리스크 | 설명 |
|---------|-----------|-------------|------|
| 개인 폰에서 자신에게 온 카카오톡 알림을 로컬에 저장 | 낮음 | 매우 낮음 | 자기 기기에서 자기 앱 알림 접근 |
| 저장된 대화를 로컬 AI로 요약 | 낮음 | 매우 낮음 | 데이터가 기기를 떠나지 않음 |
| 저장된 대화를 외부 AI API로 전송 | 중간 | 낮음 | 타인 개인정보의 제3자 제공에 해당 가능 |
| 처리된 데이터를 제3자와 공유 | 높음 | 중간 | 명백한 개인정보 제3자 제공 |
| 앱을 타인에게 배포 | 높음 | 높음 | 개인정보처리자로서의 의무 발생 |

### 9.5 권장사항: "GDPR 정신"을 자발적으로 적용

법적 의무와 관계없이, 개인 도구 개발에서도 다음 원칙을 자발적으로 적용하는 것을 권장한다:

1. **데이터 최소화**: 필요한 최소한의 데이터만 수집/저장
2. **목적 제한**: 브리핑 생성이라는 명확한 목적에만 사용
3. **저장 기간 제한**: 목적 달성 후 지체 없이 삭제
4. **보안 조치**: 암호화 등 기술적 보호조치 이행
5. **투명성**: 어떤 데이터를 어떻게 처리하는지 자신에게 명확히 인지
6. **접근 제한**: 기기 잠금, 생체인증 등으로 물리적 접근 통제

---

## 10. 타인의 대화 데이터 처리 모범 사례 {#10-타인-데이터-처리}

### 10.1 윤리적 원칙

Onlime은 자신에게 온 메시지를 처리하지만, 그 메시지에는 타인의 개인정보가 포함되어 있다. 다음 원칙을 준수해야 한다:

#### (1) 데이터 수탁자(Guardian)로서의 책임

> "다른 사람의 데이터를 관리하게 되면, 당신은 그 데이터의 수호자가 된다."
> - Privacy Guides (https://www.privacyguides.org/articles/2025/03/10/the-privacy-of-others/)

타인이 신뢰를 바탕으로 공유한 대화 내용을 안전하게 관리해야 한다.

#### (2) 동의와 개인적 차이 존중

사람마다 프라이버시 감수성이 다르다. 한 사람이 편하게 공유하는 내용이 다른 사람에게는 매우 민감할 수 있다.

#### (3) 삭제 권리 존중

원본 메시지 발신자가 메시지를 삭제했다면(카카오톡 메시지 삭제 기능 등), 수집된 사본도 삭제하는 것이 윤리적이다. 스크린샷으로 타인의 게시물을 재게시하면 상대방의 삭제 권리를 박탈하는 것이다.

### 10.2 기술적 구현 권장사항

#### (1) 개인정보 익명화/가명처리 파이프라인

```python
import re
import hashlib

def anonymize_message(message: dict) -> dict:
    """메시지에서 개인 식별 정보를 가명처리"""
    anonymized = message.copy()

    # 발신자 이름을 해시로 대체 (내부 매핑은 별도 암호화 저장)
    if 'sender' in anonymized:
        sender_hash = hashlib.sha256(
            anonymized['sender'].encode()
        ).hexdigest()[:8]
        anonymized['sender_id'] = f"USER_{sender_hash}"
        # 원본 이름은 AI 전송 시 제거
        del anonymized['sender']

    # 전화번호 마스킹
    if 'message' in anonymized:
        anonymized['message'] = re.sub(
            r'01[0-9]-?\d{3,4}-?\d{4}',
            '[전화번호]',
            anonymized['message']
        )

        # 이메일 마스킹
        anonymized['message'] = re.sub(
            r'[\w.-]+@[\w.-]+\.\w+',
            '[이메일]',
            anonymized['message']
        )

        # 주민등록번호 마스킹
        anonymized['message'] = re.sub(
            r'\d{6}-?[1-4]\d{6}',
            '[주민번호]',
            anonymized['message']
        )

        # 계좌번호 패턴 마스킹
        anonymized['message'] = re.sub(
            r'\d{3,4}-\d{2,6}-\d{2,6}',
            '[계좌번호]',
            anonymized['message']
        )

    return anonymized
```

#### (2) 외부 API 전송 전 개인정보 제거

```python
def prepare_for_external_api(messages: list[dict]) -> list[dict]:
    """외부 AI API로 전송하기 전 개인정보 제거"""
    sanitized = []
    for msg in messages:
        sanitized_msg = anonymize_message(msg)
        # 추가: 민감 키워드 필터링
        if contains_sensitive_info(sanitized_msg.get('message', '')):
            sanitized_msg['message'] = '[민감 정보 포함 - 요약 생략]'
        sanitized.append(sanitized_msg)
    return sanitized

def contains_sensitive_info(text: str) -> bool:
    """민감 정보 포함 여부 검사"""
    sensitive_patterns = [
        r'비밀번호',
        r'카드\s*번호',
        r'인증\s*번호',
        r'OTP',
        r'계좌',
    ]
    for pattern in sensitive_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False
```

#### (3) 데이터 접근 로그

```kotlin
// 모든 데이터 접근을 로깅하여 추적 가능하게
@Entity(tableName = "access_log")
data class AccessLog(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val timestamp: Long = System.currentTimeMillis(),
    val dataType: String,        // "kakao_message", "transcript", etc.
    val action: String,          // "read", "process", "send_to_api", "delete"
    val recordCount: Int,
    val destination: String?     // null = local, "openai" = 외부
)
```

### 10.3 대화 상대방에 대한 사회적 고려

| 상황 | 권장 행동 |
|------|-----------|
| 비즈니스 미팅 녹음 | 미팅 시작 시 "기록을 위해 녹음합니다" 고지 |
| 개인적 대화 | AI 처리 사실을 밝히는 것이 윤리적 (법적 의무는 아님) |
| 민감한 상담/고민 | 해당 대화는 AI 처리에서 제외하는 것을 권장 |
| 그룹 채팅 | 다수의 타인 정보가 포함되므로 더욱 신중하게 처리 |

---

## 11. Samsung Knox 보안 프레임워크 통합 {#11-samsung-knox}

### 11.1 Knox 보안 아키텍처

Samsung Knox는 하드웨어 수준부터 소프트웨어까지 다층 보안을 제공한다.

```
┌────────────────────────────────────────┐
│        Samsung Knox 보안 스택           │
├────────────────────────────────────────┤
│                                         │
│  [앱 계층]                              │
│  Knox SDK APIs                          │
│  - 컨테이너화                           │
│  - SDP (Sensitive Data Protection)      │
│  - DualDAR 암호화                       │
│                                         │
│  [OS 계층]                              │
│  SE for Android (보안 강화 안드로이드)    │
│  Real-Time Kernel Protection (RKP)      │
│  Defeat Firmware Rollback               │
│                                         │
│  [하드웨어 계층]                         │
│  TrustZone (ARM)                        │
│  Samsung eSE (Secure Element)           │
│  Hardware Root of Trust                  │
│  Device Unique Hardware Key (DUHK)       │
│                                         │
└────────────────────────────────────────┘
```

참고: https://docs.samsungknox.com/admin/fundamentals/whitepaper/samsung-knox-mobile-security/system-security/knox-framework/

### 11.2 Secure Folder 활용

Samsung Secure Folder는 Knox 기반의 암호화된 컨테이너이다:

- **별도 암호화 영역**: PIN, 패턴, 비밀번호, 생체인증으로 접근
- **앱 격리**: Secure Folder 내 앱은 외부 앱에서 접근 불가
- **독립 데이터**: 같은 앱이라도 Secure Folder 내외에서 별도 데이터 유지

**Onlime 활용 방안**: Onlime 앱을 Secure Folder 내에 설치하여 추가 보안 계층 제공. 기기 잠금이 해제되어도 Secure Folder의 별도 인증이 필요하므로 이중 보안이 가능하다.

### 11.3 Knox SDP (Sensitive Data Protection)

> **주의**: Knox SDP는 API level 33, Knox SDK v3.7에서 deprecated되었다. 새로운 구현에서는 Android 표준 암호화(Jetpack Security + Android Keystore)를 우선 고려할 것.

Knox SDP가 제공했던 3가지 핵심 클래스:

| 클래스 | 기능 | 대안 |
|--------|------|------|
| `SdpFileSystem` | 파일 수준 암호화, 기기 잠금 시 자동 보호 | `EncryptedFile` (Jetpack Security) |
| `SdpDatabase` | 컬럼 수준 DB 암호화 | Room + SQLCipher |
| `SdpEngine` | 암호화 상태/키 관리 | Android Keystore |

### 11.4 Knox SDK 활용이 적합한 경우

- B2B 엔터프라이즈 앱 (MDM 연동)
- Samsung Knox Partner Program 가입이 필요
- 삼성 기기 전용 기능이므로 다른 제조사 기기에서는 동작하지 않음

**Onlime의 경우**: 개인용 앱이므로 Knox SDK 직접 통합보다는 Secure Folder에 앱을 설치하는 방식이 더 실용적이다. Knox SDK는 Samsung Knox Partner Program 가입과 별도 라이선스가 필요하여 개인 프로젝트에는 과도한 요구사항이다.

### 11.5 실용적 Samsung 보안 활용 방안

| 기능 | 구현 방법 | 효과 |
|------|-----------|------|
| Secure Folder 설치 | Onlime 앱을 Secure Folder 내 설치 | 이중 인증 (기기 잠금 + Secure Folder 잠금) |
| Samsung Pass 연동 | Android BiometricPrompt 사용 (Samsung Pass 자동 연동) | 강력한 생체인증 |
| Private Share | 생성된 보고서 공유 시 Samsung Private Share 사용 | 공유 콘텐츠 만료/권한 제어 |
| Samsung Blockchain Keystore | 추후 무결성 검증이 필요한 경우 | 데이터 변조 방지 |

---

## 12. 실전 보안 아키텍처 설계 {#12-보안-아키텍처}

### 12.1 전체 보안 아키텍처

```
┌───────────────────────────────────────────────────────────────────┐
│                    Onlime 보안 아키텍처 (Android)                   │
├───────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌─────────── 접근 제어 계층 ──────────┐                           │
│  │                                       │                          │
│  │  [1] 기기 잠금 (PIN/패턴/생체)        │                          │
│  │  [2] Secure Folder (선택)             │                          │
│  │  [3] 앱 내 생체인증 (BiometricPrompt) │                          │
│  │                                       │                          │
│  └───────────────────────────────────────┘                          │
│                         │                                           │
│                         ▼                                           │
│  ┌─────────── 데이터 수집 계층 ──────────┐                          │
│  │                                        │                          │
│  │  Notification Listener (카카오톡)      │                          │
│  │  Google Calendar API (OAuth 2.0)       │                          │
│  │  녹음 파일 감지 (FileObserver)         │                          │
│  │  Plaud API (녹음 전사)                 │                          │
│  │                                        │                          │
│  │  -> 수집 즉시 내부 저장소에 암호화 저장 │                          │
│  │                                        │                          │
│  └────────────────┬───────────────────────┘                          │
│                    │                                                  │
│                    ▼                                                  │
│  ┌─────────── 저장 계층 (암호화) ────────┐                           │
│  │                                        │                          │
│  │  ┌──────────────────────────────────┐ │                          │
│  │  │  Android Keystore (TEE/StrongBox)│ │                          │
│  │  │  - DB 마스터 키                   │ │                          │
│  │  │  - 파일 암호화 키                 │ │                          │
│  │  │  - API 토큰 암호화 키            │ │                          │
│  │  └──────────────────────────────────┘ │                          │
│  │                  │                     │                          │
│  │                  ▼                     │                          │
│  │  ┌────────────────────────────────┐   │                          │
│  │  │  Room + SQLCipher (AES-256)    │   │                          │
│  │  │  - 카카오톡 메시지              │   │                          │
│  │  │  - 전사 텍스트                  │   │                          │
│  │  │  - 캘린더 이벤트                │   │                          │
│  │  │  - 접근 로그                    │   │                          │
│  │  └────────────────────────────────┘   │                          │
│  │                                        │                          │
│  │  ┌────────────────────────────────┐   │                          │
│  │  │  EncryptedSharedPreferences    │   │                          │
│  │  │  - OAuth 토큰                   │   │                          │
│  │  │  - API 키                       │   │                          │
│  │  │  - 사용자 설정                  │   │                          │
│  │  └────────────────────────────────┘   │                          │
│  │                                        │                          │
│  │  ┌────────────────────────────────┐   │                          │
│  │  │  EncryptedFile                 │   │                          │
│  │  │  - 생성된 보고서               │   │                          │
│  │  │  - 임시 처리 파일              │   │                          │
│  │  └────────────────────────────────┘   │                          │
│  │                                        │                          │
│  └────────────────┬───────────────────────┘                          │
│                    │                                                  │
│                    ▼                                                  │
│  ┌─────────── 처리 계층 ─────────────────┐                           │
│  │                                        │                          │
│  │  [로컬 우선 처리]                      │                          │
│  │  - 개인정보 마스킹/익명화              │                          │
│  │  - 키워드 추출 및 분류                 │                          │
│  │  - 기본 요약 (온디바이스 LLM 가능 시)  │                          │
│  │                                        │                          │
│  │  [외부 API 전송 (필요 시)]             │                          │
│  │  - 익명화된 데이터만 전송              │                          │
│  │  - HTTPS (TLS 1.3)                    │                          │
│  │  - Certificate Pinning                │                          │
│  │                                        │                          │
│  └────────────────┬───────────────────────┘                           │
│                    │                                                  │
│                    ▼                                                  │
│  ┌─────────── 생명주기 관리 ─────────────┐                           │
│  │                                        │                          │
│  │  자동 삭제 스케줄러 (WorkManager)      │                          │
│  │  - 알림 원본: 7일                     │                          │
│  │  - 녹음 파일: 전사 후 즉시             │                          │
│  │  - 전사 텍스트: 30일                  │                          │
│  │  - 보고서: 90일 (일간) / 1년 (주간)   │                          │
│  │                                        │                          │
│  │  완전 삭제 기능 (사용자 요청 시)       │                          │
│  │  - 모든 DB, 파일, 키 삭제              │                          │
│  │  - 안전한 덮어쓰기(secure wipe)        │                          │
│  │                                        │                          │
│  └────────────────────────────────────────┘                          │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### 12.2 네트워크 보안

#### Certificate Pinning 구현

```kotlin
// OkHttp Certificate Pinning
val certificatePinner = CertificatePinner.Builder()
    .add("api.openai.com", "sha256/AAAA...")
    .add("api.anthropic.com", "sha256/BBBB...")
    .add("www.googleapis.com", "sha256/CCCC...")
    .build()

val okHttpClient = OkHttpClient.Builder()
    .certificatePinner(certificatePinner)
    .protocols(listOf(Protocol.HTTP_2, Protocol.HTTP_1_1))
    .build()
```

#### 네트워크 보안 설정 (network_security_config.xml)

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <!-- 평문 통신 전면 금지 -->
    <base-config cleartextTrafficPermitted="false">
        <trust-anchors>
            <certificates src="system" />
        </trust-anchors>
    </base-config>

    <!-- 개발 환경 (디버그 빌드만) -->
    <debug-overrides>
        <trust-anchors>
            <certificates src="user" />
        </trust-anchors>
    </debug-overrides>
</network-security-config>
```

### 12.3 앱 무결성 보호

```kotlin
// AndroidManifest.xml
android:allowBackup="false"          // 클라우드 백업 비활성화
android:extractNativeLibs="false"    // 네이티브 라이브러리 추출 방지
android:usesCleartextTraffic="false" // HTTP 평문 통신 차단

// ProGuard/R8 (난독화)
// proguard-rules.pro
-keep class kr.chamchi.onlime.data.** { *; }  // 데이터 클래스 유지
-dontwarn net.zetetic.**                        // SQLCipher 경고 무시
```

### 12.4 보안 체크리스트 (구현 전 검토)

#### 법적 준수

- [ ] 카카오톡 알림 기반 수집만 사용 (API 크롤링/스크래핑 금지)
- [ ] 녹음은 본인이 참여한 대화만 (통신비밀보호법 준수)
- [ ] 외부 API 전송 시 개인정보 익명화/가명처리
- [ ] 데이터 보존 기간 정책 수립 및 자동 삭제 구현
- [ ] 앱 내 개인정보 처리방침 게시 (배포 시)

#### 기기 보안

- [ ] 모든 데이터가 앱 내부 저장소에 암호화 저장
- [ ] Android Keystore 기반 키 관리 (StrongBox 우선)
- [ ] 민감 기능에 생체인증 연동
- [ ] 앱 삭제 시 완전 데이터 삭제
- [ ] 클라우드 백업 비활성화 (`allowBackup="false"`)

#### 네트워크 보안

- [ ] HTTPS Only (평문 통신 차단)
- [ ] Certificate Pinning 적용
- [ ] OAuth 토큰 암호화 저장
- [ ] API 키 하드코딩 금지 (EncryptedSharedPreferences 사용)

#### 데이터 처리

- [ ] 개인정보 마스킹 파이프라인 구현
- [ ] 데이터 접근 로그 기록
- [ ] 보존 기간 경과 데이터 자동 삭제
- [ ] Secure Wipe (안전한 덮어쓰기) 구현

### 12.5 위협 모델링

| 위협 | 발생 확률 | 영향도 | 대응 |
|------|-----------|--------|------|
| 기기 분실/도난 | 중간 | 높음 | 기기 암호화 + 앱 내 암호화 + 생체인증 + 원격 삭제 |
| 앱 데이터 무단 접근 (루팅) | 낮음 | 높음 | SQLCipher + Keystore 바인딩 + 루팅 탐지 |
| 네트워크 도청 | 낮음 | 중간 | HTTPS + Certificate Pinning |
| 외부 API 서비스 데이터 유출 | 낮음 | 중간 | 데이터 익명화 후 전송 + 최소 데이터 원칙 |
| 카카오톡 약관 변경/계정 제재 | 낮음 | 중간 | 알림 기반 수집 (가장 안전한 방법) 유지 |
| 법적 분쟁 (개인정보 침해 주장) | 매우 낮음 | 높음 | 데이터 최소화 + 자동 삭제 + 익명화 + 개인 사용 범위 유지 |

---

## 핵심 요약 및 최종 권장사항

### 법적 측면

1. **한국 PIPA에는 "개인용 면제"가 없다.** 따라서 개인 도구라도 타인의 개인정보를 처리할 때는 최소한의 보호조치를 취해야 한다.
2. **녹음은 본인이 참여한 대화만 합법이다.** 단, 녹음물을 제3자에게 공개하면 민사 책임이 발생할 수 있다.
3. **카카오톡 알림 기반 수집이 가장 안전한 방법이다.** API 크롤링이나 DB 직접 접근은 약관 위반 및 법률 위반 리스크가 높다.
4. **외부 AI API 전송 시 반드시 개인정보를 익명화/가명처리해야 한다.**

### 기술적 측면

1. **암호화 3중 레이어**: Android Keystore(키 보호) + SQLCipher(DB 암호화) + Jetpack Security(파일/설정 암호화)
2. **생체인증을 민감 데이터 접근의 게이트키퍼로 사용**
3. **데이터 자동 삭제 스케줄러를 반드시 구현** (WorkManager 기반)
4. **로컬 처리를 최우선**, 외부 전송은 최소화
5. **Samsung Secure Folder에 앱을 설치하여 추가 보안 계층 확보**

### 윤리적 측면

1. **타인의 대화 데이터는 "수탁받은 것"이라는 인식으로 관리**
2. **미팅 녹음 시 참석자에게 사전 고지하는 습관**
3. **민감한 상담/고민 대화는 AI 처리에서 제외**
4. **수집 범위를 자기 검열하여 실제 필요한 데이터만 처리**

---

## 참고 자료

### 법령

- 개인정보 보호법: https://www.law.go.kr/법령/개인정보보호법
- 개인정보 보호법 시행령: https://www.law.go.kr/LSW/lsInfoP.do?lsId=011468
- 통신비밀보호법: https://casenote.kr/법령/통신비밀보호법/제3조
- 정보통신망법 제49조: https://brunch.co.kr/@herelaw/1

### 약관 및 정책

- 카카오톡 운영정책: https://talksafety.kakao.com/policy
- 카카오 개인정보 처리방침: https://privacy.kakao.com/policy
- Google API Services User Data Policy: https://developers.google.com/terms/api-services-user-data-policy
- Google APIs Terms of Service: https://developers.google.com/terms

### 기술 문서

- Android Keystore: https://developer.android.com/privacy-and-security/keystore
- Jetpack Security: https://developer.android.com/jetpack/androidx/releases/security
- Samsung Knox SDK: https://docs.samsungknox.com/dev/knox-sdk/
- Samsung Knox Data Protection: https://docs.samsungknox.com/admin/fundamentals/whitepaper/samsung-knox-mobile-security/system-security/data-protection/
- OWASP Android Keystore: https://mas.owasp.org/MASTG/knowledge/android/MASVS-STORAGE/MASTG-KNOW-0043/

### 학술 및 참고

- GDPR Household Exemption: https://gdpr-info.eu/recitals/no-18/
- Privacy Guides - Privacy of Others: https://www.privacyguides.org/articles/2025/03/10/the-privacy-of-others/
- 개인정보보호법 적용 배제사유 연구: https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002421055

---

*이 문서는 Onlime 프로젝트의 프라이버시, 보안, 법적 고려사항에 대한 조사 보고서입니다.*
*조사일: 2026-04-02*
