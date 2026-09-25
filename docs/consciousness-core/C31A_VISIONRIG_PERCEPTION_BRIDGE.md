# C31 — VisionRig perception bridge

Status: implemented on a default-off integration branch.

## C31-A — semantic projection

VisionRig owns sensing and emits `visionrig/perception-event/v2`. ModelRig owns
semantic projection. C31-A converts bounded visual entity observations into
`WorldEvidenceEvent/v1` plans plus attention salience.

It does **not** mutate a session directly.

Detector/OCR labels are projected as `epistemic_status="inferred"`.
`identity_hint` is deliberately ignored; visual recognition is not identity
authority.

Frame-rate load is collapsed through a process-local fingerprint cache. A tracked
entity re-emits only when its semantic label or coarse visual region changes.
Projection is capped at 16 evidence plans per VisionRig event.

## C31-B — explicit transport/admission

```text
VisionRig bounded journal
        |
        | GET /api/v1/perception/events
        | explicit poll_once; max 4 events
        v
VisionRigClient (loopback only)
        |
        v
VisionRigPerceptionProjector
        |
        v
ProductionCognitiveSession.submit_world_evidence()
        |
        +--> C20-A WorldState reducer
        +--> C18-A supervisor CognitionEvent
        +--> existing episode / SelfState-ledger handling
```

C31-B deliberately reuses `ProductionCognitiveSession.submit_world_evidence()`
instead of duplicating world/supervisor admission. This preserves the existing
atomic admission, episode and SelfState-ledger semantics.

If the VisionRig journal reports a cursor gap, C31-B fails closed and requires
explicit resynchronization. There is no silent skip.

If admission fails after some items were accepted, only the non-authoritative
projector cache is rolled back. Retrying re-emits the exact deterministic
evidence; the existing session admission treats already-admitted evidence as
idempotent replay and continues from there.

## Authority invariants

C31 has:

- no pixels or embedding vectors in Consciousness Core;
- no identity-hint promotion;
- no internal polling thread;
- no timer;
- no automatic repeat;
- zero direct model calls;
- zero durable-memory-write authority;
- zero execution authority;
- zero scheduling authority;
- `production_activation=false`.
