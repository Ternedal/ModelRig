# ModelRig

A local-first AI platform: run models on your own hardware via Ollama, reach them
from a desktop app (**Kaliv** on Windows), an Android phone (**Kaliv**), and the **Kaliv VR** OpenXR client, with
Danish voice (ASR→LLM→TTS, streamed sentence-by-sentence), RAG document ingest
(pdf/docx/pptx/html/photos), a confirmation-gated tool layer, and an optional
Ollama Cloud brain for when local isn't enough. The backend keeps the ModelRig
name; everything user-facing is Kaliv.

## Product definition

**Kaliv is a local-first embodied AI platform that combines persistent cognitive
state, replaceable model reasoning, memory, voice, tools and a source-derived
digital body across desktop, mobile and VR.** ModelRig is the backend/control
plane; Kaliv is the user-facing system.

The LLM is deliberately replaceable rather than being the persistence or identity
authority. Persistent cognitive state, VoiceRig, BodyRig and the clients keep
separate ownership boundaries. Consciousness Core is the landed, default-off
architecture for persistent SelfState/WorldState, temporal continuity, sleep/wake
and bounded cognitive cycles. Its production activation remains false and its
runtime paths stay behind explicit opt-in gates.

```mermaid
flowchart LR
    CC["Consciousness Core\nLANDED · DORMANT / default-off"] -. "cognitive state/guidance" .-> MR["ModelRig\nreasoning · memory · tools · semantic intent"]
    LLM["Replaceable LLM\nlocal / explicit cloud"] <--> MR
    MR -->|BodyCue| BR["BodyRig\nbody identity · Motor State\ndigital-twin authority"]
    MR <--> VR["VoiceRig\nvoice/audio + timing authority"]
    subgraph K["Kaliv product surfaces"]
        KA["Kaliv Android"]
        KD["Kaliv Desktop"]
        KVR["Kaliv VR"]
    end
    MR --> KA
    MR --> KD
    MR --> KVR
    BR --> KVR
    VR --> KVR
    SP["SkyPlayer-Engine\nXR/media primitives"] --> KVR
```

See **[docs/KALIV_SYSTEM_DEFINITION.md](docs/KALIV_SYSTEM_DEFINITION.md)** for
the canonical whole-system definition, authority map, cognitive-continuity model,
embodiment model and evidence-state vocabulary.

Current version: see `VERSION`. For what actually exists right now — tools with their
risk/sensitivity, the dormant switches and their defaults, design-doc status — see
**CURRENT_STATE.md**, which is GENERATED from the code and CI-checked for drift.

For body-domain ownership, standalone **`Ternedal/BodyRig` is the authority** for
`.mrbody`, BodyPrint, Movement Identity, Motor State and body realization semantics.
ModelRig owns reasoning and semantic BodyRig-facing intent; its internal `bodyrig`
package and mirrored contracts are compatibility/integration consumers. See
`docs/BODYRIG_AUTHORITY.md`.

**The 2.0 line (August 2026)** rebuilt the Android client against a design
authority (`docs/design/DDR-001`, tokens generated from a single JSON source)
and added the things a phone-first client actually needs:

- **QR pairing** — the rig draws the code, the phone scans it. The link never
  carries a token and never pairs by itself: it shows you the host, and only
  then do you connect.
- **In-app updates** — the app reads the `releases/latest` redirect and offers
  `kaliv-latest.apk`. No API, no token, strict semver.
- **Share to Kaliv** — a share lands in a choice, not an action. Nothing is
  indexed because you tapped Share.
- **Answer citations** — "show what was read" lists the retrieved chunks with
  their match scores. It deliberately does NOT claim which sentence used which
  chunk; that link does not exist in the model, so asserting it would be a guess
  dressed as evidence.
- **Offline queue** — write while the rig is away. A queued message is never
  sent by itself when the rig returns.
- **Per-source on/off** in Knowledge, plus first-run onboarding that says out
  loud that the models run on your own machine.

Earlier lines: streaming voice, a self-supervising appliance mode (autostart +
crash-restart + update-with-rollback), and a multi-step agent with human-gated
writes.

## Current implementation architecture

