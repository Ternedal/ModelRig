# BodyRig System Specification v0.1

Status: bootstrap specification

## 1. Purpose

BodyRig is a standalone embodiment subsystem for the ModelRig ecosystem. It converts source video into a reusable body identity/profile (`bodyprint`) and provides a low-latency runtime that expresses ModelRig intent physically while remaining synchronized with VoiceRig.

## 2. System boundaries

### ModelRig owns
- cognition and response generation
- conversational state
- semantic expression intent
- tool/task state
- high-level attention target

### VoiceRig owns
- speech recognition/audio input
- synthesized speech audio
- speech timing
- phoneme/viseme alignment when available
- prosodic metadata when available

### BodyRig owns
- bodyprint creation/import
- skeletal retargeting
- idle/listen/think/speak/interruption states
- gesture selection and scheduling
- gaze and head movement
- facial expression mixing
- lip animation consumption
- procedural motion
- animation cancellation/blending
- renderer-neutral embodiment state

### Client/renderers own
- scene rendering
- camera and lighting
- device-specific input
- spatial placement
- final graphics quality/performance choices

## 3. Primary components

```text
bodyrig/
  capture/
    ingest
    quality scoring
    frame selection
  analysis/
    pose
    hands
    face
    motion style
    gesture discovery
    gaze/expression statistics
  reconstruction/
    adapter interface
    basic avatar adapter
    optional advanced adapters
  package/
    bodyprint builder
    validator
    provenance
  runtime/
    state machine
    expression planner adapter
    gaze controller
    gesture controller
    face mixer
    lip-sync adapter
    animation mixer
    interruption controller
  renderers/
    unity adapter (first target)
    future adapters
```

## 4. Input requirements

MVP accepts common video files without dedicated mocap hardware.

Minimum usable input:
- one visible person
- enough frames with face and torso visible
- stable enough image quality for tracking

Recommended capture:
- front full-body
- side/profile
- slow turn
- walking
- natural speaking
- free gesticulation
- closer facial speaking segment

The importer MUST grade evidence coverage rather than silently fabricate missing traits.

## 5. Capture quality report

Importer returns independent confidence/coverage scores:

```json
{
  "appearance": 0.72,
  "body_shape": 0.91,
  "motion": 0.84,
  "face_behavior": 0.93,
  "hands": 0.61,
  "gaze": 0.78
}
```

It also returns actionable recommendations such as `more_visible_hands`, `need_full_body`, `need_profile_face`.

## 6. Embodiment states

Required states:

- `idle`
- `listening`
- `thinking`
- `speaking`
- `waiting_for_tool`
- `interrupted`
- `error`

Transitions MUST be blendable and interruptible. A new user turn MUST be able to stop speech-driven animation immediately without leaving a gesture or mouth animation running.

## 7. Motion model

BodyRig MUST separate three layers:

1. **semantic intent** — e.g. `explain`, `uncertain`, `amused`
2. **person-specific style** — bodyprint parameters and learned gesture vocabulary
3. **real-time realization** — animation clip/procedural blend chosen by runtime

ModelRig never sends joint rotations.

Example:

```json
{
  "state": "speaking",
  "emotion": "amused",
  "intensity": 0.42,
  "gesture": "explain",
  "gaze": {"target": "user"}
}
```

## 8. Synchronization

Runtime operates on a monotonic session timeline.

VoiceRig speech chunks and BodyRig expression events share:
- `session_id`
- `utterance_id`
- monotonic timestamps

BodyRig MUST support streaming speech. It MUST NOT wait for an entire utterance before beginning lipsync or speaking-state motion.

## 9. Avatar representation

Initial target: a humanoid avatar format compatible with portable skeletal retargeting and facial expressions. VRM 1.0 is the preferred candidate for the first implementation, but BodyRig internal contracts MUST NOT depend on Unity-specific object structures.

Advanced human reconstruction engines MUST be adapters behind a stable interface.

## 10. Privacy, consent and provenance

Every bodyprint MUST contain:
- source ownership/permission assertion
- creation timestamp
- BodyRig format version
- source fingerprints (hashes, not source media by default)
- reconstruction/analysis engine versions
- synthetic identity marker

BodyRig MUST permit deleting source media after bodyprint creation.

MVP SHOULD default to local processing where practical and MUST make any network upload explicit.

## 11. Performance targets

Runtime target (excluding renderer):
- semantic event acceptance: < 20 ms local
- state transition scheduling: < 1 frame at 60 Hz target renderer cadence
- interruption/cancel dispatch: < 50 ms
- streaming viseme ingestion supported

Offline bodyprint creation has no hard real-time target in MVP.

## 12. MVP acceptance

MVP is accepted only when all are demonstrated:

1. Ordinary video can be ingested without mocap hardware.
2. Pose, hands and face tracks are extracted with per-track confidence.
3. Motion statistics and at least one reusable person-specific gesture are produced.
4. A deterministic `.bodyprint` package is emitted and validates against schema.
5. A humanoid avatar can load the bodyprint and enter every required runtime state.
6. VoiceRig-compatible timing can drive mouth animation during streaming playback.
7. ModelRig-style semantic events control state, gaze, emotion and gesture.
8. Interruption cancels speech/gesture state cleanly.
9. Bodyprint can be consumed without depending on the source video.
10. The same protocol is suitable for Windows, Android and Quest renderers.
