# Kaliv end-to-end latency qualification

`scripts/kaliv_end_to_end_latency_qualifier.py` produces the canonical evidence
for the `end_to_end_latency` Kaliv system release gate.

This is deliberately a **measurement gate**, not an invented performance SLO.
The repository does not yet have a physically established cross-rig latency
threshold, so this qualifier proves and records one real correlated traversal
without claiming that the measured value is "fast enough".

## Required event

The input evidence must represent one real, non-simulated event observed by one
monotonic clock. The same bounded `event_id` must appear at all three phases:

1. `perception_received`
2. `cognition_completed`
3. `outward_started`

Each phase carries its own nonblank evidence reference. The references must be
distinct so one artifact cannot be reused to impersonate multiple stages.

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

```powershell
python scripts/kaliv_end_to_end_latency_qualifier.py .\latency-evidence.json `
  --report .\validation\kaliv-end-to-end-latency-latest.json
```

A successful run exits 0 and emits a content-addressed
`release_evidence_ref`. Invalid, simulated, cross-event, non-monotone, or
overclaiming evidence exits 2.