```mermaid
flowchart TB
    subgraph Clients["Kaliv clients"]
        direction LR
        Desktop["Desktop"]
        Android["Android"]
        KalivVR["VR / OpenXR"]
    end

    subgraph ModelRig["ModelRig — control plane"]
        direction TB
        Go["Go backend :8080<br/>pairing · auth · routing"]

        subgraph Worker["Python worker :8099"]
            direction TB

            subgraph Cognition["Cognition + continuity"]
                direction LR
                CC["Consciousness Core<br/>SelfState · WorldState · time · sleep/wake<br/>LANDED · DORMANT"]
                M4["Memory 4<br/>autobiographical memory authority"]
                A3["Agent 3<br/>planning + gated execution<br/>DORMANT"]
                A4["Agent 4<br/>campaign / read architecture<br/>DORMANT"]
            end

            subgraph Services["Runtime services"]
                direction LR
                RAG["RAG + voice pipeline"]
                Tools["Tools<br/>approval gate"]
                Sched["Scheduler"]
                BC["BodyCue<br/>integration boundary"]
            end
        end
    end

    subgraph State["Local model + state"]
        direction LR
        Ollama["Ollama<br/>replaceable LLM + embeddings"]
        CoreState["Continuity store<br/>atomic SelfState / lifecycle files"]
        DB[("SQLite<br/>RAG · memory · audit · schedules")]
    end

    subgraph Authorities["Independent authorities / engines"]
        direction LR
        Voice["VoiceRig<br/>voice + timing"]
        BodyRig["BodyRig<br/>body identity + Motor State"]
        Sky["SkyPlayer-Engine<br/>XR / media"]
    end

    subgraph Operations["Appliance + development"]
        direction LR
        Sup["Supervisor"]
        Upd["Updater"]
        Dev["DevControl<br/>DORMANT"]
    end

    Desktop --> Go
    Android --> Go
    KalivVR --> Go

    Go --> RAG
    Go -. "gated" .-> CC
    Go -. "gated" .-> M4
    Go -.-> A3
    Go -.-> A4

    CC <--> Ollama
    CC <--> CoreState
    CC -. "recall / experience candidates" .-> M4
    CC -. "intentions" .-> A3
    CC -. "body intent / feedback" .-> BC

    M4 <--> DB
    A3 --> M4
    A3 --> Tools
    Sched --> Tools
    Tools --> DB
    Sched --> DB
    RAG <--> Ollama
    RAG <--> DB

    RAG <--> Voice
    BC <--> BodyRig
    BodyRig --> KalivVR
    Voice --> KalivVR
    Sky --> KalivVR

    Sup --> Go
    Sup --> Worker
    Upd -. "release / rollback" .-> Sup

    classDef focus stroke-width:3px;
    classDef dormant stroke-dasharray:6 4;
    classDef external stroke-dasharray:2 4;

    class CC focus;
    class CC,A3,A4,Dev dormant;
    class Voice,BodyRig,Sky external;
```

The diagram is intentionally architectural rather than exhaustive: **solid lines**
show normal runtime/data relationships, while **dashed lines** show gated,
dormant or advisory paths. Consciousness Core is deliberately central to
continuity and cognition, but it does not absorb the authorities around it:
Memory 4 owns durable autobiographical memory, Agent 3/tools own execution,
BodyRig owns body identity and realization, and VoiceRig owns voice/timing.

Consciousness Core is landed on `main` but remains dormant/default-off behind
`KALIV_CONSCIOUSNESS_CORE_ENABLED=0` and its narrower feature gates.

**Two cloud roads, and they are not the same thing.**

```mermaid
flowchart LR
    subgraph R1["Road 1 — no tools exist on this road. Nothing to bypass: there is no door."]
        K1["Kaliv"] --> C1["Ollama Cloud"]
    end
    subgraph R2["Road 2 — /tools/chat with cloud_key: cloud proposes, the gate decides, you approve writes"]
        K2["Kaliv"] --> G2["Go"] --> W2["Worker<br/>(the gate lives here)"] --> C2["Ollama Cloud"]
    end
```

Embeddings NEVER go to the cloud. `oc.embed()` has no `base_url` and no
`api_key` parameter, so the RAG index cannot be built over the network —
enforced by the signature, not by a runtime check. Only the LLM step can leave
the rig, and only with the toggle on. When a cloud model proposes a write, the
card says who asked: *"Cloud-modellen foreslår: …"*

