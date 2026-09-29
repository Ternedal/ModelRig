# Live Consciousness lifecycle qualification

This is the operator-side evidence boundary for the
"consciousness_live_lifecycle" system release gate.

It builds on the live-cycle probe and does **not** add runtime authority.

## Required evidence

One qualification bundle must bind all three evidence classes to the same exact
ModelRig Git SHA:

1. **Live cycle** — a passing
   "kaliv-consciousness-core/live-cycle-probe/v1" report.
2. **Dormancy/restart** — a C31-D
   "dormancy-bridge-receipt/v1" collected after an actual process restart,
   with "restart_proven=true", "cognition_during_gap=false", and explicit
   wake reorientation.
3. **Model swap** — a C31-G
   "model-swap-continuity-receipt/v1" proving the CognitiveProfile changed
   while identity, Person binding, SelfState, durable-memory binding and lived
   continuity remained preserved.

The dormancy and model-swap receipts must also agree on the exact Self identity
and Person revision.

The C31-D/C31-G receipt schemas themselves do not carry a Git SHA. Their
candidate binding is therefore **operator-envelope binding**, not cryptographic
receipt-native provenance: the qualification input must be assembled from the
source artifacts collected on that exact checkout, and the emitted evidence
references SHA-256-bind the resulting payloads. Do not reinterpret the verdict
as proof that an arbitrary copied receipt originated from the candidate SHA.

## Run

Create an evidence JSON bundle and run:

    python scripts/consciousness_live_lifecycle_qualifier.py ^
      validation/consciousness-live-lifecycle-input.json ^
      --report validation/consciousness-live-lifecycle-latest.json

A successful verdict contains:

    state=QUALIFIED
    live_cycle_qualified=true
    dormancy_restart_qualified=true
    model_swap_qualified=true
    identity_lineage_preserved=true
    full_lifecycle_qualified=true
    consciousness_live_lifecycle_gate_satisfied=true
    production_activation=false

The emitted "evidence_refs" are deterministic SHA-256 references to the exact
three evidence payloads. One of those references, or the qualification report
itself, can be supplied as evidence for the "consciousness_live_lifecycle"
entry in the cross-repository Kaliv release manifest.

## Fail-closed rules

The qualifier rejects the bundle if:

- any evidence item is bound to a different Git SHA;
- the live-cycle probe did not perform exactly one successful RUN;
- the dormancy receipt permits cognition during the offline gap;
- restart was not explicitly proven;
- wake reorientation was not explicit;
- model-swap continuity did not preserve identity/state/memory bindings;
- dormancy and model-swap identity lineage disagree;
- any component claims identity, persistence, durable-memory, execution,
  scheduling, model, timer, thread or production authority that it does not own;
- the input attempts to set "production_activation=true".

This qualifier proves only the Consciousness lifecycle release gate. It does not
claim that the full cross-repository Kaliv release is ready; the remaining system
release gates remain independently required.
