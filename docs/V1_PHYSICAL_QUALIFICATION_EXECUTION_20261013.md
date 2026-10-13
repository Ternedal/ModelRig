# V1 physical qualification execution plan (2026-10-13)

Status: **BLOCKED pending physical evidence**. This document is an execution checklist, not a release approval.

## Authority
- Preserve main and existing V1 software freeze.
- Pin the exact candidate Git SHA and tree before testing; do not mix evidence across revisions.
- Never hand-edit generated CURRENT_STATE.md or ACTIVATION_READINESS.md.
- Fail closed on missing, stale, simulated, or inconsistent reports.

## Execution order
1. Confirm candidate SHA, protected-main status, required checks and pending PRs. Capture CI results for the exact candidate.
2. On the Windows rig, identify the *running* worker PID, interpreter and ASR/TTS runtime status using the read-only voice preflight introduced in #2098. Do not infer runtime readiness from a package installed in a different Python environment.
3. Validate live voice input → transcription → cognition/LLM → audible TTS. Record failures and environment identity; do not claim PASS based on component tests alone.
4. Collect three real correlated receipts (perception_received, cognition_completed, outward_started) for one event, epoch, observer and candidate SHA. Run scripts/kaliv_end_to_end_latency_qualifier.py as documented in docs/KALIV_END_TO_END_LATENCY_QUALIFICATION.md. MEASURED is not a latency SLO pass.
5. Capture repeatable resource and latency measurements on both RTX 3060 cards under a representative load; document VRAM, TTFT, ASR, TTS and end-to-end distributions. Do not infer a performance threshold without an approved baseline.
6. Run the canonical physical Agent 3 rig-validation flow and produce validation/agent3-rig-validation-latest.json. Regenerate activation readiness using its generator. Do not enable Agent 3 or scheduler while readiness says NO.
7. Execute device-specific Kaliv and updater acceptance, including real device and signed-release checks where applicable.
8. Produce a SHA-bound release manifest listing CI, physical tests, receipts, unresolved blockers and an explicit GO/NO-GO decision.

## Exit criteria
- Exact candidate SHA and required CI checks verified.
- Physical end-to-end voice works and is evidenced.
- Latency evidence qualifies without overclaiming an SLO.
- Agent 3 / scheduler remain off unless readiness becomes PASS from real physical evidence.
- No unresolved P0 security or runtime blocker.
- Rollback path and known limitations documented.

Any unmet criterion is **NO-GO**, not a silent exception.
