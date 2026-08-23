# BodyRig Runtime Protocol v0.1

This document defines the logical contracts between ModelRig, VoiceRig and BodyRig. Transport is deliberately unspecified in v0.1; JSON examples represent the canonical semantic payloads and can later map to WebSocket, gRPC, local IPC or another transport.

## 1. Identifiers and clock

Every real-time event carries:

- `session_id`
- `sequence`
- `timestamp_ms` on a monotonic session clock

Speech-related events additionally carry `utterance_id`.

Consumers MUST reject stale sequence numbers within a session.

## 2. ModelRig -> BodyRig: ExpressionPlan

```json
{
  "type": "bodyrig.expression_plan",
  "version": "0.1",
  "session_id": "s_123",
  "sequence": 184,
  "timestamp_ms": 15520,
  "state": "speaking",
  "emotion": {
    "name": "amused",
    "intensity": 0.42
  },
  "gesture": {
    "intent": "explain",
    "intensity": 0.55,
    "optional": true
  },
  "gaze": {
    "target": "user",
    "intensity": 0.8
  },
  "energy": 0.48
}
```

Required principle: these fields describe intent. They never describe bones, morph target weights or renderer objects.

## 3. State event

For fast turn-taking, state may be sent separately from a full ExpressionPlan.

```json
{
  "type": "bodyrig.state",
  "version": "0.1",
  "session_id": "s_123",
  "sequence": 185,
  "timestamp_ms": 15532,
  "state": "listening",
  "transition_ms": 120
}
```

Allowed MVP states:

- `idle`
- `listening`
- `thinking`
- `speaking`
- `waiting_for_tool`
- `interrupted`
- `error`

## 4. VoiceRig -> BodyRig: speech lifecycle

### Speech start

```json
{
  "type": "bodyrig.speech.start",
  "version": "0.1",
  "session_id": "s_123",
  "utterance_id": "u_44",
  "sequence": 190,
  "timestamp_ms": 16000,
  "audio_clock_ms": 0
}
```

### Streaming viseme frame

```json
{
  "type": "bodyrig.speech.viseme",
  "version": "0.1",
  "session_id": "s_123",
  "utterance_id": "u_44",
  "sequence": 191,
  "timestamp_ms": 16020,
  "audio_offset_ms": 20,
  "visemes": [
    {"id": "aa", "weight": 0.71},
    {"id": "oh", "weight": 0.12}
  ]
}
```

BodyRig MAY map canonical viseme IDs to avatar-specific blendshapes.

### Prosody hint

```json
{
  "type": "bodyrig.speech.prosody",
  "version": "0.1",
  "session_id": "s_123",
  "utterance_id": "u_44",
  "sequence": 192,
  "timestamp_ms": 16100,
  "audio_offset_ms": 100,
  "energy": 0.58,
  "pitch_relative": 0.12,
  "rate_relative": -0.05
}
```

Prosody hints are optional and MUST degrade gracefully when unavailable.

### Speech end

```json
{
  "type": "bodyrig.speech.end",
  "version": "0.1",
  "session_id": "s_123",
  "utterance_id": "u_44",
  "sequence": 240,
  "timestamp_ms": 20120,
  "audio_offset_ms": 4120
}
```

## 5. Interruption / cancellation

This is a first-class protocol operation.

```json
{
  "type": "bodyrig.cancel",
  "version": "0.1",
  "session_id": "s_123",
  "sequence": 241,
  "timestamp_ms": 20140,
  "scope": "utterance",
  "utterance_id": "u_44",
  "reason": "user_interrupted",
  "transition_ms": 80
}
```

Upon accepted cancellation BodyRig MUST:

1. stop consuming queued viseme/prosody frames for the target utterance;
2. release mouth shapes toward neutral;
3. cancel or gracefully exit speech gestures;
4. transition to `interrupted` and then the next commanded state;
5. prevent stale queued events from reactivating the cancelled utterance.

## 6. BodyRig -> orchestrator/client: RuntimeState

```json
{
  "type": "bodyrig.runtime_state",
  "version": "0.1",
  "session_id": "s_123",
  "sequence": 310,
  "timestamp_ms": 20200,
  "state": "listening",
  "active_utterance_id": null,
  "active_gesture": null,
  "bodyprint_id": "01J...",
  "health": "ok"
}
```

## 7. Attention targets

Canonical MVP targets:

- `user`
- `camera`
- `screen`
- `object:<id>`
- `world:<x,y,z>` when spatial coordinates are available
- `away`
- `none`

Renderer adapters resolve canonical targets into device-specific transforms.

## 8. Gesture resolution

When ModelRig requests `gesture.intent = explain`, runtime selects in order:

1. matching person-specific bodyprint gesture;
2. compatible procedural gesture using bodyprint style parameters;
3. neutral generic gesture;
4. no gesture if request was optional.

This guarantees graceful degradation.

## 9. Error semantics

Runtime errors are classified as:

- `invalid_event`
- `unsupported_version`
- `bodyprint_invalid`
- `avatar_unavailable`
- `timeline_desync`
- `renderer_error`

Malformed external events MUST NOT crash the animation runtime.

## 10. Transport requirements for later ADR

Any selected transport must support:

- bidirectional streaming
- ordered events per session
- low local latency
- cancellation
- reconnect/session recovery
- authentication when crossing process/device boundaries

Transport selection is intentionally deferred until integration constraints from ModelRig, VoiceRig and the first renderer are measured.
