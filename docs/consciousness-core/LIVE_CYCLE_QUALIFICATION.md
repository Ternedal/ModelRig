# Live Consciousness cycle qualification

This probe is the first physical/runtime evidence step after C31 A-H software qualification.

It exercises the **existing** loopback-only production surfaces:

```text
POST /experimental/consciousness/user-turn
        ↓
canonical C21-A admission
        ↓
one pending CognitionEvent
        ↓
POST /experimental/consciousness/step-event
        ↓
canonical C22-C WAIT/RUN policy
        ↓
exactly one bounded RUN
```

No new runtime route, scheduler, thread, timer, model authority or activation path
is introduced by the probe.

## Prerequisites

Run the worker from a clean checkout with the existing reviewed gates enabled:

```text
KALIV_CONSCIOUSNESS_CORE_ENABLED=1
KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED=1
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED=1
```

A valid local CognitiveProfile must already be configured for C22.

The worker URL must remain loopback-only. The repository default is:

```text
http://127.0.0.1:8099
```

## Run

From the exact candidate checkout:

```powershell
python scripts\consciousness_live_cycle_probe.py
```

or explicitly:

```powershell
python scripts\consciousness_live_cycle_probe.py `
  --worker-url http://127.0.0.1:8099 `
  --report validation\consciousness-live-cycle-latest.json
```

The probe:

1. requires an exact clean Git SHA;
2. checks worker health over loopback;
3. admits one unique reported user turn through C21-A;
4. verifies that admission itself made zero model calls;
5. binds the returned exact CognitionEvent id into C22-C;
6. accepts bounded WAIT receipts without converting them into hidden runtime retry;
7. issues at most six explicit operator-side step requests;
8. requires one canonical RUN with exactly one ThoughtEngine call;
9. validates the authority-denial fields on both receipts;
10. writes one atomic machine-readable report.

The report intentionally excludes the generated probe user text.

## What a PASS proves

A PASS proves that the exact checkout can perform a real live:

```text
user evidence
→ WorldState admission
→ supervisor attention
→ exact-event selection
→ one ThoughtEngine cycle
→ one live context transition
```

through the production-wired C19/C21/C22 seams.

It also records request latency for admission and each bounded step attempt.

## What a PASS does NOT prove

A live-cycle PASS is **not** the final `consciousness_live_lifecycle` release gate.

The receipt therefore always keeps:

```text
full_lifecycle_qualified=false
model_swap_qualified=false
dormancy_restart_qualified=false
release_gate_satisfied=false
production_activation=false
```

The remaining lifecycle qualification must additionally prove, on the same
release lineage:

- planned or unplanned dormancy followed by explicit wake reorientation;
- restart without fabricated cognition during the gap;
- replaceable ThoughtEngine/CognitiveProfile without identity/person drift;
- continuity evidence that binds the pre/post lifecycle transitions.

This prevents a single successful cognitive turn from being mistaken for full
persistent-life qualification.
