# BodyRig V1 — virtual embodiment for ModelRig

## Purpose

BodyRig is the visual/physical embodiment layer for ModelRig.

The system boundary is intentionally strict:

- **ModelRig** thinks, plans and produces semantic intent.
- **VoiceRig** listens and speaks.
- **BodyRig** turns identity, speech timing and semantic intent into visible face/body behaviour.
- **Kaliv / VR clients** render and present the resulting embodiment.

BodyRig must not grow a separate assistant personality or reasoning layer. It is a motor/embodiment system driven by ModelRig and VoiceRig.

## Product goal

The normal user flow should be as simple as VoiceRig:

> choose 1–10 ordinary video clips → name the body/avatar → BodyRig finds the subject, extracts a body profile and reusable motion/style information → export/install a portable `.mrbody` package.

The user should not need to choose ML models, skeleton formats, frame rates, pose estimators or renderer settings in the normal flow.

## V1 scope

BodyRig V1 targets a useful, local-first clone rather than a research-demo photorealistic human.

V1 must provide:

1. video ingest through FFmpeg;
2. automatic person detection/tracking across clips;
3. explicit user selection only when the intended person is genuinely ambiguous;
4. body-shape/proportion recovery from the best usable frames;
5. temporal pose/motion extraction from usable sequences;
6. a normalized `bodyprint.json` describing proportions, motion style and expressivity;
7. a rigged VRM 1.0 avatar as the runtime-neutral visual asset;
8. a portable, checksummed `.mrbody` package;
9. a local runtime API for semantic body cues from ModelRig;
10. synchronization hooks for VoiceRig speech/viseme timing;
11. one reference renderer/SDK path for Windows/Android/Quest-class Unity clients;
12. fail-closed validation of package format, paths, checksums and schema versions.

V1 does **not** claim perfect photorealistic face reconstruction from arbitrary internet video. Face identity fidelity is a separately replaceable pipeline stage. BodyRig must be able to improve that stage later without changing the ModelRig/VoiceRig runtime contract.

## Local-first and source handling

Source videos are private input material and are not part of the portable profile by default.

BodyRig should store only the derived package and bounded build metadata after a completed build unless the user explicitly keeps sources.

A support bundle must never contain:

- source video;
- extracted raw frames;
- `.mrbody` packages;
- private ModelRig tokens;
- model-provider credentials.

## Portable package: `.mrbody`

`.mrbody` is the BodyRig equivalent of `.mrvoice`.

It is a ZIP container with data-only content. It must never contain executable code, DLLs, scripts, plugins or native libraries.

Minimum V1 payload:

```text
manifest.json
checksums.json
avatar.vrm
bodyprint.json
provenance.json
thumbnail.png
```

Optional V1 payloads:

```text
motions/idle.vrma
motions/walk.vrma
motions/talk.vrma
motions/gesture_01.vrma
motions/gesture_02.vrma
motions/gesture_03.vrma
```

The authoritative runtime asset is `avatar.vrm`; the authoritative behavioural identity is `bodyprint.json`. Engine-specific intermediate tensors, SMPL/SMPL-X model files, checkpoints and serialized Python objects must not be embedded in the package.

## Bodyprint

`bodyprint.json` is a portable behavioural/physical identity profile, analogous to VoiceRig's voice profile.

V1 separates four concerns:

### Shape

- normalized height/proportion ratios;
- shoulder/hip/limb proportions;
- rest-pose corrections;
- avatar scale metadata.

### Motion style

- typical movement energy;
- gesture frequency;
- gesture amplitude;
- head-motion amplitude;
- posture tendency;
- turn speed;
- walking cadence when enough source data exists.

### Expression style

- blink rate range;
- gaze movement strength;
- head-tilt tendency;
- smile/expression intensity baseline;
- speech-related head/upper-body motion strength.

### Runtime defaults

- idle profile;
- gaze smoothing;
- gesture intensity;
- breathing/micro-motion strength;
- personal-space defaults for spatial clients.

A missing observation must remain `unknown`/absent rather than being invented from the source person's identity.

