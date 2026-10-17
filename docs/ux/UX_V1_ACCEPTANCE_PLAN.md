# ModelRig / Kaliv — UX V1 acceptance plan

Status: proposal only. This document does not change V1 runtime or release gates.

## Confirmed documentation gaps (verify current implementation before coding)
- Desktop README: conversation persistence exists; conversation browser (list/switch/delete) is described as missing.
- Android README lists stop-generation as future work, BUT current ModelRigClient.chatStream and ragChatStream already expose registerCall for OkHttp cancellation. Verify actual UI wiring before treating stop as missing.
- Android README: RAG is single-turn despite conversation history being displayed.
- Android README: markdown renderer lacks tables, images and nested lists.
- Desktop README: settings are in memory, while conversations persist.
- Voice preflight: dependency discovery does not prove runtime ASR or real audio readiness.

## Source verification (2026-10-11)
- Inspected current `android/.../net/ModelRigClient.kt`: chatStream, ragChatStream, and voiceConverseStream expose `registerCall`; streaming completion and mid-stream failures are explicitly checked. Do not reimplement these features blindly.
- `ChatScreen.kt` is not the current path; UI is split across `ui/chat/ChatScreen1.kt`, `ui/AppUi.kt` and related files. `ChatScreen1.kt` already exposes `onStop` and uses it for the busy-state send/stop button. Parent callback wiring and cancellation lifecycle remain unverified.
- README claims may be historical, not current release evidence. Acceptance status stays UNKNOWN until code-path and test inspection.

## P0 — release-safe usability and safety
1. Show active source (local/cloud), model, connection status and whether fallback occurred; never silently transmit private prompts to cloud.
2. Verify existing cancel-generation UI wiring end-to-end; add deterministic cancellation tests, no duplicate assistant message and explicit partial-answer status where missing.
3. Replace generic 502 errors with actionable, non-secret-leaking voice status and retry guidance.
4. Provide keyboard/screen-reader semantics, visible focus, accessible contrast and touch targets.
5. Preserve unsent draft on transient network errors; do not retry non-idempotent requests without user action.

## P1 — next version
1. Desktop conversation browser: list, switch, rename, delete with confirmation and undo where possible.
2. Persist settings safely; encrypt credentials, do not log tokens.
3. RAG multi-turn with explicit source attribution and token-budget cap.
4. Structured markdown tables and accessible code blocks.
5. Consistent UI states on Android, Desktop and Quest.

## Test matrix / acceptance criteria
- Offline, backend down, model unavailable, invalid token, timeout, streaming disconnect.
- Cancel before first token / mid-stream / after completion: no phantom reply, leaked work or double text.
- Local/cloud transitions require explicit consent when content would leave device.
- Cold start, resume, rotate, background/foreground, large histories and long code blocks.
- Screen reader navigation and keyboard-only chat/send/cancel.
- ASR unavailable: status indicates disabled dependency; no misleading recording success.
- Measure p50/p95 time-to-first-token and interaction latency on physical rig; no unmeasured performance claims.

## Delivery sequence
1. Inspect current source and existing tests; create issue-sized implementation patches on this branch.
2. Add regression tests before changing behavior.
3. Run available CI; physical-device/rig tests remain explicitly unverified until performed.
4. Open draft PR, keep main protected and V1 freeze intact.
