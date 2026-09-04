# `.bodyprint` Package Specification v0.1

A bodyprint is a portable, renderer-independent embodiment profile. It is a ZIP-compatible container with a `.bodyprint` extension.

## Package layout

```text
<identity>.bodyprint
  manifest.json
  avatar/
    avatar.vrm                  # optional in early profiles
  identity/
    body.json
    face.json
    appearance.json
  motion/
    style.json
    gestures.json
    clips/                      # optional reusable animations
  behavior/
    gaze.json
    posture.json
    expression.json
    idle.json
  provenance/
    source.json
    engines.json
    hashes.json
```

## Design rules

- Unknown evidence is represented as unknown/confidence, never invented as fact.
- Runtime-critical behavior is stored as normalized semantic parameters, not renderer-specific bone transforms.
- Raw source video is not embedded by default.
- Avatar geometry is optional: a bodyprint may describe motion/behavior only and be applied to another compatible avatar.
- Package readers must ignore unknown optional fields for forward compatibility.

## `manifest.json`

```json
{
  "format": "bodyrig.bodyprint",
  "version": "0.1.0",
  "id": "01J...",
  "created_at": "2026-08-23T00:00:00Z",
  "display_name": "Example",
  "capabilities": [
    "motion_style",
    "face_behavior",
    "gaze",
    "gestures"
  ],
  "avatar": {
    "path": "avatar/avatar.vrm",
    "format": "vrm-1.0",
    "optional": true
  },
  "confidence": {
    "appearance": 0.72,
    "body_shape": 0.91,
    "motion": 0.84,
    "face_behavior": 0.93,
    "hands": 0.61,
    "gaze": 0.78
  }
}
```

## `identity/body.json`

Contains normalized, non-renderer-specific body characteristics and evidence quality.

```json
{
  "height": {"value_m": null, "confidence": 0.0},
  "proportions": {
    "shoulder_to_height": {"value": 0.24, "confidence": 0.82},
    "arm_to_height": {"value": 0.44, "confidence": 0.79}
  },
  "dominant_hand": {"value": "right", "confidence": 0.74}
}
```

Absolute real-world dimensions MUST remain null unless calibrated evidence exists.

## `motion/style.json`

```json
{
  "schema": "bodyrig.motion-style/0.1",
  "gesture_energy": 0.64,
  "gesture_frequency_hz": 0.18,
  "movement_smoothness": 0.77,
  "posture": {
    "upright": 0.71,
    "forward_lean": 0.18,
    "lateral_bias": -0.03
  },
  "head": {
    "activity": 0.31,
    "nod_rate_hz": 0.04,
    "tilt_bias": 0.08
  },
  "arms": {
    "range": 0.58,
    "symmetry": 0.34
  }
}
```

## `motion/gestures.json`

Reusable gestures discovered from source material.

```json
{
  "gestures": [
    {
      "id": "right_hand_explain_01",
      "semantic_tags": ["explain", "emphasis"],
      "duration_ms": 1240,
      "confidence": 0.86,
      "handedness": "right",
      "clip": "clips/right_hand_explain_01.vrma"
    }
  ]
}
```

A gesture MAY have no clip and instead contain normalized procedural features.

## `behavior/gaze.json`

```json
{
  "direct_gaze_ratio": 0.61,
  "mean_hold_ms": 1450,
  "away_glance_rate_hz": 0.09,
  "thinking_bias": "up_left",
  "confidence": 0.78
}
```

These are style priors, not commands. Runtime gaze targets always take precedence.

## `behavior/expression.json`

```json
{
  "smile_intensity_mean": 0.42,
  "blink_rate_hz": 0.24,
  "brow_activity": 0.37,
  "expression_energy": 0.51,
  "smile_asymmetry": -0.08
}
```

## Provenance

`provenance/source.json` MUST contain:

```json
{
  "permission_asserted": true,
  "permission_basis": "self_or_authorized",
  "raw_media_embedded": false,
  "source_count": 3,
  "synthetic_identity": true
}
```

`provenance/hashes.json` stores cryptographic source fingerprints when enabled. The package MUST NOT require source media to function at runtime.

## Validation

A bodyprint is valid when:
- `manifest.json` exists and uses a supported major version;
- all referenced paths exist;
- required JSON documents parse and satisfy their schema;
- numeric normalized values are finite and within declared ranges;
- optional avatar/clip files match their declared formats;
- provenance metadata is present.

The validator MUST fail closed on malformed packages rather than attempting permissive recovery.
