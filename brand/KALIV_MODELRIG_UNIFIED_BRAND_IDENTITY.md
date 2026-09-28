# Kaliv / ModelRig — Unified Brand Identity

**Status:** Proposed unified brand authority  
**Date:** 2026-09-28  
**Scope:** Website, Android, Quest/VR, Windows desktop, BodyRig UI, and future Rig clients.

## 1. Brand architecture

**Kaliv** is the user-facing identity: the assistant, presence and relationship layer.

**ModelRig** is the platform and orchestration layer behind Kaliv.

**Rig modules** are capabilities within the same family:
- BodyRig — embodiment and physical/digital body state
- VoiceRig — speech and voice
- VisionRig — perception and spatial vision
- Consciousness Core — persistent cognitive state and continuity
- future `*Rig` modules follow the same system

The hierarchy is therefore:

`KALIV`  
`powered by ModelRig`

ModelRig should not compete visually with Kaliv on consumer/client surfaces. In technical surfaces, diagnostics and developer tooling, ModelRig may become the dominant label.

## 2. Core idea

**Ancient symbol. Living machine.**

Kaliv combines a tactile, almost archaeological identity with a modern cognitive system. The visual language should feel like a dark object that has woken up: quiet, precise, premium and slightly mysterious — never generic “AI neon”.

The brand has two complementary energies:

1. **Ember / materiality** — charred black, walnut, bronze and warm gold. Represents identity, body, memory, permanence and the human-facing Kaliv layer.
2. **Signal / cognition** — electric ion blue and cool luminous gradients. Represents thought, live system activity, data flow, perception and the ModelRig/Rig layer.

Blue is not a replacement for the existing bronze system. It is a controlled system-state accent.

## 3. Brand personality

Kaliv should feel:
- intelligent, not performative
- premium, not luxury-fashion
- technical, not sterile
- embodied, not purely digital
- calm, not sleepy
- futuristic, not sci-fi cosplay
- private and local-first, without security-theatre visuals

Avoid generic robot heads, brains, circuit-board backgrounds, rainbow AI gradients and dense cyberpunk decoration.

## 4. Master mark

The **Ankh** is the master brand mark and the only symbol that should represent Kaliv across all platforms.

Rules:
- preserve the distinctive ankh silhouette
- use the clean vector/transparent form for UI
- use the branded/burned material form for hero imagery and marketing
- keep generous clear space around the mark
- do not place the ankh inside another arbitrary logo container unless the platform requires it
- no extra “M” mark for ModelRig on user-facing surfaces

### Mark treatments

**Core / Ember**  
Warm bronze-gold on charred black. Used for resting state, identity, launcher marks, settings, onboarding and branded static surfaces.

**Live / Signal**  
Ankh with a restrained electric-blue inner edge, current trace or energy bloom. Used for active cognition, wake/listening/thinking states and hero moments. It should still read as the same mark.

**Monochrome**  
Single-color silhouette for Android themed icons, Windows monochrome contexts and accessibility/high-contrast surfaces.

## 5. Color system

Existing Kaliv dark tokens remain the base authority.

### Foundation
- Canvas — `#0B0A09`
- Surface — `#171411`
- Elevated — `#211B16`
- Border — `#2A2521`
- Text high — `#F3EFE6`
- Text body — `#EEE6D8`
- Text muted — `#A89D90`

### Ember family
- Ember gold fill — `#B08A3E`
- Ember highlight — `#D4AB52`
- Ember soft — `#E2C06A`
- Ember ink — `#2B1C05`

Use for brand identity, selected identity-level actions, premium framing and persistent Kaliv surfaces.

### Signal family
- Signal 500 — `#48C7FF`
- Signal 400 — `#73D6FF`
- Signal 600 — `#159FDB`
- Signal deep — `#0B5F8C`
- Signal glow — `rgba(72,199,255,0.22)`

Use only for:
- thinking / inference
- listening and voice activity
- vision/perception activity
- model/runtime activity
- live data, streaming and selected technical telemetry
- focus/accent in technical ModelRig surfaces

Do **not** use Signal blue as the default primary button color. Kaliv’s normal action language remains warm.

### Semantic colors
Keep semantic success/warning/danger separate from brand colors. Never use Signal blue to mean “success”.

## 6. Signature gradient

The brand may use one controlled “living system” gradient:

`Ember → Signal`

Example:
`#D4AB52 → #7BCFFF → #48C7FF`

Use it sparingly for:
- website hero art
- startup/wake transition
- thinking visualization
- major launch artwork

Never use it as a full-page background or on every button.

## 7. Typography

### Display / identity
**EB Garamond**
- Kaliv wordmark
- large titles
- emotional/identity moments
- onboarding hero copy

It is the “human / timeless” voice of the system.

### Interface / system
**Inter**
- all controls
- navigation
- chat body
- settings
- technical status
- BodyRig/ModelRig dashboards

It is the “machine / operational” voice of the system.

### Technical data
Use a restrained monospace face only for IDs, hashes, timings, model names, telemetry and logs. It must not become the general UI font.

## 8. Shape language

- 8dp base grid
- rounded but not bubbly
- cards: 15–20dp
- sheets: 22dp
- controls: 14–16dp
- pills only for compact state/filters
- 1dp hairlines
- generous negative space

The visual signature should come from material, typography, light and state — not from excessive geometry.

## 9. Material and depth

