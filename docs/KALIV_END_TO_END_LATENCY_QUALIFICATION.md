# Kaliv end-to-end latency qualification

`scripts/kaliv_end_to_end_latency_qualifier.py` produces the canonical evidence
for the `end_to_end_latency` Kaliv system release gate.

This is deliberately a **measurement gate**, not an invented performance SLO.
The repository does not yet have a physically established cross-rig latency
threshold, so this qualifier proves and records one real correlated traversal
without claiming that the measured value is "fast enough".

## Required event

The qualifier does **not** accept a caller-authored envelope as release
authority. It reads three concrete source receipt files from one evidence root:

1. `perception_received`
2. `cognition_completed`
3. `outward_started`

Each source receipt is bounded, regular, non-symlink UTF-8 JSON and is hashed
with SHA-256 from its exact bytes. All three receipts must bind the same
`candidate_git_sha`, `event_id`, `runtime_epoch` and `observer_id`.
The files and their byte digests must be distinct.

The perception receipt binds a concrete real input identity. The cognition
receipt must bind the canonical cognition event id, a nonblank transition
receipt and at least one completed real cycle. The outward receipt must state
`started=true` and carry the required runtime identity: `utterance_id` for
voice, `body_runtime_id` for body, or both for `voice+body`. A queued
request is not outward-start evidence.

The clock contract is exact:

```json
{
  "kind": "monotonic",
  "unit": "milliseconds",
  "origin": "single-observer"
}
```

This avoids cross-machine wall-clock skew. Timestamps must satisfy:

```text
perception_received <= cognition_completed <= outward_started
```

The qualifier derives:

- perception → cognition milliseconds;
- cognition → outward milliseconds;
- total perception → outward milliseconds.

`outward_kind` must be `voice`, `body`, or `voice+body`.

## Authority boundary

A valid verdict contains:

```json
{
  "state": "MEASURED",
  "threshold_applied": false,
  "end_to_end_latency_gate_satisfied": true,
  "release_gate_satisfied": false,
  "production_activation": false
}
```

The canonical release reference is:

```text
kaliv-end-to-end-latency:<modelrig-sha>:<sha256>
```

The system release gate accepts exactly one such reference for
`end_to_end_latency=PASS`. The embedded ModelRig SHA must equal the pinned
release SHA or be its Git ancestor with the exact same tree, permitting only a
clean merge-commit identity change.

A later physical baseline may establish an SLO. Until that happens, this
qualifier must continue to report `threshold_applied=false`; CI must not invent
or infer a threshold.

## Run

Store all three receipts below one evidence directory and invoke the qualifier
with explicit paths:

```powershell
python scripts/kaliv_end_to_end_latency_qualifier.py `
  --evidence-root .\validation\latency-event-001 `
  --perception perception_received.json `
  --cognition cognition_completed.json `
  --outward outward_started.json `
  --report .\validation\kaliv-end-to-end-latency-latest.json
```

A successful run exits 0 and emits a content-addressed
`release_evidence_ref` plus the relative path and SHA-256 of every validated
source receipt. Missing/unreadable/oversized/path-escaped/symlinked receipts,
hash-content substitution via reused receipt bytes, mixed candidate/event/
runtime-epoch/observer identity, replay/simulation, incomplete cognition,
queued-but-not-started outward behavior, non-monotone timing, or authority
overclaim exits 2.

Legacy hand-authored v1 latency envelopes are intentionally no longer accepted
as release evidence.
