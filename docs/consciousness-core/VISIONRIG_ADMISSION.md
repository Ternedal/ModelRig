# VisionRig -> Consciousness Core admission

This adapter connects VisionRig `PerceptionEvent/v3` to the existing C20
WorldEvidence boundary. It does not create a second world model.

## Activation

The route is absent unless the exact opt-in is set:

```text
KALIV_CONSCIOUSNESS_VISIONRIG_ENABLED=1
```

When enabled, the private loopback-only endpoint is:

```text
POST /experimental/consciousness/visionrig-event
```

The request body is a strict `visionrig/perception-event/v3` object and is
bounded to 256 KiB. Loopback admission happens before body parsing. The route
also requires an `application/json` media type before parsing; simple
cross-origin browser POST media types such as `text/plain` are rejected.

## Epistemic mapping

VisionRig results are projected as:

```text
WorldEvidenceEvent
epistemic_status = inferred
source_ref       = canonical SHA-256 of the complete VisionRig event
subject_ref      = hashed VisionRig sensor descriptor
observed_sequence= VisionRig frame sequence
```

The bridge intentionally labels the result `inferred`, not `observed`.
Object detection, recognition and spatial fusion are interpretations of sensor
data even when some measurements (such as Kinect depth) are metric.

## Cognitive summary

The proposition is deliberately bounded and structural. It can contain:

- entity-kind counts;
- up to six highest-confidence non-text labels;
- inferred scene/place label plus its confidence when present;
- count + nearest measured metric depth;
- relation predicate counts;
- OCR item count;
- landmark-group count;
- dropped-frame count.

It deliberately does **not** place raw OCR text, `identity_hint`, raw
landmarks, RGB pixels, IR arrays or depth maps into Consciousness Core context.
Those require separately reviewed semantics.

## Attention

Admission reuses C20-B. A new event updates transient WorldState first and queues
one linked `world_change` cognition event. The deterministic salience heuristic
can increase for people, close measured objects and interaction/motion
relations, but is capped below 1.0.

Admission itself performs no ThoughtEngine call. Existing supervisor policy owns
whether a later cognitive step runs.

## Authority

The receipt fixes:

```text
model_calls=0
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

VisionRig therefore supplies sensory evidence and attention candidates without
gaining memory, tool, scheduler, BodyRig, VoiceRig or action authority.