## Build pipeline

The first implementation should use replaceable adapters so research-model licensing does not become the product architecture.

```text
Video files
    |
    v
FFmpeg normalize / frame sampling
    |
    v
Person detector + tracker
    |
    +---- ambiguity? ----> short user selection
    |
    v
Body/pose recovery adapter
    |
    +----> shape observations
    +----> temporal joint motion
    |
    v
Motion-style extractor
    |
    v
Avatar fitting / rigging adapter
    |
    v
VRM 1.0 exporter
    |
    v
.mrbody builder + full validator
```

### Initial research adapter

A practical first candidate is HMR2/4D-Humans for video human-mesh recovery/tracking because the code is MIT-licensed and already outputs tracked 3D body parameters from video. Body-model assets such as SMPL/SMPL-X have their own restrictive terms and therefore must be an optional, user-obtained build dependency rather than redistributed BodyRig assets.

GVHMR is useful as an evaluation/experimental adapter for world-grounded motion, but its upstream software license is non-commercial/research-oriented and must not become a hard product dependency.

Face reconstruction engines such as DECA likewise have restrictive non-commercial licensing; V1 should keep face-identity reconstruction behind an adapter boundary and not make DECA a mandatory redistributed dependency.

## VRM as runtime asset

BodyRig V1 standardizes on **VRM 1.0** for the portable avatar.

Reasons:

- based on glTF 2.0;
- humanoid skeleton semantics;
- expression support;
- mature Unity runtime path through UniVRM;
- usable on Windows and Android-class Unity targets;
- keeps ModelRig independent of Unity and of the cloning engine.

Runtime motion clips may use VRM Animation (`.vrma`) where useful, but semantic cues remain the primary control surface.

## Runtime architecture

```text
                       semantic response
                           + intent
                              |
                              v
                        +-----------+
                        | ModelRig  |
                        +-----+-----+
                              |
                     BodyCue v1 JSON
                              |
                              v
                        +-----------+
                        | BodyRig   |
                        | runtime   |
                        +-----+-----+
                              ^
                              |
                    speech timing / visemes
                              |
                        +-----+-----+
                        | VoiceRig  |
                        +-----------+

BodyRig runtime output -> Kaliv Windows / Kaliv Android / Unity VR client
```

ModelRig sends **meaning**, not bone rotations.

Example:

```json
{
  "type": "modelrig-body-cue",
  "version": 1,
  "utterance_id": "u-01J...",
  "emotion": "thoughtful",
  "intensity": 0.35,
  "energy": 0.2,
  "gesture": "small_shrug",
  "gaze": "user"
}
```

BodyRig maps the semantic cue to the selected body's own motion profile and animation repertoire.

This is important: two `.mrbody` profiles receiving the same `small_shrug` cue should be allowed to perform visibly different shrugs because their bodyprints differ.

## Runtime API V1

BodyRig should run loopback-only by default, following VoiceRig's local-service pattern.

Proposed default address:

```text
http://127.0.0.1:8775
```

Minimum API surface:

```text
GET  /api/v1/health
GET  /api/v1/bodies
POST /api/v1/bodies/import
POST /api/v1/bodies/{id}/activate
POST /api/v1/runtime/session
POST /api/v1/runtime/cue
POST /api/v1/runtime/speech-timing
GET  /api/v1/runtime/state
```

Long-lived, low-latency animation data can later use a WebSocket transport without changing the semantic cue schema.

## ModelRig integration

ModelRig owns assistant intent. BodyRig receives a bounded structured `BodyCue` generated after response planning.

ModelRig should not emit raw joint transforms or engine-specific animation names.

Recommended ModelRig-side representation:

```text
body.emotion       optional enum/string
body.intensity     0..1
body.energy        0..1
body.gesture       optional semantic gesture id
body.gaze          user | away | object:<id> | neutral
body.posture       optional semantic posture id
body.duration_ms   optional bounded duration hint
```

Unknown fields/versions are rejected by a V1 consumer rather than guessed.

