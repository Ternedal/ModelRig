# Kaliv / ModelRig — Brand Handoff

This directory contains the visual identity and implementation handoff for the Kaliv / ModelRig product family.

## Current authority

Use these files in this order:

1. `brand/KALIV_MODELRIG_UNIFIED_BRAND_IDENTITY.md` — cross-platform brand rules and Ember / Signal semantics.
2. `assets/design/kaliv-ui-guide/kaliv-ui-tokens.json` — canonical production UI-token authority.
3. `docs/design/UNIFIED_BRAND_IMPLEMENTATION_PLAN.md` — implementation status across Android, Windows, Quest and BodyRig.
4. Platform adapters/components — generated Kotlin tokens, `KalivVrBrand.cs`, and BodyRig's shared CSS roles.

Older visual boards and handoff documents remain useful as historical/design references, but they do not override the authorities above.

## Brand architecture

- **Kaliv** — user-facing identity, presence and relationship layer.
- **ModelRig** — platform/orchestration layer.
- **BodyRig / VoiceRig / VisionRig / Consciousness Core** — capability modules within the same visual family.

The Ankh is the master mark. Rig modules do not get competing standalone brand identities.

## Visual state model

- **Ember / warm gold** — identity, persistent state, navigation and primary human-facing actions.
- **Signal / electric blue** — live cognition, inference, listening, perception, runtime and technical telemetry.
- **Semantic green / amber / red** — success, warning and error only.

Do not use Signal blue as the default primary button color and do not use Ember to represent runtime activity.

## Production workflow

Change shared color values in `assets/design/kaliv-ui-guide/kaliv-ui-tokens.json`, then regenerate platform tokens using `scripts/design_tokens.py`.

Do not introduce platform-local copies of canonical Signal hex values. CI guards Android, desktop and VR production code against duplicated Signal literals outside the generated token sources and the Quest brand adapter.

## Platform notes

### Android
Material 3 behavior with Kaliv tokens. Ember remains the normal action language; Signal is reserved for live system state.

### Windows / desktop
Technical surfaces may use Signal more prominently for model/runtime telemetry, while navigation and identity remain Ember.

### Quest / VR
World-space UI uses `KalivVrBrand.cs`. Interactive colliders preserve minimum target dimensions even when the visual button is slimmer.

### BodyRig
BodyRig is visually part of the same family. Signal represents tracking/inference/live projection; Ember represents performer/body authority and persisted identity.

## Assets

Raster concept boards are visual references, not token or vector authority. Canonical vector assets should live under `brand/master/`, `brand/wordmark/`, `brand/lockups/` and platform-specific export folders.
