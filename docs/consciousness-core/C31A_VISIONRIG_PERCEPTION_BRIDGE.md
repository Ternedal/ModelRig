# C31-A — VisionRig perception bridge

Status: implemented on a default-off integration branch.

## Boundary

VisionRig owns visual sensing and emits `visionrig/perception-event/v2`.
Consciousness Core does not consume pixels, ONNX tensors or embedding vectors.

ModelRig owns the semantic projection:

```text
VisionRig PerceptionEvent/v2
        |
        v
VisionRigPerceptionProjector
        |
        +--> WorldEvidenceEvent/v1 --> C20-A world reducer
        |
        +--> CognitionEvent/v1 -----> C18-A supervisor
```

No new world-state authority is introduced. The bridge only creates inputs for
the existing authority boundaries.

## Epistemic policy

Detector/OCR labels are projected as `epistemic_status="inferred"`, not as
unquestioned truth. Exact VisionRig event/source refs remain attached as
provenance.

`identity_hint` is deliberately ignored by C31-A. Visual recognition may later
supply identity evidence through an explicit reviewed policy, but a raw
recognition hint cannot rewrite person identity or become identity authority.

## Load policy

Live vision can run at tens of frames per second, while cognitive/world state
must not churn at frame rate. C31-A therefore keeps a process-local,
non-authoritative fingerprint cache:

- tracked entities are keyed by track id and kind;
- only changes in semantic label or coarse screen region are re-emitted;
- unchanged observations are suppressed;
- each VisionRig event is capped at 16 projected evidence items;
- stale per-source frame sequences fail closed.

The cache is an optimization, not durable memory. Replaying the same deterministic
evidence through the Core reducers remains idempotent.

## Authority invariants

The bridge has:

- zero model calls;
- zero durable-memory write authority;
- zero execution authority;
- zero scheduling authority;
- `production_activation=false`.

There is deliberately no internal polling thread or timer in C31-A. A later
transport slice may perform an explicit `poll_once` against VisionRig's bounded
journal, behind its own default-off loopback gate.