**Voice** — audio never leaves the house. ASR (faster-whisper, CUDA) and TTS
(Piper, Danish) always run on the rig. Only the transcribed question may go to
the cloud, and only with the toggle on.

**Agent 4** — the campaign/read stack now extends beyond the original A4-14
summary. The foundation, product-read and immutable snapshot-authority software
is on `main`, while the runtime remains deliberately dormant and default-off.
The production-shaped surface is read-only, backend-proxied, requires a paired
device plus explicit `agent4:read`, and composes the narrow A4-21 read context
rather than exposing lifecycle/scheduler/resource/handoff/recovery mutation.
A4-19 snapshot-bound paging and A4-20 stale-response invalidation protect the
read product; A4-25a–e establish server-side immutable snapshot authority and
Android snapshot/race handling. **A4-25f remains a separate physical
Windows+Pixel qualification campaign followed by a human GO/NO-GO; CI does not
stand in for that evidence.** See `docs/AGENT_4_IDENTITY.md`,
`docs/AGENT_4_A4_25_SERVER_SNAPSHOT_AUTHORITY.md` and the physical runbooks.

Its architecture is fixed by ADR before behaviour ships; storage must not know
subscribers, and application-driven polling is forbidden. Those boundaries are
not prose alone: CI gates scan the package on every run
(`AGENT_4_ARCHITECTURE_DECISIONS.md` remains the decision authority).

**DevControl / KalivDev** — DC-L01 through **DC-L14 are landed on `main`** as a
separate dormant authority chain for controlled local self-development. The
core includes task/scope authority, Windows containment, signed physical-evidence
contracts, verified local execution, trusted local-only Git, semantic review,
one-time authorization/recovery, local-only candidate materialization and final
package/authority closure. It still has **no normal Kaliv product entrypoint,
no non-empty default registry/catalog and no remote Git/GitHub mutation,
merge/release/deploy authority**. DC-L15 is the fresh physical I0b campaign and
human decision packet; DC-L16 is the later, tightly allowlisted product pilot.
`docs/devcontrol/dc-l14/independent-review-verdict.md` also records that an
independent human DC-L14 verdict has not been recorded; do not synthesize one
from merge status. See `devcontrol/README.md`.

**BodyRig boundary** — `Ternedal/BodyRig` is the source of truth for `.mrbody`,
BodyPrint, Movement Identity, Motor State and body realization. ModelRig owns
semantic assistant intent and BodyRig-facing cue production. The internal
`bodyrig` package and mirrored schemas are compatibility/integration layers, not
a second product authority. See `docs/BODYRIG_AUTHORITY.md`.

**Tools** — the model proposes; the gate decides. Reads run. Writes stop at a
confirmation card and execute the arguments that were shown: the worker parks
them, so no client can alter them after approval. *Risk* decides whether a
human is asked, not origin. Reads may chain within a turn (bounded) so the model
can gather before answering; a write always stops for a human confirmation and is
never chained unapproved — even after an approved write, a subsequent write gets
its own card. Off by default (`KALIV_TOOLS_ENABLED=1`).
See `KRAVSPEC_V5_TOOLS.md`.

**The Go server is a proxy and nothing more.** Gate, whitelist and audit live in
the worker, so an old or tampered client cannot find a friendlier backend.

