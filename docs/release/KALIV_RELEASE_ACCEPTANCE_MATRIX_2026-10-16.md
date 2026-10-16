# Kaliv release acceptance matrix — operator baseline

> This document is a **planning and evidence-capture template**, not an assertion that tests passed. Never promote a release based on this file alone. Exact-head gates and independent physical qualification remain authoritative.

## Candidate identity

| Field | Required value |
| --- | --- |
| ModelRig commit SHA | NOT_RECORDED |
| BodyRig commit SHA | NOT_RECORDED |
| VoiceRig commit SHA | NOT_RECORDED |
| VisionRig commit SHA | NOT_RECORDED |
| Android application ID/version/signing fingerprint | NOT_RECORDED |
| Go backend + Python worker build IDs | NOT_RECORDED |
| Operator/date/rig hardware | NOT_RECORDED |

## Evidence vocabulary

Use only `PASS`, `FAIL`, `BLOCKED`, or `NOT_RUN`. `PASS` requires a linked dated artifact and exact candidate identity. A PR description or CI pass cannot substitute for a real device test.

## Mandatory acceptance

| Gate | Status | Required evidence |
| --- | --- | --- |
| All required exact-head CI and CodeQL | NOT_RUN | GitHub run URLs and candidate SHAs |
| Cross-repo inventory/source authority | NOT_RUN | Bound manifests and reviewed transition receipts |
| Android mic permission and capture | NOT_RUN | Device log and operator result |
| Android → authenticated Go proxy → worker | NOT_RUN | Correlated request trace with credentials redacted |
| Danish ASR and local LLM answer | NOT_RUN | Controlled input, transcript and output |
| TTS audible first chunk and complete playback | NOT_RUN | Operator observation and timing |
| Stop during network stream cancels upstream work | NOT_RUN | Android, Go and worker cancellation evidence |
| Barge-in prevents stale audio and frees resources | NOT_RUN | Two-turn physical replay |
| Voice history recalls prior turn without system-role injection | NOT_RUN | Bounded two-turn replay and negative test |
| Temporary WAV cleanup after interruption | NOT_RUN | Post-run filesystem inventory |
| Offline/reconnect and repeat turn | NOT_RUN | Device test and recovery trace |
| Cloud opt-in and privacy boundary | NOT_RUN | Local-only and explicitly cloud-enabled probes |
| Installed-app upgrade retains app data | NOT_RUN | Version/signature/device-data evidence |
| Rollback/recovery | NOT_RUN | Approved operator runbook and recovery test |
| Signing-key migration decision | BLOCKED | Explicit owner-approved plan; existing public key issue |

## PR dependency review

- #2200: Android OkHttp cancellation (check actual current state).
- #2201: combined voice validation candidate.
- #2202: Android 2.0.15 release path (check current state; do not assume still pending).
- #2203: side-by-side device pilot.
- #2204: capabilities proxy; inventory-pinned source governance.
- #2205: bounded voice conversation history.
- #2206: opt-in Nest Hub mirroring; independently gated.
- #2207: audit and priorities.
- #2208: read-only signing inventory.

**Before each merge:** refresh current PR state and SHA; classify superseded work; verify the target branch and dependency graph; ensure no release freeze violation. No auto-merge based on this template.

## Performance measurements (baseline before tuning)

Record separately for cold/warm sessions: ASR latency, LLM prefill, tokens/sec, first TTS chunk, time to audible reply, total turn duration, peak/idle VRAM and RAM, CPU utilization, queue depth, cancellation time, and p50/p95 across at least 20 representative Danish prompts. Attach hardware, model quantization, context size and Ollama settings. Do not infer improvement without paired baseline.

## Exit criteria

All mandatory gates PASS with dated linked evidence, except any explicitly waived nonmandatory item with documented risk owner. Any FAIL/BLOCKED/NOT_RUN mandatory gate prevents production promotion. Approval must be explicit and independent of this document.
