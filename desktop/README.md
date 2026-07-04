# ModelRig — Desktop (Compose Desktop / JVM)

Desktop chat client for ModelRig with **local-first routing and Ollama Cloud fallback**.

> **Compile-verified** (2026-07-04): builds clean here (`./gradlew build` →
> `BUILD SUCCESSFUL`, Kotlin 2.0.21 + Compose Multiplatform 1.7.0). **Not run**
> — no display in the build sandbox, so actual on-screen behavior is still
> unverified. Feature-wise this lags Android: no brand-real colors (`Brand.kt`
> still has the old invented palette), no markdown rendering, no persistence,
> no system prompts, no RAG — see `ROADMAP.md` §4 pt. 5 for the full audit and
> the planned lift to parity in V2.

## What it does
- Talks to any Ollama-compatible `/api/chat` endpoint.
- **Local source** can point at either local Ollama (`http://localhost:11434`,
  path `/api/chat`) or the ModelRig backend (`http://host:8080`, path
  `/api/v1/chat` + device token).
- **Cloud fallback**: if the local source fails (rig down, model not pulled, HTTP
  error) and an `OLLAMA_API_KEY` is set, it transparently retries against Ollama
  Cloud (`https://ollama.com`, model e.g. `gpt-oss:120b-cloud`). The header shows
  `RIG` or `CLOUD` so you always know who answered.
- **System prompt per source** (local + cloud, own field each in Settings):
  prepended as a `role:"system"` message before sending. Known simplification —
  the prompt follows the *preferred* source (the `preferLocal` toggle), not
  necessarily whichever one ends up answering after a fallback.
- **Brand colors** (`Brand.kt`) match Android's verified palette: Sapphire
  `#306CFC`, Champagne `#DEC08A`. UI strings are Danish, per project convention.

Routing lives in `net/ChatRouter.kt`; the HTTP client is `net/OllamaClient.kt`
(JDK `java.net.http`, no ktor). Brand tokens in `Brand.kt`.

**Streaming**: replies stream token-by-token (`chatStream`, NDJSON). The
cloud-fallback picks a source before the stream starts; a mid-stream failure is
surfaced rather than silently restarted on the other source (avoids double text).

**Model picker**: "Load models" pulls the model list (`/api/tags` locally, or
`/api/v1/models` when going via the backend) into a dropdown.

## Prerequisites
- JDK 21
- Gradle 8.x (or generate the wrapper — see below)

## Build & run
```bash
cd desktop
# no wrapper jar is shipped; create one once (needs a local Gradle):
gradle wrapper --gradle-version 8.9
./gradlew run
```
Or with a system Gradle directly:
```bash
cd desktop
gradle run
```

Package a native installer (msi/dmg/deb):
```bash
./gradlew packageDistributionForCurrentOs
```
Or a single runnable jar (bundles Compose Desktop's native rendering layer for
**whatever OS you build on** — build it on Windows to get a Windows-runnable
jar; a jar built on Linux/macOS won't run on Windows and vice versa):
```bash
./gradlew packageUberJarForCurrentOS
#   -> composeApp/build/compose/jars/ModelRig-<os>-x64-<version>.jar
#   run with: java -jar ModelRig-windows-x64-1.0.0.jar
```
Both were **confirmed working** in the Linux build sandbox (2026-07-04) — the
Kotlin/Compose Multiplatform version pairing compiles and packages cleanly.
Running the actual installer/jar on Windows still needs to happen on Windows.

## Config (env or in-app settings)
| Setting            | Env                  | Default                     |
|--------------------|----------------------|-----------------------------|
| Local base URL     | `MODELRIG_LOCAL_URL` | `http://localhost:11434`    |
| Device token       | `MODELRIG_TOKEN`     | *(empty)*                   |
| Cloud API key      | `OLLAMA_API_KEY`     | *(empty → no fallback)*     |
| Cloud model        | in-app               | `gpt-oss:120b-cloud`        |

All are editable at runtime in the Settings panel.

## Version note
`build.gradle.kts` pins Kotlin `2.0.21`, Compose Compiler plugin `2.0.21`,
Compose Multiplatform `1.7.0`. **Confirmed working together** (compiles clean,
2026-07-04) — no longer just plausible.

## Next (see `ROADMAP.md` §4 pt. 5 for the full V2 desktop-parity plan)
> Markdown rendering: done (2026-07-04) — ported from Android, compiles clean.
> SQLite persistence: done (2026-07-04) — `data/DesktopChatDb.kt`, plain JDBC
> (`org.xerial:sqlite-jdbc`), DB at `~/.modelrig/modelrig.db`. Runtime-verified
> with a temporary smoke test (insert/read/list/delete/cascade, all passed) —
> removed after verification. Settings (URLs/keys/models) still in-memory;
> only conversations persist. Latest conversation auto-resumes on startup; no
> conversation browser (list/switch/delete) yet.
> RAG mode: done (2026-07-04) — `net/RagClient.kt`, separate from
> ChatRouter (RAG only makes sense against the backend+worker). Same
> single-shot-per-question simplification as Android. Runtime-verified
> against a fake local HTTP server (NDJSON parsing, auth header, source
> filter all confirmed) — test removed after verification.

**Desktop is now at feature parity with Android's core chat capabilities**
(brand, Danish UI, system prompts, markdown, persistence, RAG). Remaining
gap: a conversation browser UI (list/switch/delete) — not in original scope,
natural next step if needed.
- Show a per-message source badge history and token/sec.
