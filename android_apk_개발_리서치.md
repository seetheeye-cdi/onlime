# Samsung S26 Ultra 개인용 Android APK 개발 종합 리서치

> 작성일: 2026-04-02
> 대상 디바이스: Samsung Galaxy S26 Ultra (Android 16 / One UI 8.5 / Snapdragon 8 Elite Gen 5)

---

## 목차

1. [프레임워크 비교: Native Kotlin vs Flutter vs React Native vs Jetpack Compose](#1-프레임워크-비교)
2. [최소 APK 개발 셋업](#2-최소-apk-개발-셋업)
3. [필수 퍼미션 상세](#3-필수-퍼미션-상세)
4. [백그라운드 서비스와 데이터 수집](#4-백그라운드-서비스와-데이터-수집)
5. [WorkManager 스케줄링](#5-workmanager-스케줄링)
6. [Samsung 디바이스 사이드로딩](#6-samsung-디바이스-사이드로딩)
7. [자체 서명 APK](#7-자체-서명-apk)
8. [Android 14/15/16 퍼미션 모델 변경사항](#8-android-141516-퍼미션-모델-변경사항)
9. [포그라운드 서비스 요구사항](#9-포그라운드-서비스-요구사항)
10. [Samsung 전용 API](#10-samsung-전용-api)
11. [최소 실행 가능 아키텍처](#11-최소-실행-가능-아키텍처)
12. [로컬 SQLite 데이터베이스 설계](#12-로컬-sqlite-데이터베이스-설계)
13. [최종 기술 스택 추천](#13-최종-기술-스택-추천)

---

## 1. 프레임워크 비교

### 비교표

| 항목 | Native Kotlin + Jetpack Compose | Flutter | React Native |
|------|-------------------------------|---------|-------------|
| **성능** | 100% (네이티브) | ~97% | ~94% |
| **시장 점유율** | Android 표준 | ~42% | ~38% |
| **언어** | Kotlin | Dart | JavaScript/TypeScript |
| **UI 프레임워크** | Jetpack Compose (선언형) | 자체 위젯 시스템 | React 컴포넌트 |
| **학습 곡선** | 중간 (Kotlin 필요) | 중간 (Dart 학습) | 낮음 (JS 경험 시) |
| **네이티브 API 접근** | 직접 접근 (최상) | 플러그인/채널 필요 | Bridge 필요 |
| **백그라운드 처리** | 완벽 지원 | 제한적 (플러그인 의존) | 매우 제한적 |
| **빌드 크기** | ~3-8 MB | ~15-25 MB | ~10-20 MB |
| **1인 개발 속도** | 중간 | 빠름 | 빠름 |
| **Android 전용 최적화** | 최상 | 중간 | 중간 |

### Jetpack Compose vs XML (기존 Android UI)

2025-2026년 기준으로 **Jetpack Compose가 확실한 승자**:

- **코드량 감소**: XML 대비 보일러플레이트 코드가 대폭 줄어듦
- **선언형 UI**: 상태 변경 시 필요한 부분만 자동으로 재구성(Recomposition)
- **실시간 프리뷰**: 변경사항 즉시 확인 가능
- **상태 관리 내장**: `@Composable` 함수가 상태 변경 시 자동 재구성
- **공식 지원**: Google이 공식적으로 새 프로젝트에 Compose 사용을 권장

### 개인용 데이터 수집 앱에 대한 판단

**결론: Native Kotlin + Jetpack Compose 강력 추천**

이유:
1. **백그라운드 처리가 핵심**: 데이터 수집 앱은 백그라운드 서비스, NotificationListenerService, AccessibilityService 등 네이티브 API에 깊이 의존함. Flutter/React Native는 이런 기능에 플러그인이나 브릿지를 통해 간접적으로만 접근 가능
2. **퍼미션 제어**: Android 14/15/16의 복잡한 퍼미션 모델을 직접 제어해야 함
3. **단일 플랫폼**: iOS 지원이 불필요하므로 크로스 플랫폼의 장점이 없음
4. **APK 크기**: 개인용이므로 경량화가 바람직 (3-8MB vs 15-25MB)
5. **Samsung 특화 API**: Knox SDK 등 Samsung 전용 기능은 네이티브에서만 완벽 지원

---

## 2. 최소 APK 개발 셋업

### 필수 도구

```
1. Android Studio (최신 안정 버전, 현재 Ladybug 이상)
2. JDK 17 이상
3. Android SDK (API Level 36 - Android 16 대상)
4. Kotlin 2.x
5. Gradle 8.x
```

### 최소 프로젝트 구조

```
app/
├── src/main/
│   ├── java/com/yourname/onlime/
│   │   ├── MainActivity.kt
│   │   ├── data/
│   │   │   ├── db/
│   │   │   │   ├── AppDatabase.kt
│   │   │   │   ├── dao/
│   │   │   │   └── entity/
│   │   │   └── repository/
│   │   ├── service/
│   │   │   ├── DataCollectionService.kt
│   │   │   ├── NotificationListenerService.kt
│   │   │   └── worker/
│   │   ├── ui/
│   │   │   ├── theme/
│   │   │   └── screen/
│   │   └── di/                    # Hilt DI
│   ├── AndroidManifest.xml
│   └── res/
├── build.gradle.kts
└── proguard-rules.pro
```

### build.gradle.kts 핵심 의존성

```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")          // Room용
    id("com.google.dagger.hilt.android")
}

android {
    namespace = "com.yourname.onlime"
    compileSdk = 36          // Android 16

    defaultConfig {
        applicationId = "com.yourname.onlime"
        minSdk = 34          // Android 14 최소 지원
        targetSdk = 36       // Android 16 타겟
        versionCode = 1
        versionName = "1.0"
    }

    buildFeatures {
        compose = true
    }

    // 개인용이므로 debug 빌드로도 충분
    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
}

dependencies {
    // Jetpack Compose
    implementation(platform("androidx.compose:compose-bom:2025.01.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose")
    implementation("androidx.navigation:navigation-compose")

    // Room (SQLite)
    implementation("androidx.room:room-runtime:2.7.0")
    implementation("androidx.room:room-ktx:2.7.0")
    ksp("androidx.room:room-compiler:2.7.0")

    // WorkManager
    implementation("androidx.work:work-runtime-ktx:2.10.0")

    // Hilt (DI)
    implementation("com.google.dagger:hilt-android:2.52")
    ksp("com.google.dagger:hilt-compiler:2.52")
    implementation("androidx.hilt:hilt-work:1.2.0")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    // DataStore (설정 저장)
    implementation("androidx.datastore:datastore-preferences:1.1.2")
}
```

### Play Store 없이 개발하는 핵심 포인트

- **Play Console 등록 불필요**: 개인 디바이스에 직접 설치하므로 개발자 계정($25) 불필요
- **빌드 방법**: Android Studio에서 `Build > Build Bundle(s) / APK(s) > Build APK(s)` 또는 터미널에서 `./gradlew assembleDebug`
- **APK 위치**: `app/build/outputs/apk/debug/app-debug.apk`
- **설치 방법**: USB 연결 후 `adb install app-debug.apk` 또는 APK 파일을 디바이스로 전송 후 직접 설치

---

## 3. 필수 퍼미션 상세

### AndroidManifest.xml 퍼미션 선언

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <!-- 알림 접근 -->
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
    <!-- NotificationListenerService는 별도 설정 필요 (아래 참조) -->

    <!-- 캘린더 -->
    <uses-permission android:name="android.permission.READ_CALENDAR" />
    <uses-permission android:name="android.permission.WRITE_CALENDAR" />

    <!-- 연락처 -->
    <uses-permission android:name="android.permission.READ_CONTACTS" />

    <!-- 저장소 (Android 14+ 세분화됨) -->
    <uses-permission android:name="android.permission.READ_MEDIA_IMAGES" />
    <uses-permission android:name="android.permission.READ_MEDIA_VIDEO" />
    <uses-permission android:name="android.permission.READ_MEDIA_AUDIO" />
    <!-- 전체 파일 접근이 필요한 경우 -->
    <uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE"
        tools:ignore="ScopedStorage" />

    <!-- 백그라운드 작업 -->
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />
    <uses-permission android:name="android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" />

    <!-- 네트워크 -->
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

    <!-- 정확한 알람 -->
    <uses-permission android:name="android.permission.SCHEDULE_EXACT_ALARM" />

    <!-- Accessibility Service (사용 시) -->
    <!-- AccessibilityService는 manifest에서 서비스로 선언 -->

    <application ...>

        <!-- NotificationListenerService 선언 -->
        <service
            android:name=".service.OnlimeNotificationListener"
            android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.service.notification.NotificationListenerService" />
            </intent-filter>
        </service>

        <!-- Foreground Service 선언 -->
        <service
            android:name=".service.DataCollectionService"
            android:foregroundServiceType="dataSync"
            android:exported="false" />

        <!-- AccessibilityService 선언 (필요시) -->
        <service
            android:name=".service.OnlimeAccessibilityService"
            android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.accessibilityservice.AccessibilityService" />
            </intent-filter>
            <meta-data
                android:name="android.accessibilityservice"
                android:resource="@xml/accessibility_config" />
        </service>

        <!-- Boot Receiver -->
        <receiver
            android:name=".receiver.BootReceiver"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>

    </application>
</manifest>
```

### 퍼미션별 런타임 요청 방법

```kotlin
// 런타임 퍼미션 요청 (Jetpack Compose)
@Composable
fun PermissionScreen() {
    val permissions = rememberMultiplePermissionsState(
        permissions = listOf(
            Manifest.permission.READ_CALENDAR,
            Manifest.permission.WRITE_CALENDAR,
            Manifest.permission.READ_CONTACTS,
            Manifest.permission.READ_MEDIA_IMAGES,
            Manifest.permission.POST_NOTIFICATIONS,
        )
    )

    LaunchedEffect(Unit) {
        if (!permissions.allPermissionsGranted) {
            permissions.launchMultiplePermissionRequest()
        }
    }
}

// NotificationListenerService 활성화 (시스템 설정으로 이동 필요)
fun openNotificationListenerSettings(context: Context) {
    val intent = Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS")
    context.startActivity(intent)
}

// AccessibilityService 활성화 (시스템 설정으로 이동 필요)
fun openAccessibilitySettings(context: Context) {
    val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
    context.startActivity(intent)
}
```

### 퍼미션 분류

| 퍼미션 | 유형 | 요청 방식 |
|--------|------|----------|
| READ_CALENDAR / WRITE_CALENDAR | 런타임 (위험) | 대화상자로 요청 |
| READ_CONTACTS | 런타임 (위험) | 대화상자로 요청 |
| READ_MEDIA_* | 런타임 (위험) | 대화상자로 요청 (부분 접근 가능) |
| POST_NOTIFICATIONS | 런타임 (Android 13+) | 대화상자로 요청 |
| FOREGROUND_SERVICE | 일반 | 자동 부여 |
| NotificationListenerService | 특수 | 시스템 설정에서 수동 활성화 |
| AccessibilityService | 특수 | 시스템 설정에서 수동 활성화 |
| SCHEDULE_EXACT_ALARM | 특수 (Android 14+) | 기본 거부, 사용자가 설정에서 허용 |
| MANAGE_EXTERNAL_STORAGE | 특수 | 시스템 설정에서 수동 허용 |

---

## 4. 백그라운드 서비스와 데이터 수집

### Foreground Service 구현

```kotlin
class DataCollectionService : Service() {

    companion object {
        const val CHANNEL_ID = "data_collection_channel"
        const val NOTIFICATION_ID = 1001
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = createNotification()

        // Android 14+: foregroundServiceType 명시 필수
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification,
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        )

        // 데이터 수집 로직 시작
        startDataCollection()

        return START_STICKY  // 시스템에 의해 종료되면 자동 재시작
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "데이터 수집",
            NotificationManager.IMPORTANCE_LOW  // 조용한 알림
        ).apply {
            description = "백그라운드 데이터 수집 중"
            setShowBadge(false)
        }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)
    }

    private fun createNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Onlime")
            .setContentText("데이터 수집 중...")
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun startDataCollection() {
        // CoroutineScope에서 데이터 수집 실행
        CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
            // 주기적 데이터 수집 로직
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
```

### NotificationListenerService 구현

```kotlin
class OnlimeNotificationListener : NotificationListenerService() {

    @Inject lateinit var notificationRepository: NotificationRepository

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val notification = sbn.notification
        val extras = notification.extras

        val data = NotificationData(
            packageName = sbn.packageName,
            title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: "",
            text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: "",
            timestamp = sbn.postTime,
            category = notification.category ?: "unknown"
        )

        // Room DB에 저장
        CoroutineScope(Dispatchers.IO).launch {
            notificationRepository.insert(data)
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        // 알림 제거 시 처리 (선택적)
    }
}
```

### 백그라운드 제약사항 (핵심)

Android 14/15/16에서의 백그라운드 실행 제한:

1. **Doze 모드**: 디바이스가 유휴 상태이면 네트워크 접근, JobScheduler, 알람 등이 지연됨
2. **앱 대기 버킷**: 사용 빈도에 따라 앱이 버킷에 분류되어 백그라운드 작업 제한
3. **배터리 최적화**: 시스템이 자동으로 백그라운드 앱을 제한
4. **Android 15 시간 제한**: `dataSync` 포그라운드 서비스는 24시간 내 최대 6시간 실행 가능
5. **Android 16 추가 제한**: 포그라운드 서비스에서 시작된 백그라운드 Job도 런타임 할당량 적용

**대응 전략**:
- `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` 퍼미션으로 배터리 최적화 예외 요청
- Foreground Service로 지속적 데이터 수집 보장
- WorkManager로 주기적 작업 스케줄링 (시스템이 적절한 시점에 실행)
- 개인용 앱이므로 Samsung 설정에서 "절전에서 제외" 수동 설정 가능

---

## 5. WorkManager 스케줄링

### 기본 설정

```kotlin
// 주기적 데이터 동기화 Worker
class DataSyncWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    @Inject lateinit var database: AppDatabase
    @Inject lateinit var dataProcessor: DataProcessor

    override suspend fun doWork(): Result {
        return try {
            // 1. 미처리 데이터 조회
            val pendingData = database.collectedDataDao().getPendingData()

            // 2. 데이터 처리 (분석, 집계 등)
            val processed = dataProcessor.process(pendingData)

            // 3. 처리 결과 저장
            database.processedDataDao().insertAll(processed)

            // 4. 원본 데이터 처리 완료 표시
            database.collectedDataDao().markAsProcessed(
                pendingData.map { it.id }
            )

            Result.success()
        } catch (e: Exception) {
            if (runAttemptCount < 3) {
                Result.retry()
            } else {
                Result.failure()
            }
        }
    }
}

// Worker 등록 (Application 클래스 또는 ViewModel에서)
fun schedulePeriodicSync(context: Context) {
    val constraints = Constraints.Builder()
        .setRequiresBatteryNotLow(true)          // 배터리 부족 시 실행 안 함
        .setRequiredNetworkType(NetworkType.NOT_REQUIRED)  // 로컬 처리이므로
        .build()

    val syncRequest = PeriodicWorkRequestBuilder<DataSyncWorker>(
        repeatInterval = 15,                      // 최소 15분 간격
        repeatIntervalTimeUnit = TimeUnit.MINUTES,
        flexInterval = 5,                          // 유연 구간 5분
        flexTimeUnit = TimeUnit.MINUTES
    )
        .setConstraints(constraints)
        .setBackoffCriteria(
            BackoffPolicy.EXPONENTIAL,
            WorkRequest.MIN_BACKOFF_MILLIS,
            TimeUnit.MILLISECONDS
        )
        .addTag("data_sync")
        .build()

    WorkManager.getInstance(context).enqueueUniquePeriodicWork(
        "periodic_data_sync",
        ExistingPeriodicWorkPolicy.KEEP,          // 이미 존재하면 유지
        syncRequest
    )
}

// 일회성 즉시 실행 작업
fun runImmediateSync(context: Context) {
    val request = OneTimeWorkRequestBuilder<DataSyncWorker>()
        .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
        .build()

    WorkManager.getInstance(context).enqueue(request)
}
```

### WorkManager 핵심 특성

| 특성 | 설명 |
|------|------|
| **최소 간격** | 주기적 작업은 최소 15분 간격 |
| **실행 보장** | 앱 재시작, 디바이스 재부팅 후에도 실행됨 |
| **제약 조건** | 네트워크, 배터리, 충전 상태 등 조건 설정 가능 |
| **체이닝** | 여러 작업을 순차/병렬로 연결 가능 |
| **Doze 호환** | Doze 모드에서도 유지 윈도우에 실행 |
| **재시도** | 지수 백오프로 자동 재시도 가능 |

### 포그라운드 서비스 vs WorkManager 사용 분기

```
데이터 수집 유형에 따른 선택:

[지속적 실시간 수집]          → Foreground Service
  - 알림 모니터링
  - 실시간 센서 데이터

[주기적 배치 처리]           → WorkManager (Periodic)
  - 15분마다 데이터 집계
  - 일일 리포트 생성
  - 캘린더/연락처 동기화

[특정 조건 트리거]           → WorkManager (OneTime + Constraints)
  - 충전 중일 때 무거운 처리
  - 네트워크 연결 시 클라우드 백업

[즉시 1회 실행]             → WorkManager (Expedited OneTime)
  - 사용자가 수동 트리거한 동기화
```

---

## 6. Samsung 디바이스 사이드로딩

### 방법 1: ADB를 통한 설치 (추천)

```bash
# 1. USB 디버깅 활성화
#    설정 > 휴대전화 정보 > 소프트웨어 정보 > 빌드번호 7회 탭
#    설정 > 개발자 옵션 > USB 디버깅 활성화

# 2. USB 연결 후 디바이스 확인
adb devices

# 3. APK 설치
adb install app-debug.apk

# 4. 업데이트 설치 (기존 데이터 유지)
adb install -r app-debug.apk

# 5. 특정 사용자에게 설치
adb install --user current app-debug.apk
```

### 방법 2: 파일 전송 후 직접 설치

```
1. APK 파일을 디바이스로 전송 (USB, 클라우드, 이메일 등)
2. 설정 > 앱 > 우측 상단 점 3개 > 특별한 접근 > 출처를 알 수 없는 앱 설치
3. 설치에 사용할 앱 (내 파일, Chrome 등)에 "이 출처 허용" 활성화
4. 파일 관리자에서 APK 파일 탭하여 설치
```

### 방법 3: Android Studio 직접 설치

```
1. USB 연결
2. Android Studio에서 Run 버튼 클릭 (또는 Shift+F10)
3. 연결된 Samsung S26 Ultra 선택
4. 자동으로 빌드 + 설치 + 실행
```

### Samsung 특이사항

- **24시간 지연 정책**: Android 최신 버전에서는 "출처를 알 수 없는 앱" 최초 활성화 후 24시간 대기 필요할 수 있음. **ADB를 통한 설치는 이 제한을 우회** 가능
- **앱별 허용**: One UI에서는 앱마다 개별적으로 "출처를 알 수 없는 앱 설치" 권한을 부여해야 함
- **개발자 인증**: Android 16에서 Google이 비-ADB APK 설치에 개발자 등록을 요구할 수 있다는 보도가 있었으나, ADB 설치는 영향 없음

---

## 7. 자체 서명 APK

### Debug 키스토어 (개발/테스트용)

```bash
# Android Studio가 자동 생성하는 debug.keystore
# 위치: ~/.android/debug.keystore
# 비밀번호: android
# 유효기간: 365일 (만료 시 자동 재생성)
# 별칭: androiddebugkey

# 수동 생성
keytool -genkey -v \
  -keystore ~/.android/debug.keystore \
  -storepass android \
  -alias androiddebugkey \
  -keypass android \
  -keyalg RSA \
  -keysize 2048 \
  -validity 365 \
  -dname "CN=Android Debug,O=Android,C=US"
```

### Release 키스토어 (개인용 장기 사용 추천)

```bash
# 개인용 Release 키 생성 (25년 유효)
keytool -genkeypair -v \
  -keystore onlime-release.jks \
  -storetype JKS \
  -keyalg RSA \
  -keysize 2048 \
  -validity 9125 \
  -alias onlime \
  -storepass [강력한비밀번호] \
  -keypass [강력한비밀번호] \
  -dname "CN=Onlime Personal, OU=Personal, O=Onlime, L=Seoul, ST=Seoul, C=KR"
```

### build.gradle.kts에서 서명 설정

```kotlin
android {
    signingConfigs {
        create("release") {
            storeFile = file("../keystore/onlime-release.jks")
            storePassword = System.getenv("KEYSTORE_PASSWORD") ?: "your-password"
            keyAlias = "onlime"
            keyPassword = System.getenv("KEY_PASSWORD") ?: "your-password"
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
}
```

### 서명 관련 핵심 사항

- **개인 사용**: Play Store 배포가 아니므로 debug 키스토어로도 충분하나, 앱 업데이트 시 동일한 키로 서명해야 함
- **release 키 권장 이유**: debug 키는 365일 만료되어 재설치가 필요해질 수 있음. Release 키(25년)를 만들면 장기간 업데이트 가능
- **키 분실 주의**: 키를 잃으면 기존 앱을 업데이트할 수 없고 재설치(데이터 손실)가 필요
- **키 백업**: 키스토어 파일과 비밀번호를 안전하게 백업 (1Password, 별도 저장소 등)
- **APK 서명 스킴**: v1(JAR), v2(APK Signature Scheme v2), v3 모두 지원. Android Studio가 자동 처리

---

## 8. Android 14/15/16 퍼미션 모델 변경사항

### Android 14 (API 34) 주요 변경

| 변경사항 | 영향 | 대응 |
|----------|------|------|
| **사진/동영상 부분 접근** | 사용자가 "선택한 사진만" 허용 가능 | `READ_MEDIA_VISUAL_USER_SELECTED` 퍼미션 추가 처리 |
| **포그라운드 서비스 타입 필수** | manifest에 `foregroundServiceType` 미선언 시 크래시 | 모든 포그라운드 서비스에 타입 명시 |
| **정확한 알람 기본 거부** | `SCHEDULE_EXACT_ALARM` 신규 앱에 자동 부여 안 됨 | 사용자에게 설정 화면 안내 또는 `SCHEDULE_EXACT_ALARM` 대신 WorkManager 사용 |
| **전체 화면 인텐트 제한** | 전화/알람 앱만 전체 화면 알림 가능 | 해당 없음 (데이터 수집 앱) |

### Android 15 (API 35) 주요 변경

| 변경사항 | 영향 | 대응 |
|----------|------|------|
| **dataSync 서비스 6시간 제한** | 24시간 내 최대 6시간 실행 | 지속 수집은 다른 서비스 타입 고려, 또는 6시간 주기로 재시작 설계 |
| **mediaProcessing 서비스 신설** | 미디어 처리 전용 타입 추가 | 미디어 관련 처리 시 해당 타입 사용 |
| **BOOT_COMPLETED 제한** | 부팅 시 dataSync 포그라운드 서비스 시작 불가 | WorkManager로 부팅 후 작업 예약 |
| **알림 쿨다운** | 짧은 시간 내 다수 알림 발송 시 자동 그룹화/억제 | 알림 발송 빈도 조절 |
| **Play Protect 퍼미션 회수** | 유해 앱으로 판정 시 퍼미션 자동 회수 | 개인용/사이드로드 앱에는 영향 제한적 |

### Android 16 (API 36) - S26 Ultra 탑재

| 변경사항 | 영향 | 대응 |
|----------|------|------|
| **FGS에서 시작된 Job 할당량 적용** | 포그라운드 서비스에서 시작한 백그라운드 Job도 런타임 할당량 제한 | Job 실행 시간 최적화, 청크 단위 처리 |
| **건강 데이터 퍼미션 세분화** | `BODY_SENSORS` 대신 세분화된 `android.permission.health.*` 퍼미션 | 건강 데이터 수집 시 개별 퍼미션 요청 |
| **백그라운드 액티비티 시작 Strict 모드** | 백그라운드에서 액티비티 시작 차단 감지 | 백그라운드에서는 알림을 통해 사용자를 앱으로 유도 |
| **SYSTEM_ALERT_WINDOW + FGS 조합 제한** | 오버레이 윈도우가 실제로 표시 중이어야 FGS 시작 가능 | 오버레이에 의존하지 않는 FGS 시작 방식 사용 |

### 개인용 사이드로드 앱의 장점

Play Store를 거치지 않으므로:
- Play Protect의 자동 퍼미션 회수 위험이 낮음
- Play Console의 foreground service 타입 신고 불필요
- AccessibilityService 사용에 대한 Play Store 정책 심사 없음
- 다만, OS 수준의 퍼미션 모델은 동일하게 적용됨

---

## 9. 포그라운드 서비스 요구사항

### Android 14+ 포그라운드 서비스 타입 목록

```
camera              카메라 사용
connectedDevice     연결된 기기 통신
dataSync            데이터 동기화 (24시간 내 6시간 제한 - Android 15+)
health              건강/피트니스
location            위치 추적
mediaPlayback       미디어 재생
mediaProjection     화면 미러링/녹화
microphone          마이크 사용
phoneCall           전화 관련
remoteMessaging     원격 메시징
shortService        짧은 작업 (< 3분)
specialUse          위 카테고리에 해당하지 않는 특수 용도
systemExempted      시스템 면제 (시스템 앱 전용)
mediaProcessing     미디어 처리 (Android 15 신설)
```

### 데이터 수집 앱에 적합한 타입 조합

```xml
<!-- 데이터 수집/동기화 -->
<service
    android:name=".service.DataCollectionService"
    android:foregroundServiceType="dataSync"
    android:exported="false" />

<!-- 특수 용도 (알림 수집 등 명확한 카테고리 없는 경우) -->
<service
    android:name=".service.SpecialCollectionService"
    android:foregroundServiceType="specialUse"
    android:exported="false" />
```

### 포그라운드 서비스 시작 제한 우회

```kotlin
// Android 12+: 백그라운드에서 포그라운드 서비스 시작 제한
// 허용되는 경우:
// 1. 사용자가 앱과 상호작용 중 (포그라운드 상태)
// 2. 기존 포그라운드 서비스가 있는 경우
// 3. SYSTEM_ALERT_WINDOW 퍼미션 + 표시 중인 오버레이
// 4. 정확한 알람에서 시작
// 5. RECEIVE_BOOT_COMPLETED에서 시작 (일부 타입 제한)

// 권장 패턴: WorkManager에서 포그라운드 서비스 시작
class DataCollectionWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    override suspend fun getForegroundInfo(): ForegroundInfo {
        return ForegroundInfo(
            NOTIFICATION_ID,
            createNotification(),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        )
    }

    override suspend fun doWork(): Result {
        setForeground(getForegroundInfo())
        // 데이터 수집 수행
        return Result.success()
    }
}
```

---

## 10. Samsung 전용 API

### Samsung Knox SDK

**개요**: Knox SDK는 삼성 디바이스 전용 확장 API로, Android Enterprise 기능을 넘어서는 삼성 독점 기능을 제공한다.

**사용 가능한 기능**:
- 계정 관리
- 앱 관리 (설치/제거/제어)
- 연결 관리 (Wi-Fi, Bluetooth, NFC 등)
- 커스터마이징 (알림바, 키가드, 테마)
- 디바이스 설정 제어
- 보안 설정 (암호화, 생체 인증 등)
- VPN 설정

**접근 방법**: Samsung Knox Partner Program 가입 필요. 개인 개발자도 가입 가능하나 심사가 있을 수 있음.

**현재 SDK 버전**: API Level 39 (2025년 7월 기준)

### Samsung 특화 기능 (Knox 없이 사용 가능)

```kotlin
// Samsung 디바이스 확인
fun isSamsungDevice(): Boolean {
    return Build.MANUFACTURER.equals("samsung", ignoreCase = true)
}

// Samsung Edge Panel 지원
// Samsung Good Lock 모듈과의 연동
// Samsung Health SDK (건강 데이터 연동)
// Samsung Pay SDK (결제 - 해당 없음)
```

### S26 Ultra 특화 고려사항

- **Android 16 + One UI 8.5**: 최신 OS에서의 퍼미션 및 백그라운드 정책 준수 필요
- **Snapdragon 8 Elite Gen 5**: 충분한 처리 성능, 온디바이스 ML 처리 가능
- **256GB/512GB/1TB 저장소**: 로컬 데이터 저장 공간 충분
- **5,000mAh 배터리 + 60W 충전**: 백그라운드 서비스 운용에 유리
- **Privacy Display**: 개인 정보 보호 기능으로 데이터 수집 앱에 적합

### 개인용 앱에서 Knox SDK 필요성

**결론: 대부분의 경우 불필요**

개인용 데이터 수집 앱은 표준 Android API만으로 충분하다. Knox SDK는 주로 엔터프라이즈 MDM(Mobile Device Management) 용도이며, 개인 데이터 수집에 필요한 알림 접근, 캘린더, 연락처, 저장소 등은 모두 표준 Android API로 처리 가능하다.

---

## 11. 최소 실행 가능 아키텍처

### MVVM + Clean Architecture (간소화 버전)

```
┌─────────────────────────────────────────────────────────┐
│                    UI Layer (Compose)                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │ Dashboard │  │ Settings │  │ Data Browser Screen   │  │
│  │  Screen   │  │  Screen  │  │                       │  │
│  └─────┬─────┘  └─────┬────┘  └───────────┬───────────┘  │
│        │              │                    │              │
│  ┌─────┴──────────────┴────────────────────┴───────────┐ │
│  │              ViewModels (State Holders)               │ │
│  │  DashboardVM  │  SettingsVM  │  DataBrowserVM       │ │
│  └──────────────────────┬──────────────────────────────┘ │
├─────────────────────────┼────────────────────────────────┤
│                  Domain Layer                             │
│  ┌──────────────────────┴──────────────────────────────┐ │
│  │              Use Cases (비즈니스 로직)                │ │
│  │  CollectDataUseCase  │  ProcessDataUseCase          │ │
│  │  SyncCalendarUseCase │  GenerateReportUseCase       │ │
│  └──────────────────────┬──────────────────────────────┘ │
├─────────────────────────┼────────────────────────────────┤
│                   Data Layer                              │
│  ┌──────────────┐  ┌───┴──────────┐  ┌────────────────┐ │
│  │  Repositories │  │   Services   │  │   Workers      │ │
│  │              │  │              │  │                │ │
│  │ Notification │  │ FG Service   │  │ DataSync       │ │
│  │ Calendar     │  │ Notification │  │ Cleanup        │ │
│  │ Contact      │  │ Listener     │  │ Report         │ │
│  │ AppUsage     │  │ Accessibility│  │                │ │
│  └──────┬───────┘  └──────────────┘  └────────────────┘ │
│         │                                                │
│  ┌──────┴─────────────────────────────────────────────┐  │
│  │              Room Database (SQLite)                  │  │
│  │  notifications │ calendar_events │ contacts         │  │
│  │  app_usage     │ processed_data  │ settings         │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 핵심 모듈 구조

```
com.yourname.onlime/
├── OnlimeApplication.kt          # Hilt Application
├── MainActivity.kt               # 단일 Activity (Compose Navigation)
│
├── ui/                           # UI Layer
│   ├── navigation/
│   │   └── NavGraph.kt
│   ├── theme/
│   │   └── Theme.kt
│   ├── dashboard/
│   │   ├── DashboardScreen.kt
│   │   └── DashboardViewModel.kt
│   ├── settings/
│   │   ├── SettingsScreen.kt
│   │   └── SettingsViewModel.kt
│   └── databrowser/
│       ├── DataBrowserScreen.kt
│       └── DataBrowserViewModel.kt
│
├── domain/                       # Domain Layer
│   ├── model/                    # 도메인 모델
│   │   ├── CollectedNotification.kt
│   │   ├── CalendarEvent.kt
│   │   └── ProcessedData.kt
│   ├── usecase/                  # 유스케이스
│   │   ├── CollectNotificationsUseCase.kt
│   │   ├── SyncCalendarUseCase.kt
│   │   └── ProcessDataUseCase.kt
│   └── repository/               # Repository 인터페이스
│       ├── NotificationRepository.kt
│       ├── CalendarRepository.kt
│       └── ContactRepository.kt
│
├── data/                         # Data Layer
│   ├── db/
│   │   ├── AppDatabase.kt
│   │   ├── entity/
│   │   │   ├── NotificationEntity.kt
│   │   │   ├── CalendarEventEntity.kt
│   │   │   ├── ContactEntity.kt
│   │   │   └── ProcessedDataEntity.kt
│   │   ├── dao/
│   │   │   ├── NotificationDao.kt
│   │   │   ├── CalendarEventDao.kt
│   │   │   ├── ContactDao.kt
│   │   │   └── ProcessedDataDao.kt
│   │   └── converter/
│   │       └── TypeConverters.kt
│   ├── repository/               # Repository 구현체
│   │   ├── NotificationRepositoryImpl.kt
│   │   ├── CalendarRepositoryImpl.kt
│   │   └── ContactRepositoryImpl.kt
│   └── source/                   # 데이터 소스
│       ├── CalendarDataSource.kt
│       └── ContactDataSource.kt
│
├── service/                      # 백그라운드 서비스
│   ├── DataCollectionService.kt
│   ├── OnlimeNotificationListener.kt
│   ├── OnlimeAccessibilityService.kt
│   └── worker/
│       ├── DataSyncWorker.kt
│       ├── CleanupWorker.kt
│       └── ReportWorker.kt
│
├── receiver/
│   └── BootReceiver.kt
│
└── di/                           # Hilt 의존성 주입
    ├── AppModule.kt
    ├── DatabaseModule.kt
    ├── RepositoryModule.kt
    └── WorkerModule.kt
```

### Hilt 의존성 주입 설정

```kotlin
// di/DatabaseModule.kt
@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(
        @ApplicationContext context: Context
    ): AppDatabase {
        return Room.databaseBuilder(
            context,
            AppDatabase::class.java,
            "onlime.db"
        )
            .addMigrations(MIGRATION_1_2)
            .build()
    }

    @Provides
    fun provideNotificationDao(db: AppDatabase) = db.notificationDao()

    @Provides
    fun provideCalendarEventDao(db: AppDatabase) = db.calendarEventDao()
}

// di/RepositoryModule.kt
@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {

    @Binds
    abstract fun bindNotificationRepository(
        impl: NotificationRepositoryImpl
    ): NotificationRepository

    @Binds
    abstract fun bindCalendarRepository(
        impl: CalendarRepositoryImpl
    ): CalendarRepository
}
```

---

## 12. 로컬 SQLite 데이터베이스 설계

### Entity 설계

```kotlin
// === 알림 데이터 ===
@Entity(
    tableName = "notifications",
    indices = [
        Index("package_name"),
        Index("timestamp"),
        Index("is_processed")
    ]
)
data class NotificationEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "package_name") val packageName: String,
    @ColumnInfo(name = "app_name") val appName: String,
    val title: String,
    val text: String,
    val category: String,
    val timestamp: Long,                    // System.currentTimeMillis()
    @ColumnInfo(name = "is_processed") val isProcessed: Boolean = false,
    @ColumnInfo(name = "created_at") val createdAt: Long = System.currentTimeMillis()
)

// === 캘린더 이벤트 ===
@Entity(
    tableName = "calendar_events",
    indices = [
        Index("calendar_id"),
        Index("start_time"),
        Index("sync_timestamp")
    ]
)
data class CalendarEventEntity(
    @PrimaryKey val eventId: Long,          // 시스템 캘린더 이벤트 ID
    @ColumnInfo(name = "calendar_id") val calendarId: Long,
    val title: String,
    val description: String?,
    val location: String?,
    @ColumnInfo(name = "start_time") val startTime: Long,
    @ColumnInfo(name = "end_time") val endTime: Long,
    @ColumnInfo(name = "all_day") val allDay: Boolean,
    val organizer: String?,
    val attendees: String?,                 // JSON 직렬화
    @ColumnInfo(name = "sync_timestamp") val syncTimestamp: Long = System.currentTimeMillis()
)

// === 연락처 ===
@Entity(
    tableName = "contacts",
    indices = [
        Index("contact_id", unique = true),
        Index("sync_timestamp")
    ]
)
data class ContactEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "contact_id") val contactId: String,    // 시스템 연락처 ID
    @ColumnInfo(name = "display_name") val displayName: String,
    @ColumnInfo(name = "phone_numbers") val phoneNumbers: String?,  // JSON
    @ColumnInfo(name = "email_addresses") val emailAddresses: String?, // JSON
    val organization: String?,
    val note: String?,
    @ColumnInfo(name = "last_contacted") val lastContacted: Long?,
    @ColumnInfo(name = "sync_timestamp") val syncTimestamp: Long = System.currentTimeMillis()
)

// === 처리된 데이터 (분석 결과) ===
@Entity(
    tableName = "processed_data",
    indices = [
        Index("data_type"),
        Index("date"),
        Index("created_at")
    ]
)
data class ProcessedDataEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "data_type") val dataType: String,    // "daily_summary", "weekly_report" 등
    val date: String,                       // "2026-04-02" 형식
    @ColumnInfo(name = "json_payload") val jsonPayload: String,  // 구조화된 JSON 데이터
    val metadata: String?,                  // 추가 메타데이터 JSON
    @ColumnInfo(name = "created_at") val createdAt: Long = System.currentTimeMillis()
)

// === 앱 사용 로그 ===
@Entity(
    tableName = "app_usage_logs",
    indices = [
        Index("package_name"),
        Index("date"),
        Index("timestamp")
    ]
)
data class AppUsageLogEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    @ColumnInfo(name = "package_name") val packageName: String,
    @ColumnInfo(name = "app_name") val appName: String,
    val date: String,                       // "2026-04-02"
    @ColumnInfo(name = "usage_duration_ms") val usageDurationMs: Long,
    @ColumnInfo(name = "launch_count") val launchCount: Int,
    val timestamp: Long
)

// === 키-값 설정 저장 ===
@Entity(tableName = "app_settings")
data class AppSettingEntity(
    @PrimaryKey val key: String,
    val value: String,
    @ColumnInfo(name = "updated_at") val updatedAt: Long = System.currentTimeMillis()
)
```

### DAO 설계

```kotlin
@Dao
interface NotificationDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(notification: NotificationEntity): Long

    @Query("SELECT * FROM notifications WHERE is_processed = 0 ORDER BY timestamp DESC")
    suspend fun getPendingNotifications(): List<NotificationEntity>

    @Query("SELECT * FROM notifications WHERE timestamp BETWEEN :startTime AND :endTime ORDER BY timestamp DESC")
    suspend fun getNotificationsByTimeRange(startTime: Long, endTime: Long): List<NotificationEntity>

    @Query("SELECT * FROM notifications WHERE package_name = :packageName ORDER BY timestamp DESC LIMIT :limit")
    suspend fun getByPackage(packageName: String, limit: Int = 100): List<NotificationEntity>

    @Query("UPDATE notifications SET is_processed = 1 WHERE id IN (:ids)")
    suspend fun markAsProcessed(ids: List<Long>)

    @Query("SELECT package_name, COUNT(*) as count FROM notifications WHERE timestamp > :since GROUP BY package_name ORDER BY count DESC")
    suspend fun getNotificationCountByApp(since: Long): List<AppNotificationCount>

    // Flow로 실시간 관찰
    @Query("SELECT * FROM notifications ORDER BY timestamp DESC LIMIT :limit")
    fun observeRecentNotifications(limit: Int = 50): Flow<List<NotificationEntity>>

    @Query("DELETE FROM notifications WHERE timestamp < :before")
    suspend fun deleteOlderThan(before: Long): Int
}

data class AppNotificationCount(
    @ColumnInfo(name = "package_name") val packageName: String,
    val count: Int
)

@Dao
interface CalendarEventDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(events: List<CalendarEventEntity>)

    @Query("SELECT * FROM calendar_events WHERE start_time BETWEEN :startTime AND :endTime ORDER BY start_time")
    suspend fun getEventsByDateRange(startTime: Long, endTime: Long): List<CalendarEventEntity>

    @Query("SELECT * FROM calendar_events WHERE start_time >= :fromTime ORDER BY start_time LIMIT :limit")
    fun observeUpcomingEvents(fromTime: Long, limit: Int = 20): Flow<List<CalendarEventEntity>>

    @Query("DELETE FROM calendar_events WHERE end_time < :before")
    suspend fun deleteOlderThan(before: Long): Int
}

@Dao
interface ProcessedDataDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(data: ProcessedDataEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(data: List<ProcessedDataEntity>)

    @Query("SELECT * FROM processed_data WHERE data_type = :type ORDER BY date DESC LIMIT :limit")
    suspend fun getByType(type: String, limit: Int = 30): List<ProcessedDataEntity>

    @Query("SELECT * FROM processed_data WHERE data_type = :type AND date = :date")
    suspend fun getByTypeAndDate(type: String, date: String): ProcessedDataEntity?

    @Query("SELECT * FROM processed_data ORDER BY created_at DESC LIMIT :limit")
    fun observeRecent(limit: Int = 20): Flow<List<ProcessedDataEntity>>
}
```

### Database 클래스

```kotlin
@Database(
    entities = [
        NotificationEntity::class,
        CalendarEventEntity::class,
        ContactEntity::class,
        ProcessedDataEntity::class,
        AppUsageLogEntity::class,
        AppSettingEntity::class
    ],
    version = 1,
    exportSchema = true    // 스키마 내보내기 (마이그레이션용)
)
@TypeConverters(Converters::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun notificationDao(): NotificationDao
    abstract fun calendarEventDao(): CalendarEventDao
    abstract fun contactDao(): ContactDao
    abstract fun processedDataDao(): ProcessedDataDao
    abstract fun appUsageLogDao(): AppUsageLogDao
    abstract fun appSettingDao(): AppSettingDao
}

class Converters {
    @TypeConverter
    fun fromStringList(value: String?): List<String>? {
        return value?.let {
            Json.decodeFromString<List<String>>(it)
        }
    }

    @TypeConverter
    fun toStringList(list: List<String>?): String? {
        return list?.let {
            Json.encodeToString(it)
        }
    }
}
```

### 데이터 용량 추정 및 관리

```
일일 데이터 예상:
- 알림: ~200-500건/일 × ~500 bytes = ~100-250 KB/일
- 캘린더: ~5-20건/동기화 × ~300 bytes = ~1.5-6 KB
- 연락처: ~500건(1회) × ~500 bytes = ~250 KB (초기)
- 처리 결과: ~10-50건/일 × ~1 KB = ~10-50 KB/일
- 앱 사용: ~20-50건/일 × ~200 bytes = ~4-10 KB/일

월간: ~5-10 MB
연간: ~60-120 MB

→ S26 Ultra 256GB 최소 저장소 기준, 2000년치 이상 저장 가능
→ 그래도 오래된 원본 데이터는 주기적 정리 권장 (90일 이후 삭제)
```

### 데이터 정리 Worker

```kotlin
class CleanupWorker(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    @Inject lateinit var database: AppDatabase

    override suspend fun doWork(): Result {
        val ninetyDaysAgo = System.currentTimeMillis() - (90L * 24 * 60 * 60 * 1000)

        // 처리 완료된 90일 이전 알림 삭제
        database.notificationDao().deleteOlderThan(ninetyDaysAgo)

        // 종료된 90일 이전 캘린더 이벤트 삭제
        database.calendarEventDao().deleteOlderThan(ninetyDaysAgo)

        return Result.success()
    }
}
```

---

## 13. 최종 기술 스택 추천

### 확정 기술 스택

```
┌─────────────────────────────────────────────────────────┐
│                    추천 기술 스택                         │
├─────────────────────────────────────────────────────────┤
│ 언어        │ Kotlin 2.x                                │
│ UI          │ Jetpack Compose + Material 3              │
│ 아키텍처     │ MVVM + 간소화된 Clean Architecture        │
│ DI          │ Hilt (Dagger 기반)                        │
│ DB          │ Room (SQLite 추상화)                       │
│ 비동기       │ Kotlin Coroutines + Flow                  │
│ 백그라운드   │ Foreground Service + WorkManager           │
│ 네비게이션   │ Navigation Compose                        │
│ 설정 저장    │ DataStore Preferences                     │
│ 직렬화       │ Kotlinx Serialization                     │
│ 빌드        │ Gradle (Kotlin DSL) + Version Catalog     │
│ 타겟 SDK    │ API 36 (Android 16)                       │
│ 최소 SDK    │ API 34 (Android 14)                       │
│ 서명        │ Self-signed Release Keystore (25년 유효)   │
│ 설치        │ ADB 사이드로드                             │
└─────────────────────────────────────────────────────────┘
```

### 이 스택을 선택한 이유 요약

| 선택 | 이유 |
|------|------|
| **Kotlin (Flutter/RN 아님)** | 백그라운드 서비스, NotificationListener, Accessibility 등 네이티브 API 직접 접근 필수. 크로스 플랫폼 불필요 |
| **Jetpack Compose (XML 아님)** | 2026년 기준 Android UI 표준. 코드량 절감, 선언형 UI, 공식 권장 |
| **MVVM (MVI 아님)** | 1인 개발 규모에서 MVI는 과도한 복잡성. MVVM이 학습 곡선과 생산성 균형 최적 |
| **Hilt (Koin 아님)** | 컴파일 타임 검증, Google 공식 지원, WorkManager/서비스와의 통합 우수 |
| **Room (SQLDelight 아님)** | Android 표준, Compose/Flow와 자연스러운 통합, 풍부한 레퍼런스 |
| **Coroutines (RxJava 아님)** | Kotlin 네이티브, Room/WorkManager와 기본 통합, 코드 간결성 |
| **ADB 사이드로드** | Play Store 불필요, 24시간 지연 없음, 가장 단순한 배포 방법 |

### 개발 로드맵 (1인 개발자 기준)

```
Phase 1 (1-2주): 프로젝트 기반 구축
├── Android Studio 프로젝트 생성
├── Gradle 의존성 설정
├── Room Database + Entity/DAO 구현
├── Hilt DI 설정
├── 기본 Compose UI (Dashboard)
└── APK 빌드 및 S26 Ultra 사이드로드 테스트

Phase 2 (2-3주): 데이터 수집 구현
├── NotificationListenerService 구현
├── 캘린더 데이터 읽기 구현
├── 연락처 데이터 읽기 구현
├── Foreground Service 구현
├── 퍼미션 요청 흐름 구현
└── 수집 데이터 Room 저장

Phase 3 (1-2주): 백그라운드 처리
├── WorkManager 주기적 동기화 설정
├── 데이터 처리/집계 로직
├── 부팅 시 자동 시작
├── 배터리 최적화 예외 설정
└── 데이터 정리 Worker

Phase 4 (1-2주): UI 및 마무리
├── 데이터 브라우저 화면
├── 설정 화면
├── 통계/차트 (Vico 또는 직접 Canvas)
├── Release 서명 설정
└── 최적화 및 테스트
```

### 주의사항

1. **키스토어 백업 필수**: Release 키스토어 분실 시 앱 업데이트 불가 (재설치 + 데이터 손실)
2. **Room 마이그레이션**: 스키마 변경 시 마이그레이션 코드를 반드시 작성할 것 (데이터 보존)
3. **배터리 최적화**: Samsung One UI의 "앱 절전" 설정에서 수동으로 예외 추가 필요
4. **Android 16 정책 변화**: S26 Ultra가 Android 16을 탑재하므로 최신 퍼미션/백그라운드 제한 준수
5. **데이터 암호화**: 민감한 개인 데이터를 저장하므로, Room에 SQLCipher 적용 또는 Android Keystore 활용 고려
6. **Accessibility Service 주의**: 개인용이라도 남용 시 보안 위험. 정말 필요한 경우에만 사용

---

> 이 리서치는 2026년 4월 기준 최신 정보를 바탕으로 작성되었습니다.
> Samsung Galaxy S26 Ultra (Android 16 / One UI 8.5) 대상입니다.
