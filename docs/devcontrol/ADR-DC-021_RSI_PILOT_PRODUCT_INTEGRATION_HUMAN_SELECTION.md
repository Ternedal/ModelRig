# ADR-DC-021 — Human-signed exact product-integration selection before runtime preflight

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Context

ADR-DC-020 kan validere en komplet product-integration candidate mod exact
ADR-DC-016 trial scope, ADR-DC-018 source inventory og ADR-DC-019 selection
requirements. Det proof er bevidst inert: det er ikke et menneskeligt valg.

Næste nødvendige grænse er derfor ikke produktintegration, men en verificerbar
mekanisme til at registrere, at et menneske eksplicit har valgt **præcis ét
allerede valideret ADR-DC-020 proof**.

## Decision

ADR-DC-021 indfører en separat human-selection claim og et verificeret proof.

Claimen:

- indeholder hele det exact `PilotIntegrationSelectionCandidateProof`;
- binder samtidig candidate-proofets SHA-256;
- har et eksplicit `selection_id`, `selection_maker_actor_id` og canonical UTC
  `selected_at_utc`;
- har kun intent `select-exact-candidate`;
- er default-deny og sætter ikke `human_selection_recorded=true` før en
  kryptografisk verificeret signatur foreligger.

Den menneskelige signatur er en detached Ed25519 authority-signatur over
claimens canonical JSON bytes. Signaturen skal have samme actor som
`selection_maker_actor_id`, samme tidspunkt som `selected_at_utc` og issuer
system:

`kaliv-rsi-dc-l16-product-integration-selection-authority-v1`

Production-verifikation accepterer ikke en caller-valgt verifier. Den offentlige
facade installerer en host-pinned verifier fra en separat, host-kontrolleret
public-key keyring og kræver elevated host operator. Private signing keys må ikke
ligge i repository, worker, DevControl runtime eller keyring.

## Replay and rebinding boundary

Selection claim og proof er selvindeholdte: ADR-DC-020 proofet ligger i de
signerede bytes, ikke kun som et løst hash-referencefelt.

Ved deserialisering revalideres det indlejrede ADR-DC-020 proof gennem dets egen
constructor boundary, og `candidate_proof_sha256` skal matche exact canonical
proof bytes. Et andet candidate proof, ændrede designværdier eller ændrede
source bindings kræver derfor en ny menneskelig signatur.

## Verified authority

Et korrekt verificeret ADR-DC-021 proof må sætte:

- `human_selection_recorded=true`;
- `candidate_selection_verified=true`.

Det må **ikke** sætte:

- `integration_ready`;
- `preflight_observed`;
- `preflight_satisfied`;
- `pilot_start_authorized`;
- `product_pilot_started`;
- remote write, push eller PR mutation;
- merge, release eller deploy;
- production activation.

Proof-authority er kun:

`verified-human-dc-l16-product-integration-selection-only`

## Product boundary

Denne slice:

- ændrer ingen `backend/`, `worker/`, `desktop/` eller `android/` produktkode;
- registrerer ingen command eller task executor;
- opretter ingen product route eller feature flag i runtime;
- observerer ikke runtime/preflight;
- starter ikke pilot;
- udfører ingen local commit som del af piloten;
- giver ingen Git/GitHub/publication/release/deploy authority.

At mekanismen kan verificere en fremtidig signeret selection betyder ikke, at
Anders har foretaget selectionen i denne PR. Der oprettes ingen konkret signed
selection artifact her.

## Consequence

Et senere runtime-preflight-led kan kræve et exact ADR-DC-021 proof og dermed
skelne kryptografisk mellem:

1. en model-/kodevalideret kandidat; og
2. et separat menneskeligt valg af netop den kandidat.

Først et senere ADR må afgøre, hvordan et verificeret selection-proof bindes til
runtime observation og preflight. ADR-DC-021 giver ikke den authority.
