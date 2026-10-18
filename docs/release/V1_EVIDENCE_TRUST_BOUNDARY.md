# V1 release evidence trust boundary (operator note)

This note documents the existing release gate; it does **not** qualify or authorize a release.

## Structural versus authoritative validation

`scripts/kaliv_system_release_gate.py` validates the release manifest envelope, gate statuses, pinned SHAs and reference syntax. A syntactically valid evidence reference does **not** establish that the underlying physical test was executed or that the referenced bytes were independently verified. In particular, `QUALIFIED` from structural validation alone must never be interpreted as production authorization.

## Required operator checks before any promotion

1. Record the exact clean checkout commit SHA of ModelRig, BodyRig, VisionRig and VoiceRig and compare each to the approved freeze.
2. For each required gate, retrieve the actual producer artifact from its authoritative source, preserve its bytes, compute SHA-256 independently and check the recorded digest against the actual artifact.
3. Re-run the relevant producer validator against those artifacts and exact source revisions. Do not replace unavailable evidence with synthetic test fixtures, manually invented PASS flags or plausible-looking hashes.
4. Independently verify required physical and human approvals, including operator identity and time, and retain the review trail.
5. Treat missing, stale, untrusted, unverifiable or revision-mismatched evidence as PENDING or FAIL. Never infer PASS from GitHub CI alone.
6. Confirm the release version, signed update/rollback plan and explicit human release approval before creating any tag or activating production.

## Current freeze rule

This documentation branch does not alter protected `main`, the production worker or any release gate. Do not merge into a frozen candidate without explicitly re-qualifying the changed exact head and cross-repository evidence. Until independent artifact verification is implemented and completed, keep `release_ready=false` and `production_activation=false`.

Tracking: #2025, #2111, #2109, #2107.
