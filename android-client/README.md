# Memory Hub — Android client

Kotlin / Compose / Gradle KTS skeleton that uploads photos and videos from the
device to the Memory Hub backend.

## Prereqs

- Android Studio Iguana (2023.2) or newer
- Android SDK 34
- JDK 17
- Kotlin 1.9

## First-time setup

1. Open Android Studio → **File > Open…** and pick `android-client/`.
2. Copy `local.properties.example` to `local.properties` and set `sdk.dir`.
3. Let Gradle sync.
4. Run **app** on an emulator (Android 8.0 / API 26 or newer).

## Command-line build

```powershell
cd android-client
# Windows
./gradlew.bat :app:assembleDebug
# macOS / Linux
./gradlew :app:assembleDebug
```

The Gradle wrapper JAR is not committed — Android Studio will generate it on
first sync (or run `gradle wrapper` from a system-installed Gradle 8.9).

## Backend base URL

The app defaults to `http://10.0.2.2:5000` (the emulator loopback to the host).
Change it on the sign-in screen or via **Settings → API base URL**.

## Features (Phase 1)

- Email / password sign-in against `POST /api/user/login`
- Google sign-in (Credential Manager) → `POST /api/user/oauth/google/callback`
- Watch-folder picker via `ACTION_OPEN_DOCUMENT_TREE`
  (persistent read permission is taken so it survives reboots)
- `UploadWorker` (WorkManager) uploads new files with
  - `NetworkType.UNMETERED` when *Wi-Fi only* is on
  - `requiresCharging = true` when *Charging only* is on
  - `BackoffPolicy.EXPONENTIAL` retries
- Room DB tracks `upload_state (uri, sha256, size, state, last_error, attempts, updated_at)`
- **Delete local after upload** toggle — only fires after the server has
  acknowledged both `POST /api/asset` *and* `GET /api/asset/<id>`
- Refresh tokens live in `EncryptedSharedPreferences`
- `AuthInterceptor` transparently refreshes on 401 via
  `POST /api/user/refresh` (JSON-body mode — the backend also accepts the
  refresh token as a cookie for the SPA)

## Tests

- `app/src/androidTest/…/UploadStateDaoTest.kt` — Room DAO smoke test
- `app/src/androidTest/…/UploadWorkerTest.kt` — WorkManager unit test that
  injects a fake `ApiService` returning 201 and asserts
  `upload_state.state == 'done'`