Dark surfaces should feel layered rather than flat:
- charred black base
- subtle walnut/brown undertone
- fine warm borders
- very restrained bloom around active Signal elements
- no glassmorphism as a default
- no huge drop shadows

Marketing artwork may use burned wood, blackened metal, brushed bronze and electric energy. Product UI should translate those materials into clean digital tokens, not literal textures behind text.

## 10. Motion language

Motion represents the system becoming alive.

### Rest
Almost still. Slow breathing/pulse is acceptable only for the primary presence indicator.

### Wake
A short ember-to-blue ignition, 350–550 ms.

### Thinking
Low-amplitude flowing energy, never a frantic spinner. Existing 1280 ms thinking rhythm remains a useful base.

### Listening
Responsive blue amplitude / halo tied to audio level.

### Vision
Subtle scan/trace motion rather than a red targeting reticle.

### Success
Return from Signal to Ember/rest state rather than celebratory confetti.

Respect reduced-motion settings everywhere.

## 11. Iconography

Use a single icon family across Android/Windows/Web where technically possible:
- rounded geometry
- 1.75–2px optical stroke at 24px reference
- no filled cartoon icons
- system icons inherit text/muted color
- active technical icons may use Signal
- identity/navigation selection may use Ember

Rig modules should use simple glyphs, not individual logos. The master Ankh remains unique.

## 12. Naming and lockups

### Consumer/client surfaces
**Kaliv**

Optional small secondary label:
**powered by ModelRig**

### Technical/developer surfaces
**ModelRig**
with module context:
`ModelRig / BodyRig`
`ModelRig / VisionRig`

### Product family
Do not produce separate standalone brand identities for every Rig. They are sub-systems in one visual language.

## 13. Platform application

### Android
- adaptive launcher icon: Ankh
- Ember resting launcher mark
- themed monochrome Ankh
- dark-first UI, light mode preserved
- Material 3 behavior with Kaliv tokens
- Signal appears only in live cognition/perception states

### Quest / VR
- same palette, but increase contrast and physical scale
- minimum touch/target sizes should exceed flat-screen equivalents
- avoid tiny gold text in world-space UI
- Signal is especially useful for gaze/focus/listening/live perception
- use emissive blue carefully to avoid visual fatigue
- floating panels remain charred/warm, not blue holograms

### Windows
- denser information hierarchy is allowed
- technical telemetry can use more Signal than consumer clients
- keep content surfaces warm/neutral
- titlebar/sidebar should establish Kaliv/ModelRig identity without looking like a gaming RGB dashboard

### BodyRig UI
BodyRig is visually part of ModelRig, not a separate brand.
- neutral/charred analysis surfaces
- Signal blue = active tracking, inference, projection and live pipeline state
- Ember = identity, performer/body authority, persisted state
- semantic green/amber/red = health only
- avoid using five unrelated colors for pipeline stages
- anatomy/body visualization can use Signal contours on neutral geometry

### Website
The website can use the richest form of the system:
- black/charred atmospheric background
- large Ankh
- human/embodied imagery
- electric Signal energy around cognitive/AI moments
- warm type and bronze framing
- blue should feel like energy inside the object, not a generic tech background

## 14. UI state mapping

| Meaning | Visual language |
| --- | --- |
| Identity / Kaliv | Ember |
| Memory / persistence | Ember |
| Body authority | Ember |
| Thinking / inference | Signal |
| Listening / speech activity | Signal |
| Vision / perception | Signal |
| Runtime / model active | Signal |
| Success | semantic green |
| Warning | semantic amber |
| Error | semantic red |
| Idle / disabled | neutral muted |

This mapping is a core brand rule. It gives the same colors the same meaning in every client.

## 15. Accessibility

- WCAG AA remains mandatory for normal text
- never communicate state by color alone
- glow is decorative and cannot be the only focus indicator
- technical blue text on dark surfaces must use a contrast-safe Signal variant
- preserve light mode rather than treating it as an afterthought
- Quest UI must be validated in-headset, not only in screenshots

## 16. Asset package

Canonical assets should be organized as:

`brand/master/ankh.svg`
`brand/master/ankh-monochrome.svg`
`brand/master/ankh-live.svg`
`brand/wordmark/kaliv.svg`
`brand/lockups/kaliv-powered-by-modelrig.svg`
`brand/platform/android/`
`brand/platform/windows/`
`brand/platform/quest/`
`brand/marketing/`

Raster exports are derivatives. SVG/vector is the authority where possible.

## 17. Design-token authority

The existing `assets/design/kaliv-ui-guide/kaliv-ui-tokens.json` remains the single implementation source for UI tokens.

A future token revision should add a `signal` group rather than replacing `gold`:

```json
"signal": {
  "500": "#48C7FF",
  "400": "#73D6FF",
  "600": "#159FDB",
  "deep": "#0B5F8C",
  "glow": "#3848C7FF"
}
```

The implementation rule is: no platform invents local colors. Intentional divergence must be documented as a platform override.

## 18. Brand test

A new screen belongs to the system if it passes these questions:

1. Would it still look like Kaliv with the logo removed?
2. Is Ember used for identity and Signal used for live cognition?
3. Is the interface calm enough to run for hours?
4. Does the hierarchy work without glow or animation?
5. Is the same semantic state represented the same way on Android, Quest, Windows and BodyRig?
6. Does it feel like a capable instrument rather than an AI-themed demo?

If not, it is not finished.

## 19. One-line identity

**Kaliv is a living local intelligence: grounded in material, illuminated by cognition.**
