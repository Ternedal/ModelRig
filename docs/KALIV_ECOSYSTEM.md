# Kaliv repositories and integration contracts

> **Purpose:** a map of the repositories that make up Kaliv and of the contracts
> between each of them and ModelRig, as implemented on `main`.
>
> This page describes interfaces. It does not define authority and it does not
> claim that anything is activated, released or physically accepted.
>
> - Who owns what: [`KALIV_SYSTEM_DEFINITION.md`](KALIV_SYSTEM_DEFINITION.md).
> - What is on `main` and which switches are on: the generated
>   [`CURRENT_STATE.md`](../CURRENT_STATE.md) and
>   [`ACTIVATION_READINESS.md`](../ACTIVATION_READINESS.md).
> - What a whole-system release requires:
>   [`KALIV_SYSTEM_RELEASE_QUALIFICATION.md`](KALIV_SYSTEM_RELEASE_QUALIFICATION.md).
>
> Every contract below names the source file that implements it. If this page
> and that file disagree, the file is right.

## Repositories

| Repository | Role | Connection to ModelRig |
|---|---|---|
| [ModelRig](https://github.com/Ternedal/ModelRig) | Backend and control plane (Go backend, Python worker) and the Kaliv clients: `android/`, `desktop/`, `vr/` | — |
| [VoiceRig](https://github.com/Ternedal/VoiceRig) | Builds `.mrvoice` voice profiles; local TTS sidecar | The worker calls the sidecar over loopback HTTP; Piper is the fallback |
| [BodyRig](https://github.com/Ternedal/BodyRig) | Body identity: `.mrbody` packages, BodyPrint, Motor State, the clone pipeline | File contract (`.mrbody`); ModelRig runs its own in-process body runtime; BodyRig's Person Studio calls the backend for auditions |
| [VisionRig](https://github.com/Ternedal/VisionRig) | Visual perception: sensor ingress and structured `PerceptionEvent`s | VisionRig posts events to the worker over loopback; the Control Center reads VisionRig status |
| [LanguageRig](https://github.com/Ternedal/LanguageRig) | Danish language-model adaptation and evaluation | Registers models in the shared Ollama; can publish books to the RAG API |
| [KalivNexus](https://github.com/Ternedal/KalivNexus) | Registry for external API capabilities and guarded MCP inspection | None |
| [KalivHub](https://github.com/Ternedal/KalivHub) | Home client: Home Assistant → Google Cast sender for a Nest Hub (private repository) | None on `main` |
| [KalivHub-Receiver](https://github.com/Ternedal/KalivHub-Receiver) | The Cast receiver page shown on the Nest Hub | None on `main` |
| [SkyPlayer-Engine](https://github.com/Ternedal/SkyPlayer-Engine) | Unity/OpenXR playback and passthrough package | `vr/` consumes it as a pinned package |
| [Kaliv](https://github.com/Ternedal/Kaliv) | The public project site, kaliv.dk | The site states release and proof status by hand |

## Local services and ports

Every service below binds to loopback by default. Clients reach ModelRig only
through the backend, which has to be bound to a LAN or Tailscale address with
`MODELRIG_HOST` before a phone or headset can connect. Sensor clients reach
VisionRig only through its sensor gateway.

| Service | Default address | Set by |
|---|---|---|
| ModelRig backend | `127.0.0.1:8080` | `MODELRIG_HOST`, `MODELRIG_PORT` (`backend/internal/config/config.go`) |
| ModelRig worker | `127.0.0.1:8099` | `MODELRIG_WORKER_HOST`, `MODELRIG_WORKER_PORT` (`worker/run_worker.py`) |
| VoiceRig sidecar | `127.0.0.1:8765` | fixed in VoiceRig |
| BodyRig service | `127.0.0.1:8775` | `BODYRIG_HOST`, `BODYRIG_PORT` in BodyRig |
| VisionRig core | `127.0.0.1:8110` | VisionRig |
| VisionRig sensor gateway | `127.0.0.1:8111` | `VISIONRIG_GATEWAY_BIND_HOST`, `VISIONRIG_GATEWAY_PORT` in VisionRig |

## VoiceRig

Implemented in `worker/app/voice_tts.py`.

- VoiceRig installs `.mrvoice` packages into the voices directory,
  `MODELRIG_VOICES_DIR` (default `~/.kaliv/voices`). Both sides must use the same
  directory. ModelRig only checks that a package exists; it does not parse the
  manifest. VoiceRig decides which package to speak with.
- The worker calls `GET /api/tts/status` and `POST /api/tts/synthesize` on
  `VOICERIG_TTS_URL` (default `http://127.0.0.1:8765`).
- `TTS_PROVIDER` selects the provider: `auto` (default) uses VoiceRig when a
  package exists and the sidecar reports `ok`, and Piper otherwise; `voicerig`
  and `piper` force one provider.
- VoiceRig can also try to push a package to
  `POST /api/v1/voices/import` when it is not configured for a same-host
  install. ModelRig has no such route, so a split-host install fails.

The VoiceRig side of the contract is in VoiceRig's
`docs/MODELRIG_INTEGRATION.md`.

## VisionRig

- **Events in.** VisionRig posts `PerceptionEvent/v4` (v3 is still accepted) to
  `POST /experimental/consciousness/visionrig-event` on the worker. The route
  is loopback-only and is off unless
  `KALIV_CONSCIOUSNESS_VISIONRIG_ENABLED=1`
  (`worker/app/consciousness_core/visionrig_admission.py`).
- **Status out.** The Control Center reads VisionRig at `KALIV_VISIONRIG_URL`
  (default `http://127.0.0.1:8110`; `worker/app/control_center_vision.py`).
- A VisionRig observation is evidence for the Consciousness Core. It does not
  authorize a memory write or an action; see the authority table in
  [`KALIV_SYSTEM_DEFINITION.md`](KALIV_SYSTEM_DEFINITION.md).

The VisionRig side is in VisionRig's `docs/MODELRIG_BRIDGE.md`.

## BodyRig

- **File contract.** `.mrbody` v1. The specification is
  [`MRBODY_SPEC.md`](MRBODY_SPEC.md); the schemas are
  `contracts/mrbody-manifest-v1.schema.json` and the snapshot in
  `contracts/bodyrig/`. Authority over the format is described in
  [`BODYRIG_AUTHORITY.md`](BODYRIG_AUTHORITY.md).
- **Runtime.** ModelRig runs its own body runtime in `bodyrig/`, reads the
  installed body from its profile store (`KALIV_BODY_STORE`,
  `worker/app/body_assets.py`) and serves it to clients through the backend
  routes under `/api/v1/body/` (`backend/internal/httpapi/server.go`): the
  active package, its avatar, BodyPrint and motions, the body state and the
  frame stream. Only canonical `bodyid-*` packages are accepted. ModelRig does
  not call the BodyRig service.
- **Clients.** Android and Kaliv VR load the body from those backend routes.
- **BodyRig calls ModelRig.** BodyRig's Person Studio uses the ordinary backend
  API with a device token for personality auditions: `GET /healthz`,
  `GET /api/v1/models` and `POST /api/v1/chat`.

ModelRig's own BodyRig documentation is [`BODYRIG_V1.md`](BODYRIG_V1.md) and
[`bodyrig/`](bodyrig/). The BodyRig side is in BodyRig's
`docs/KALIV_ECOSYSTEM.md`.

## LanguageRig

- LanguageRig registers a trained model in the local Ollama instance that
  ModelRig uses. ModelRig does not switch its default model as a result.
- `languagerig publish-rag` sends books to `POST /api/v1/rag/ingest` with a
  paired device token (`backend/internal/httpapi/server.go`).
- ModelRig does not call LanguageRig.

## KalivHub and KalivHub-Receiver

There is no KalivHub code on ModelRig `main`.

- ModelRig's own Home Assistant work is a separate track, T-038:
  [`T038_HOME_ASSISTANT_LIVE_READ.md`](T038_HOME_ASSISTANT_LIVE_READ.md) and
  `worker/app/home_assistant_*.py`.
- The receiver listens on the Cast namespace `urn:x-cast:dk.kalivhub.lab`. A
  bridge that mirrors ModelRig replies to a Nest Hub exists on a test branch of
  KalivHub-Receiver (`test/nest-hub-microphone-probe`), not in this repository.

## KalivNexus

No integration. KalivNexus does not call ModelRig, and ModelRig does not call
KalivNexus.

## SkyPlayer-Engine

`vr/Packages/manifest.json` pins the package `dk.ternedal.skyplayer.engine` to
a commit. [`vr/RENDERING.md`](../vr/RENDERING.md) describes how Kaliv VR wraps
the engine's player.

## Kaliv (the site)

The site at kaliv.dk publishes a machine-readable manifest, `project.json`,
and a text version, `llms.txt`. Both state the latest release and the proof
status by hand, so they can lag behind this repository.
