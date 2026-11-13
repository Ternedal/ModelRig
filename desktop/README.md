# ModelRig — Desktop (Compose Desktop / JVM)

Desktop chat client for ModelRig with **local-first routing and Ollama Cloud fallback**.

> **Compile-verified** (2026-07-04): builds clean here (`./gradlew build` →
> `BUILD SUCCESSFUL`, Kotlin 2.0.21 + Compose Multiplatform 1.7.0). **Not run**
> — no display in the build sandbox, so actual on-screen behavior is still
> unverified at that checkpoint. The feature gaps listed then (palette, markdown,
> persistence, system prompts, RAG) have since been closed — see "Next" below;
> the original V2 desktop-parity audit is in `HISTORY.md` §4 pt. 5.

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
- **Brand colors** come from the generated `KalivTokens.kt` (single source
  `assets/design/kaliv-ui-guide/kaliv-ui-tokens.json`); `Brand.kt` reads them.
  UI strings are Danish, per project convention.

Routing lives in `net/ChatRouter.kt`; the HTTP client is `net/OllamaClient.kt`
(JDK `java.net.http`, no ktor). Theme mapping in `Brand.kt`.

**Streaming**: replies stream token-by-token (`chatStream`, NDJSON). The
cloud-fallback picks a source before the stream starts; a mid-stream failure is
surfaced rather than silently restarted on the other source (avoids double text).

**Model picker**: "Load models" pulls the model list (`/api/tags` locally, or
`/api/v1/models` when going via the backend) into a dropdown.

## Prerequisites
- JDK 21
- The committed Gradle wrapper (`./gradlew`; no system Gradle needed)

## Build & run
```bash
cd desktop
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
#   -> composeApp/build/compose/jars/Kaliv-<os>-x64-<version>.jar
#   run with: java -jar Kaliv-windows-x64-<version>.jar
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
Current `build.gradle.kts` pins Kotlin JVM `2.4.10`, Compose Compiler plugin
`2.4.10`, Kotlin serialization `2.4.10`, and Compose Multiplatform `1.11.1`.
The compile claim above is the historical 2026-07-04 checkpoint; current
compatibility is qualified by the repository's exact-head CI rather than by
rewriting that older evidence.

## Next (see `HISTORY.md` §4 pt. 5 for the original V2 desktop-parity plan)
> Markdown rendering: done (2026-07-04) — ported from Android, compiles clean.
> SQLite persistence: done (2026-07-04) — `data/DesktopChatDb.kt`, plain JDBC
> (`org.xerial:sqlite-jdbc`), DB at `~/.modelrig/modelrig.db`. Runtime-verified
> with a temporary smoke test (insert/read/list/delete/cascade, all passed) —
> removed after verification. Settings persist too (SQLite `setting` table,
> since v1.35.0); `deviceToken` and `cloudKey` are stored as Windows DPAPI
> envelopes (see SECURITY.md). Latest conversation auto-resumes on startup; no
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
