# ModelRig / Kaliv 2.0.14 – integrated test release

This runbook is the operator-facing test path for the first integrated 2.0.14
candidate. It does not grant production authority. All release and runtime
authority gates remain fail-closed unless their own evidence says otherwise.

## Candidate pins

The release manifest must pin exact revisions. For this test release, use:

- ModelRig: the exact commit tagged `v2.0.14` after this final closure PR lands on `main`
- BodyRig: `360844a5acf94876306447f2d86a7b22a487f4a8`
- VisionRig: `66ea9bfce1c4d219e4bac1d85324a0e6e3f042e5`
- VoiceRig: `9f3e594996db7eb2c6e035247ecb168bf17c1dae`

Do not replace those external pins with floating branch names during qualification.

`v2.0.14` is not a valid candidate until the final ModelRig merge commit has full CI/exact-head qualification and the release tag points to that exact commit. If any of the four pinned revisions changes, re-freeze and re-run the cross-repository software exact-green qualification before physical acceptance.

## What the GitHub release must contain

The `v2.0.14` build is expected to publish atomically only after all build jobs
succeed. Verify that the release contains, at minimum:

- signed Android APK: `modelrig-v2.0.14.apk`
- stable Android alias: `kaliv-latest.apk`
- Windows desktop runnable JAR
- `modelrig-server-windows-x64.exe`
- `modelrig-worker-windows-x64.exe`
- `modelrig-supervisor-windows-x64.exe`
- `modelrig-updater-windows-x64.exe`
- `modelrig-v2.0.14.zip`
- `SHA256SUMS.txt`
- GitHub/Sigstore build attestations for the release assets

A release missing an expected asset is not a valid test candidate.

## Windows rig – first test

1. Stop any previous ModelRig/Kaliv processes.
2. Pull the exact `v2.0.14` tag or use the published release binaries.
3. Confirm Ollama is running and the intended local model is available.
4. For checkout-based testing, start with `scripts\start-kaliv.bat`.
5. Verify:
   - backend `/healthz`
   - worker `/healthz`
   - full-chain `/health/full`
   - reported version is `2.0.14`
   - Ollama connectivity is visible and truthful
6. Open Kaliv Desktop and confirm pairing, model listing and a normal local chat.
7. Exercise one RAG query if a local corpus is configured.
8. Confirm no dormant write/agent/production authority silently activates.

## Android

1. Install the signed `modelrig-v2.0.14.apk` over the existing Kaliv app.
2. Confirm the package installs without signature mismatch.
3. Pair to the rig through the normal QR/pairing flow.
4. Verify local chat and streaming response.
5. Verify reconnect after briefly stopping/restarting the rig.
6. Confirm the app still reports/uses version 2.0.14 and does not fall back to a
   stale client build.

## VisionRig

Use the pinned VisionRig revision above.

Verify health and the expected `PerceptionEvent/v4` contract before enabling the
ModelRig bridge. Then test one bounded perception flow into ModelRig. VisionRig
must not gain identity, durable-memory or action authority from the integration.

## VoiceRig

Use the pinned VoiceRig revision above.

Verify the local ASR/TTS path, one complete voice turn and timing/streaming. Audio
must remain local; only text may traverse an explicitly enabled cloud LLM path.

## BodyRig

Use the pinned BodyRig revision above.

Verify the BodyRig health/control surface and one ModelRig-to-BodyRig cue path.
Treat photoreal and M6 qualification as evidence gates: do not infer them from a
successful UI connection alone.

## Integrated smoke sequence

Run this order so failures are easy to localize:

1. Ollama
2. ModelRig worker
3. ModelRig backend
4. Kaliv Desktop
5. Kaliv Android
6. VoiceRig
7. VisionRig
8. BodyRig
9. Consciousness Core development-only lifecycle path, if explicitly enabled
10. Kaliv VR / Quest as a separate physical-device qualification

Record exact SHAs and the release asset hashes with every physical observation.

## Pass condition for this test release

The test release is useful when the packaged 2.0.14 artifacts install/start
cleanly, the core local chat path works, Android can pair and converse with the
rig, and the pinned VoiceRig/VisionRig/BodyRig integrations can be exercised
without crossing their authority boundaries.

This document does not declare production readiness. Physical observations and
the canonical release manifest remain the evidence authority.
