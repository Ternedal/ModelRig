# BodyRig Roadmap

## M0 — Embodiment runtime proof

Goal: prove that ModelRig + VoiceRig can drive a believable, interruptible humanoid avatar before attempting body cloning.

Deliverables:
- runtime state machine
- VRM-capable Unity proof renderer
- semantic ExpressionPlan ingestion
- gaze controller
- idle/listen/think/speak states
- streaming viseme adapter
- gesture scheduler
- interruption/cancel path
- deterministic demo harness

Acceptance gate:
- all required states visibly distinct
- speech begins without waiting for a complete utterance
- interruption returns to listening cleanly
- no ModelRig bone/morph commands

## M1 — Video analysis + motion bodyprint

Goal: create a bodyprint from ordinary video that captures movement style without requiring visual reconstruction.

Deliverables:
- video ingest pipeline
- frame quality and coverage scoring
- body pose tracking
- hand tracking
- facial behavior tracking
- normalized timeline representation
- motion statistics extraction
- gesture candidate segmentation
- bodyprint builder + validator

Acceptance gate:
- two different source subjects produce measurably different motion profiles
- at least one person-specific gesture can be replayed/retargeted
- source video is no longer required after bodyprint creation

## M2 — Face behavior + expressive clone

Goal: make the avatar's non-verbal facial behavior recognizably source-specific.

Deliverables:
- blink/gaze/expression priors
- head motion signature
- expression intensity calibration
- runtime face mixer
- VoiceRig viseme + expression coexistence

Acceptance gate:
- lipsync does not overwrite emotional expression
- source-specific blink/head/expression behavior is visible in blind A/B comparison against generic behavior

## M3 — Visual body reconstruction

Goal: add likeness while preserving engine replaceability.

Deliverables:
- reconstruction adapter interface
- one baseline reconstruction backend
- avatar/mesh conversion pipeline
- human review/refinement step if required
- avatar embedding/reference in bodyprint

Acceptance gate:
- reconstruction backend can be replaced without changing runtime protocol
- resulting avatar retargets M1/M2 motion correctly

## M4 — Multi-client embodiment

Goal: demonstrate one bodyprint/session protocol on multiple presentation surfaces.

Targets:
- Windows
- Android
- Quest/MR

Acceptance gate:
- same bodyprint and semantic protocol used unchanged on all targets
- renderer-specific implementation remains behind adapters

## M5 — Spatial presence

Goal: transform the avatar from a viewport object into a spatial agent.

Deliverables:
- world-space placement
- user/head position target
- spatial gaze
- object attention targets
- proximity-aware posture/gesture constraints
- Quest/MR demo

Acceptance gate:
- avatar can be placed in a room and maintain correct user-relative gaze and speaking behavior

## Engineering work order

### Phase A — contracts first
1. lock bodyprint v0.1 schemas
2. lock ExpressionPlan/state/cancel protocol
3. build protocol conformance tests

### Phase B — runtime
4. build headless state machine
5. build animation scheduler
6. add gaze and procedural idle
7. add VoiceRig timing adapter
8. add interruption tests

### Phase C — first renderer
9. Unity/VRM renderer adapter
10. deterministic canned demo
11. end-to-end local integration

### Phase D — analysis
12. video ingest
13. pose/hand/face tracks
14. quality scoring
15. motion fingerprint
16. gesture extraction
17. bodyprint serialization

### Phase E — clone quality
18. expression behavior
19. advanced reconstruction adapters
20. multi-client optimization

## First coding slice

The first implementation PR should contain no ML dependency at all. Build:

- bodyprint JSON schemas + validator
- protocol models
- runtime state machine
- cancellation semantics
- deterministic tests

Why: these contracts are stable foundations and can be tested in CI without GPU/model downloads. Video-analysis engines are then plugged into a contract that already exists.

## Definition of done for bootstrap

Bootstrap phase is done when:
- architecture docs are reviewed
- schemas validate sample packages/events
- CI runs schema/protocol tests
- first implementation issue set exists
- no runtime/reconstruction technology choice is hidden as an implicit dependency
