# ModelRig — Android V1

Native Android client: **pair with the ModelRig backend, then chat**.

> Not built in the generator environment (no Android SDK there). Complete source
> — build in Android Studio or with a local Gradle + SDK.

## Scope (V1)
- **PairScreen** — enter the backend base URL + an `XXXX-XXXX` pairing code →
  `POST /api/v1/pair/claim` → the issued device token is stored.
- **ChatScreen** — `POST /api/v1/chat` with the bearer token; the backend proxies
  Ollama. Non-streaming.

Networking: OkHttp + `org.json` (both minimal, `org.json` is built into Android).
Token in `SharedPreferences` (see hardening note in `data/TokenStore.kt`).

**Streaming**: replies stream token-by-token (`chatStream`, OkHttp line reader).
**Model picker**: "Load models" pulls `/api/v1/models` into a dropdown; the choice
persists via `TokenStore`.

## The one thing that will bite you
The backend defaults to binding `127.0.0.1`. **A loopback-bound server is
unreachable from the phone.** On the server set `MODELRIG_HOST=0.0.0.0` (LAN) or a
Tailscale IP, then restart, then pair. The pairing screen repeats this warning.

Also: the app ships `usesCleartextTraffic="true"` because the backend is plain
HTTP on the LAN. Put it behind Tailscale/HTTPS for anything beyond your home net.

## Build
```bash
cd android
gradle wrapper --gradle-version 8.9   # once, if no wrapper present
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```
Or open the `android/` folder in Android Studio and Run.

## Config
- `applicationId` / namespace: `dk.ternedal.modelrig`
- `minSdk` 26, `targetSdk` 35
- AGP 8.5.2, Kotlin 2.0.21, Compose BOM 2024.09.03 (bump if your SDK needs it)

## Pairing flow, end to end
1. On the server (rig): `MODELRIG_HOST=0.0.0.0 ./modelrig-server`
2. Mint a code: `./modelrig-server -pair` (server stopped) **or** `POST
   /api/v1/pair/start` (server running).
3. In the app: enter `http://<rig-ip>:8080` + the code → **Pair**.
4. Chat.

## V1.1 ideas
- Encrypted token storage (DataStore + Keystore).
- Retry/backoff + offline indicator.
- Share the UI layer with desktop via Compose Multiplatform.
