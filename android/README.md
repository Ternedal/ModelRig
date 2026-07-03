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
**Model picker**: "Genindlæs modeller" pulls `/api/v1/models` into a dropdown; the
choice persists via `TokenStore`.

## Two sources: rig and cloud
The app can talk to **your rig** (backend → local Ollama + RAG) **or directly to
Ollama Cloud** — the latter needs no rig running at all. Setup screen has both:

- **Ollama Cloud** (`net/CloudClient.kt`): streams from `https://ollama.com/api/chat`
  with your account API key. No rig required. Get a key at
  `ollama.com/settings/keys`; the model name is used directly (e.g. `gpt-oss:120b`).
- **Rig** (`net/ModelRigClient.kt`): pair with the backend for local models + RAG.

If both are configured, the chat screen shows a **Rig / Cloud** toggle. The choice
persists (`TokenStore.chatMode`).

**System instruction** (per source): each of rig and cloud has an optional
multiline system prompt (`TokenStore.rigSystem` / `cloudSystem`). When set, it's
sent as the first `role:"system"` message on every request for that source — so
you can run one persona against the rig (e.g. a terse backend dev) and another in
the cloud. Edit it on the setup screen; it saves as you type.

**Cloud key security**: the API key can cost real money if leaked, so it's
**encrypted at rest** with an AES-256-GCM key held in the **AndroidKeystore**
(`data/Crypto.kt`) — no external dependency (Jetpack Security's
EncryptedSharedPreferences is deprecated, so it's avoided). The rig device token
stays in plain prefs (LAN-only, lower value).

## UI
Material 3, dark-first, brand palette shared with the desktop client
(`ui/theme/Theme.kt`). Custom top bar (model dropdown + overflow: clear / unpair),
chat bubbles with auto-scroll, a streaming spinner on the in-flight reply, and a
multiline input.

**Markdown rendering** (`ui/Markdown.kt`) is a small, **dependency-free** Compose
renderer: headings, bold/italic, inline code, fenced **code blocks with a copy
button**, bullet/numbered lists, blockquotes, rules, and (styled) links. It does
**not** do tables, deep list nesting, or images — if you need those, `MarkdownText`
is the single call site to swap for `com.mikepenz:multiplatform-markdown-renderer-m3`.

Streaming + markdown interact deliberately: the reply is shown as **plain text
while streaming**, then re-rendered as **markdown once complete** — this avoids
re-parsing on every token and half-open code fences flickering. UI strings are in
Danish (inline; move to `res/values/strings.xml` to localize).

> None of the Kotlin (UI included) was compiled in the generator environment.
> First local build is the real test — see `CLIENT_BUILD_AND_TEST.md` at the repo
> root.

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
- Clickable links (`withLink`/`LinkAnnotation` on Compose 1.7+) and table support
  (swap in a full CommonMark renderer).
- Encrypted token storage (DataStore + Keystore).
- Retry/backoff + offline indicator; stop-generation (needs exposing OkHttp
  `call.cancel()` in `ModelRigClient`).
- Share the UI layer with desktop via Compose Multiplatform.
