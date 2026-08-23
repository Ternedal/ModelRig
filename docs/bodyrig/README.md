# BodyRig

BodyRig is the embodiment layer for ModelRig: the visual and physical counterpart to VoiceRig.

## Mission

Turn ordinary video material into a reusable `bodyprint` that can drive a real-time avatar across Windows, Android and Quest-class clients.

BodyRig does not own intelligence or personality. ModelRig remains the brain. VoiceRig owns speech/listening. BodyRig turns semantic intent, voice timing and a body profile into synchronized physical expression.

## Core flow

```text
video/images
    |
    v
BodyRig Capture + Analysis
    |
    +--> appearance profile
    +--> body/skeleton profile
    +--> motion signature
    +--> face/expression profile
    +--> gaze/gesture profile
    |
    v
.bodyprint package
    |
    v
BodyRig Runtime <--- ModelRig ExpressionPlan
       ^          <--- VoiceRig audio + visemes/timing
       |
       v
VRM 1.0 avatar + animation runtime
       |
       +--> Windows
       +--> Android
       +--> Quest / MR
```

## MVP principle

MVP proves *embodiment*, not photorealism.

The first release is successful when a normal video can produce a reproducible bodyprint whose movement, gaze, facial style and gestures can be applied to a VRM avatar in real time and synchronized with VoiceRig.

Photorealistic body/face reconstruction is deliberately a later milestone.

## Non-goals for MVP

- No LLM-generated bone rotations.
- No hard dependency on one body reconstruction model.
- No requirement for mocap hardware.
- No requirement for photorealistic skin/hair/clothing.
- No intelligence/personality duplicated inside BodyRig.

## Architecture invariants

1. ModelRig emits semantic intent, never low-level animation transforms.
2. VoiceRig is authoritative for speech audio and lip timing.
3. BodyRig runtime is deterministic and interruptible.
4. A bodyprint is renderer-independent.
5. Avatar reconstruction backends are replaceable adapters.
6. Provenance and consent metadata travel with every bodyprint.

See:

- `SPEC.md` — system architecture and requirements
- `BODYPRINT.md` — package format v0.1
- `PROTOCOL.md` — ModelRig/VoiceRig/BodyRig contracts
- `ROADMAP.md` — implementation milestones and acceptance gates
