# Unified Kaliv / ModelRig Brand — Implementation Plan

**Branch:** `brand/unified-identity-20260928`  
**Brand authority:** `brand/KALIV_MODELRIG_UNIFIED_BRAND_IDENTITY.md`  
**Token authority:** `assets/design/kaliv-ui-guide/kaliv-ui-tokens.json`

## Goal

Implement the unified Ember / Signal identity across Android, Windows, Quest and BodyRig without allowing platform-local color drift.

## Rules

- Ember / gold = Kaliv identity, persistent state, human-facing primary actions.
- Signal / electric blue = live cognition, inference, listening, perception, model/runtime activity.
- Green / amber / red remain semantic health states.
- The Ankh stays the master identity mark.
- Existing UI behavior and API contracts are preserved while the visual layer changes.

## Phase 1 — Shared design system
- [x] Add Signal token family to the canonical token JSON.
- [x] Expose CSS Signal variables.
- [x] Extend the Kotlin token generator.
- [x] Regenerate Android and desktop token sources.
- [x] Expose explicit cognition roles in Android and desktop themes.
- [x] Add brand-state contract test.

## Phase 2 — Android
- [x] Voice/listening activity uses Signal blue.
- [x] Runtime/loading indicators use Signal blue.
- [x] Semantic health uses semantic colors, not brand gold.
- [x] Keep primary user actions Ember/gold.
- [x] Verify no local hard-coded Signal literals.

## Phase 3 — Windows / ModelRig desktop
- [x] Live model/runtime/performance visualizations use Signal.
- [x] Keep approvals/destructive actions semantic and identity controls Ember.
- [x] Active technical telemetry uses Signal consistently.
- [x] Remove remaining hand-authored brand-state colors where touched.

## Phase 4 — Quest / VR
- [x] Replace local palette ownership with named Ember/Signal roles.
- [x] Apply Signal to live model/listening/perception state.
- [x] Keep primary interaction actions Ember.
- [x] Preserve world-space contrast and readable target sizes.

## Phase 5 — BodyRig
- [x] Locate current UI authority in BodyRig repo.
- [x] Add shared Ember/Signal theme contract.
- [x] Signal = tracking/inference/live projection.
- [x] Ember = identity/body authority/persisted performer state.
- [x] Semantic colors = health only.

## Phase 6 — Gates and documentation
- [x] CI gate verifies required Signal tokens and bindings.
- [x] CI gate rejects duplicated hard-coded canonical Signal hex values.
- [x] Update design handoff/readme.
- [ ] Run available compile/workflow tests.
- [x] Open implementation PR and record any unverified visual checks.


## Verification state

- BodyRig PR #1308: repository CI, CodeQL, Windows regression and LOC checks green on the brand branch.
- ModelRig PR #1914: mergeable; current head must pass Android compile, desktop compile, core CI, accessibility, diagnostics and CodeQL before the workflow/compile item is closed.
- Physical visual review remains separate from compile/CI qualification, especially for Quest in-headset readability and the final pixel-level desktop/Android polish.
