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

## One operator (rig day)

`scripts/consciousness_live_lifecycle_operator.py` runs every step below in
order and stops at the first one that does not hold:

1. preflight: worker on loopback, qualification snapshot enabled, the swap
   profile differs from the current one;
2. the live-cycle probe on the clean checkout;
3. status before the restart, saved as the worker sent it;
4. it asks you to restart the worker, then waits until `runtime_instance_ref`
   has changed and the first lived-continuity snapshot is there (it restarts
   nothing itself);
5. pre-swap snapshot, profile swap, post-swap snapshot in the same runtime,
   and the original profile file put back byte for byte, also on failure;
6. `consciousness_live_lifecycle_from_snapshots.py` and the qualifier.

Run it from the clean candidate checkout, with the worker running with the
consciousness flags and `KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED=1`:

    python scripts\consciousness_live_lifecycle_operator.py `
      --profile-file <the file KALIV_CONSCIOUSNESS_PROFILE_FILE points to> `
      --swap-profile <a copy where only the model calibration differs>

Each run writes to a new `validation/consciousness-lifecycle/<UTC time>/`
with an `operator-run.json` that binds every file by SHA-256. The exit code is
the qualifier's: 0 QUALIFIED, 1 refused, 2 a step failed before it. The manual
steps below remain the reference for what it does.

## Run

Create an evidence JSON bundle and run:

    python scripts/consciousness_live_lifecycle_qualifier.py `
      validation/consciousness-live-lifecycle-input.json `
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
three component evidence payloads. The verdict additionally emits one canonical
release reference:

    consciousness-live-lifecycle:<exact-modelrig-sha>:<verdict-sha256>

The digest is computed over the complete qualification verdict before
"release_evidence_ref" is added, so it is stable and non-self-referential.
The cross-repository Kaliv release manifest must use exactly this canonical
reference for the "consciousness_live_lifecycle" gate; arbitrary labels or a
component evidence ref are not sufficient.

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

## Evidence assembly

The live lifecycle gate is assembled from raw, independently validated evidence
with:

    python scripts/consciousness_live_lifecycle_evidence_assembler.py `
      --candidate-sha <40-hex-modelrig-sha> `
      --live-cycle validation/consciousness-live-cycle-latest.json `
      --before-status validation/consciousness-status-before-restart.json `
      --after-status validation/consciousness-status-after-restart.json `
      --wake-receipt validation/wake-receipt.json `
      --wake-orientation validation/wake-orientation-receipt.json `
      --before-profile validation/profile-before.json `
      --after-profile validation/profile-after.json `
      --before-self-state validation/self-state-before.json `
      --after-self-state validation/self-state-after.json `
      --before-continuity validation/continuity-before.json `
      --after-continuity validation/continuity-after.json `
      --output validation/consciousness-live-lifecycle-input.json

The loopback runtime status now includes an opaque "runtime_instance_ref".
It is stable for one worker process, contains no PID/host/Self/Person identity,
and is regenerated when the worker process starts. Evidence assembly requires
different before/after runtime-instance refs; identical refs fail closed because
a process restart has not been proven.

The assembler does not trust caller-supplied dormancy or model-swap verdicts. It
reconstructs the C31-D dormancy bridge and C31-G model-swap continuity receipt
through the same Core contract functions used by runtime/tests, cross-checks
Self/Person lineage, and writes the qualifier input atomically.

"production_activation" remains false throughout.

## Runtime snapshot flow

For real production-path evidence, enable the qualification surface only for the
local operator session:

    $env:KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED="1"

The endpoint is loopback-only and remains disabled unless the exact flag above
is set.

**Save every response byte for byte with `Invoke-WebRequest -OutFile`.** Do not
round-trip it through `Invoke-RestMethod | ConvertTo-Json | Set-Content`. That
rewrites the response: in PowerShell 7.4.6 the same answer grew from 249 to 753
bytes and a `+00:00` timestamp became `+01:00`, and in Windows PowerShell 5.1
`Set-Content -Encoding utf8` adds a BOM, which the assembler refuses (#2390, F4).

Capture the ordinary privacy-safe status before restarting the worker:

    Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8099/experimental/consciousness/status `
      -OutFile validation/consciousness-status-pre-restart.json

After the worker has restarted and produced one lived-continuity receipt, capture
the first qualification snapshot:

    Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8099/experimental/consciousness/qualification-snapshot `
      -OutFile validation/consciousness-pre-swap.json

Replace only the configured CognitiveProfile/model calibration. Do not run
another cognitive cycle and do not restart the worker. Then capture the second
snapshot:

    Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8099/experimental/consciousness/qualification-snapshot `
      -OutFile validation/consciousness-post-swap.json

Assemble the qualification input directly from those snapshots:

    python scripts/consciousness_live_lifecycle_from_snapshots.py `
      --candidate-sha <40-hex-modelrig-sha> `
      --live-cycle validation/consciousness-live-cycle-latest.json `
      --pre-restart-status validation/consciousness-status-pre-restart.json `
      --pre-swap-snapshot validation/consciousness-pre-swap.json `
      --post-swap-snapshot validation/consciousness-post-swap.json `
      --output validation/consciousness-live-lifecycle-input.json

The adapter requires a changed runtime instance across the restart and the same
runtime instance across the model swap. The production session bootstrap itself
is accepted as C31-D v2 wake-reorientation evidence only when it is an exact
"WAKE_REORIENTATION" receipt bound to the same WakeReceipt, Self and Person
revision and proves no cognition during the gap, no prior transient world or
workspace restoration, no model call and no SelfState-store write.

"production_activation" remains false throughout.

