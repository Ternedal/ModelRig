# ModelRig Body Package (`.mrbody`) v1

`.mrbody` is a versioned, data-only ZIP container used to move a BodyRig body/avatar profile between BodyRig, ModelRig and renderer clients.

It deliberately contains no model checkpoints, Python objects, native code, scripts, Unity packages or plugins.

## Required files

```text
manifest.json
checksums.json
avatar.vrm
bodyprint.json
provenance.json
thumbnail.png
```

## Optional motion files

V1 may contain only the following optional motion paths:

```text
motions/idle.vrma
motions/walk.vrma
motions/talk.vrma
motions/gesture_01.vrma
motions/gesture_02.vrma
motions/gesture_03.vrma
```

No other archive path is valid in V1.

## Manifest

Example:

```json
{
  "format": "modelrig-body",
  "format_version": 1,
  "id": "anders-body-12345678",
  "name": "Anders",
  "avatar": {
    "format": "vrm",
    "version": "1.0",
    "path": "avatar.vrm"
  },
  "bodyprint": "bodyprint.json",
  "provenance": "provenance.json",
  "thumbnail": "thumbnail.png",
  "builder": {
    "name": "bodyrig",
    "version": "0.1.0"
  }
}
```

`id` is a local runtime identity and must use a path-safe slug. V1 permits only lowercase letters/digits plus `æøå`, `_` and `-`, with a maximum length of 160 characters.

Importer code must validate the id before materializing any files.

## Bodyprint

`bodyprint.json` describes portable physical and behavioural characteristics and must not contain opaque engine-specific tensors.

Example:

```json
{
  "format": "modelrig-bodyprint",
  "version": 1,
  "shape": {
    "height_scale": 1.0,
    "shoulder_to_height": 0.24,
    "hip_to_height": 0.19,
    "arm_to_height": 0.44,
    "leg_to_height": 0.53
  },
  "motion": {
    "energy": 0.42,
    "gesture_frequency": 0.37,
    "gesture_amplitude": 0.48,
    "head_motion": 0.31,
    "turn_speed": 0.46,
    "walk_cadence_spm": 108.0
  },
  "expression": {
    "blink_rate_per_min": 16.0,
    "gaze_strength": 0.45,
    "head_tilt": 0.28,
    "speech_motion": 0.52
  },
  "runtime": {
    "idle_strength": 0.35,
    "gaze_smoothing": 0.7,
    "gesture_intensity": 0.55,
    "breathing_strength": 0.2
  }
}
```

Values which could not be observed reliably should be omitted rather than guessed.

Normalized intensity-style fields are finite numbers in `0.0 .. 1.0`.

## Provenance

`provenance.json` records how the synthetic body profile was produced without embedding private source-media identifiers.

Minimum V1 fields:

```json
{
  "format": "modelrig-body-provenance",
  "version": 1,
  "created_at": "2026-08-23T12:00:00Z",
  "source": {
    "kind": "user-supplied-local-media",
    "count": 3
  },
  "synthetic_avatar": true,
  "pipeline": [
    {
      "stage": "body-recovery",
      "adapter": "hmr2",
      "revision": "<pinned revision>"
    }
  ]
}
```

Provenance must not claim that BodyRig verified legal rights, identity or consent unless a future product feature actually performs such verification.

## Checksums

`checksums.json` contains lowercase SHA-256 values for exactly every payload file other than `manifest.json` and `checksums.json` itself.

Example:

```json
{
  "avatar.vrm": "<sha256>",
  "bodyprint.json": "<sha256>",
  "provenance.json": "<sha256>",
  "thumbnail.png": "<sha256>"
}
```

Optional motion files, when present, must also be represented exactly once.

## Import safety

A V1 importer must reject before extraction:

- absolute paths;
- path traversal (`..`);
- backslash archive paths;
- duplicate entries;
- encrypted entries;
- any file not explicitly allowed by V1;
- missing required files;
- missing or extra checksum entries;
- checksum mismatch;
- invalid JSON/schema;
- unknown `format` or `format_version`;
- invalid/path-like ids;
- non-finite numeric values;
- values outside schema ranges;
- executables, scripts, DLLs or plugins.

Suggested V1 package limits:

```text
Max archive entries              12
Max total uncompressed           256 MiB
manifest/checksums/bodyprint      512 KiB each
provenance                        512 KiB
thumbnail                           8 MiB
avatar.vrm                        192 MiB
individual .vrma                  32 MiB
```

An importer may choose lower implementation limits but must never silently accept more than the format limits.

## Atomic replacement

Installing/replacing a profile must use a temporary sibling location, validate the complete package, and then perform one atomic replacement. A failed import must leave the previously valid package untouched.

## Runtime portability

The completed `.mrbody` package must animate without the original source videos and without requiring the build-time body-recovery model, SMPL/SMPL-X assets, research checkpoints or Python build environment.

This separation is intentional: build-time model adapters may change across BodyRig versions while the runtime package contract remains stable.