Cloud fallback (desktop): if local is down/insufficient →
Ollama Cloud (https://ollama.com, model `:cloud`) with `OLLAMA_API_KEY`.

- **backend/** — Go, stdlib only. Device pairing (short `XXXX-XXXX` codes) →
  hashed bearer tokens, device list + **revoke**, brute-force **rate limiting** on
  claim, then reverse-proxies chat/models to Ollama (streaming) and RAG to the
  worker. Auth is loopback-free.
- **worker/** — Python FastAPI. RAG: **chunk** (overlapping) → embed via Ollama →
  SQLite → cosine retrieval → optional synthesis, plus **streaming RAG chat**
  (retrieve + stream the answer). Source management: list, stats, delete, filter.
  Ingest is **atomic**: every embedding is computed before anything is deleted,
  and the replace plus all inserts run in one `BEGIN IMMEDIATE` transaction, so a
  failed embed can no longer leave a source half-replaced. The corpus is **bound
  to the model that built it** (`corpus_meta`), and a query under a different
  model or dimension **fails closed with a named error** instead of returning
  nothing — silence that looks like "no relevant sources" is the one answer a
  disconnected index must never give.
- **vr/** — Kaliv VR (Unity/OpenXR, Quest). First-party ModelRig client using the same pairing/bearer/chat contracts as Android/Desktop, with reusable XR/media mechanics supplied by `Ternedal/SkyPlayer-Engine`.
- **desktop/** — Compose Desktop (JVM). **Streaming** chat with local-first +
  Ollama Cloud fallback, model picker, branded UI.
- **android/** — Compose Android V1. Talk to your **rig** (backend → local models
  + RAG) **or directly to Ollama Cloud** (no rig needed). Material 3 dark UI,
  dependency-free **Markdown** rendering (code blocks + copy), Keystore-encrypted
  cloud key. Source — build locally (an APK ships on the GitHub release).
- **tools/** — `modelrig-cli.py`, a dependency-free reference client (pair, chat,
  RAG, device mgmt, `doctor` health check, token `rotate`). Runnable today; used
  to drive the e2e test.
- **tests/** — worker unit + RAG tests, backend smoke + V1 tests, and an
  end-to-end integration test. `sh tests/run_tests.sh` runs the full suite (see CI for the current counts).
- **deploy/** — env reference, a Windows launcher (`run-windows.ps1`), and systemd
  units for running the worker + backend as services.
- **scripts/** — the tooling CI depends on. Generators that own a document
  (`activation_readiness.py`, `current_state.py`, `route_inventory.py`,
  `design_tokens.py`) each have a `--check` that fails on drift, so the
  generated files cannot silently diverge from their source. Also the one-click
  operators for rig days, including `workflow_baseline_one_click.py --check`,
  which answers "is the rig ready" without running or writing anything.
- **eval/** — the specs the harnesses measure against: workflow completion
  (`workflows_v1.json`, 14 workflows), Agent 3 model tasks, the voice baseline
  manifest. `tests/workflow_spec_contract.py` keeps them internally consistent
  — a typo in an expected tool name means a workflow can never pass, and that
  should not be discovered on a rig day.
- **assets/design/kaliv-ui-guide/** — the design authority. `kaliv-ui-tokens.json`
  is the **single** source for colours, spacing, radii and motion; it is
  generated into `KalivTokens.kt` for both clients, and desktop's `Brand.kt`
  reads those rather than keeping its own copies. Two gates hold the chain:
  drift between JSON and the generated files, and any colour literal that
  duplicates a token.
- **brand/** — logo system, app icons and brand guidelines.
  `brand/KALIV_BRAND_HANDOFF.md` is current. **`brand/05_handoff-docs/` is
  superseded**: it describes ModelRig with sapphire blue as the primary action
  colour, and the shipping Kaliv system is brass with no blue in it at all.
  Each of those four files carries a banner saying so.
- **contracts/** — the versioned capability schema and its fixtures, shared by
  the worker and both clients.

## Repository scale

The deterministic `loc-metrics` workflow is now the canonical way to measure
repository source size. At the exact 2026-09-11 landing candidate for #1139,
ModelRig contained **305,666 nonblank tracked source/config lines** and **338,619
physical source/config lines** across 1,472 files: 141,677 product, 105,688 tests,
48,122 scripts and 10,179 config (nonblank counts). Documentation, vendor, build,
generated and common lock/minified files are excluded from that metric.

Run the same definition locally with:

```bash
python scripts/loc_metrics.py
```

CI publishes JSON + Markdown artifacts for PR/main runs, so future documentation
should reference a measured run rather than hand-maintaining a guessed LOC total.

## Scheduler (delivery model)

Scheduled tool runs are **at-most-once by construction**: every claim writes a
durable occurrence row and reserves its budget slot in the same transaction
that advances the due time. Crash recovery consults the audit trail before
refunding anything — a run that provably happened keeps its slot spent. A
pause, renewal or deletion after a claim cancels the in-flight occurrence
(revision guard re-checked right before execution). Every consumed write
approval persists a receipt (device, issue time, consumption time, grant
revision) in the same transaction as the grant — `GET /schedules/{id}` shows
the full history. `ACTIVATION_READINESS.md` runs seven live durability probes
against the real components on every regeneration.

## ⚠️ The one gotcha that wastes an afternoon
The backend defaults to binding **`127.0.0.1`**. That is unreachable from your
phone or any other machine. Before pairing Android, set:
```bash
MODELRIG_HOST=0.0.0.0 ./modelrig-server      # LAN
# or bind a Tailscale IP for remote access
```
The backend logs this warning at startup; the Android pairing screen repeats it.

## Udviklingskanalen: appliancen fra checkouten

Så længe intet er i produktion, kører riggen den kode checkouten holder.
`START_DEV_APPLIANCE.cmd` bygger backend fra HEAD og starter backend + worker
med appliancens egne data og env; `STOP_DEV_APPLIANCE.cmd` bringer den
signerede release tilbage. Ny kode = `git pull` + dobbeltklik. Det er ikke
bevis, og det rører ikke `production_activation` — se `DEV_APPLIANCE.md`.

## Run order (local dev)

**The easy way:** `scripts\start-kaliv.bat` starts all three processes correctly
(including `MODELRIG_HOST=0.0.0.0` for phone reachability) and runs `/health/full`
at the end. See `scripts/START_HERE.md`. The manual steps below are the long way.
```bash
# 0. Ollama running with your models
ollama pull qwen3:14b        # confirmed primary (MODELS.md); qwen3:8b if VRAM is tight
ollama pull nomic-embed-text

# 1. Worker (RAG) — optional, only if you use /rag/*
# Bind to loopback: the worker has NO auth of its own and is meant to be reached
# only by the backend on the same machine. Do not expose it on the LAN.
cd worker && pip install -r requirements.txt
uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099

# 2. Backend
cd ../backend && go build -o modelrig-server ./cmd/modelrig-server
MODELRIG_HOST=0.0.0.0 ./modelrig-server

# 3. Pair a device
./modelrig-server -pair            # (server stopped) OR:
curl -X POST http://localhost:8080/api/v1/pair/start   # (server running)

# 4a. Desktop
cd ../desktop && ./gradlew run   # use the wrapper; a system gradle may be a different version

# 4b. Android
cd ../android && ./gradlew assembleDebug

# 4c. Or the reference CLI (works today, no build)
python tools/modelrig-cli.py --url http://localhost:8080 pair --code XXXX-XXXX
python tools/modelrig-cli.py doctor    # backend / worker / ollama health
python tools/modelrig-cli.py chat "hello"
```

Run the tests (Unix/WSL, needs Go + Python worker deps):
```bash
sh tests/run_tests.sh
```

## Build status at a glance

| Module   | State                                        | Verified by                          |
|----------|-----------------------------------------------|--------------------------------------|
| backend  | Go server: pairing, tokens, reverse proxy — plus its own `/api/v1/system/status` and `/api/v1/models/unload` (stdlib only, fail-soft) | ✅ `go build` + `go test` (config, httpapi) in CI |
| worker   | FastAPI: RAG, voice, tools, jobs, isolation   | ✅ full suite in CI — `tests/worker_*.py` + `tests/workflow_*.py`, auto-globbed (live counts in the CI log; this file does not keep score) |
| android  | Kaliv APK (minSdk 26)                         | ✅ built in CI, `kaliv-latest.apk` on every release |
| vr       | Kaliv VR Unity/OpenXR client                   | 🚧 landed on `main`; Quest build/device qualification pending |
| desktop  | Kaliv Windows JAR (Compose JVM)               | ✅ built in CI, `Kaliv-windows-x64-X.Y.Z.jar` |
| exes     | server + worker Windows executables           | ✅ built in CI, attached to every release |

Every release ships its full asset set (both APKs, the desktop JAR, the three
Windows exes, the zip and `SHA256SUMS.txt`) from a green CI run: the release is
created as a DRAFT, assets are verified against the expected list, and only
then is it published — so a half-uploaded release is never visible. Regression
tests guard the bug classes that bit on real hardware (env trimming, path
anchoring, keep_alive-to-cloud, retry losing a turn's route, streams ending
without a terminal event). The **honest rule** stands: compiled ≠ shipped, and
CI-green ≠ works-on-device — the last mile is always on-device testing.

See **STATUS.md** for the per-release history (a log, not a status page — for
current state read CURRENT_STATE.md; the old "line 3 is always current"
convention required a human to remember and spent 55 releases wrong
one-liner) and **ROADMAP.md** for where this is going (closed-ended at V15).

**Building and testing the clients locally?** See **CLIENT_BUILD_AND_TEST.md**.

## License
MIT — see LICENSE.