## VoiceRig synchronization

VoiceRig remains the source of synthesized speech audio.

BodyRig accepts a speech-timing side channel keyed by `utterance_id`:

- utterance start/stop;
- phoneme or viseme timing when the active TTS provider exposes it;
- word timing when available;
- fallback audio-energy envelope when no phoneme timing exists.

Lip sync must therefore degrade gracefully:

1. explicit visemes;
2. phoneme-to-viseme mapping;
3. word/audio timing;
4. audio-envelope jaw motion.

The assistant response and body cue must share the same `utterance_id`, preventing stale body animation from being paired with a newer VoiceRig response.

## Renderer/client boundary

BodyRig's core service is not a Unity application.

The renderer consumes:

- `.mrbody` / `avatar.vrm`;
- BodyCue events;
- speech timing;
- runtime state.

The first reference renderer should be a Unity package using VRM 1.0/UniVRM because it gives one path to:

- Windows;
- Android;
- Quest-class IL2CPP clients.

Kaliv can embed or host the renderer without moving cloning logic into the Kaliv codebase.

## Consent and provenance

A generated profile must contain `provenance.json` describing at minimum:

- profile creation timestamp;
- whether sources were user-supplied local files;
- source-count only (not source filenames by default);
- BodyRig version;
- cloning-engine adapter/revision identifiers;
- explicit synthetic-avatar marker.

The runtime must expose that the avatar is synthetic. Provenance is metadata, not DRM, and must not falsely claim identity verification or consent verification that BodyRig did not actually perform.

## Security boundaries

The `.mrbody` importer must validate ZIP metadata before extraction and reject at minimum:

- absolute paths;
- `..` traversal;
- backslashes in archive paths;
- duplicate entries;
- encrypted entries;
- unknown mandatory format versions;
- unknown payload paths;
- missing/extra checksum entries;
- checksum mismatch;
- invalid manifest/bodyprint schemas;
- executables/scripts/plugins;
- unreasonable entry count or expanded-size limits.

Import/build must be atomic: a failed replacement cannot destroy an already-valid body profile.

## Hardware target

The build side should initially target the same practical local-rig class as VoiceRig: Windows 10/11 and an NVIDIA GPU around the RTX 3060 12 GB class.

The **runtime renderer must be much lighter** than the build pipeline. A completed `.mrbody` must not require the original recovery model or SMPL/SMPL-X assets to animate in Kaliv/Quest.

## V1 acceptance gates

BodyRig V1 is not complete until a physical acceptance run proves all of the following on the target rig:

1. ordinary user video can be ingested without manual preprocessing;
2. the intended person is tracked correctly across multiple clips;
3. the generated avatar loads as VRM 1.0;
4. body proportions are recognizably derived from the source rather than a fixed generic body;
5. at least three extracted motion-style characteristics visibly affect runtime animation;
6. ModelRig can drive semantic emotion/gesture/gaze cues;
7. VoiceRig speech can drive synchronized lip/jaw motion;
8. the same `.mrbody` can be loaded by the Windows reference renderer and an Android/Quest-class build;
9. source media remains local and is absent from support output;
10. malformed/oversized/path-traversal packages fail closed.

## Roadmap after V1

### V1.1 — face fidelity

- better face identity fitting;
- hair/head reconstruction adapter;
- expression calibration;
- improved viseme blendshapes.

### V1.2 — behaviour cloning

- learned gesture preference distribution;
- conversational gaze style;
- personalized idle/micro-motion;
- context-dependent gesture selection.

### V2 — spatial embodiment

- Quest passthrough presence;
- gaze toward the user's tracked head/hands;
- personal-space reactions;
- object/pointing references;
- seated/standing environment anchoring.

### V3 — high-fidelity representation

- optional neural/rendered representation adapters;
- richer clothing/hair capture;
- environment-aware contact and locomotion;
- multi-avatar support.

The important architectural rule remains unchanged: **ModelRig is the brain, VoiceRig is the voice/audio interface, BodyRig is the body, and Kaliv/VR are presentation clients.**
