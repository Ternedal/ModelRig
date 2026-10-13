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


## Verified GitHub checkpoint (2026-10-13)
- Frozen main: `0b2ff455116f4f28a1a41704d9cb81503f17d2df`; this plan's draft branch is **not** a new release candidate.
- Draft PR #2157 head `d8a4eb2f195899a65bf85d726130dd2b975868de`: CI, CodeQL, LOC metrics, Agent 3 diagnostics and full diagnostics succeeded; exact-head qualification was **in progress** when checked. Recheck before any conclusion.
- #2106: running-worker ASR 502 diagnosis and real Danish audio baseline still require physical execution.
- #2063: same-observer end-to-end latency requires runtime-produced receipts and independent review.
- #2107: legacy updater instructions mention 2.0.11/2.0.13; **do not execute** these as if they apply to frozen 2.0.14.
- #2109: VisionRig/VoiceRig repository authority scripts do not support `-Json`; their text output is not exact-SHA-bound approval.
- #2111: final manifest validation is structural; plausible canonical reference strings alone do **not** verify source artifacts or authorize release.

## Operator evidence ledger (do not prefill PASS)
| Gate | Evidence required | State |
|---|---|---|
| Software exact-head | Frozen SHA + exact-head CI evidence for all pinned repos | Check canonical #1994 |
| Voice physical | Worker PID/interpreter, live ASR/TTS, 20-file Danish campaign, human listening | PENDING |
| End-to-end latency | Three real correlated source receipts, independent provenance review | PENDING |
| Repository authority | Live protection checks and exact SHA binding across four repos | PENDING |
| Other physical/admin gates | Canonical campaign #2025 and underlying evidence artifacts | PENDING |
| Final system release | Independent artifact verification, human sign-off, no P0 blockers | NO-GO |

**Important:** The ten-gate structural `QUALIFIED` string must never be interpreted as physical qualification or production permission without independent source-artifact verification. No synthetic or hand-authored evidence is accepted.
