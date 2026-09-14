# ADR-DC-022 — Bind verified human integration selection to exact runtime-preflight requirements

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Context

ADR-DC-017 fastlåser de egenskaber, som en senere DC-L16 runtime-preflight skal
bevise, men indeholder ingen product-integration selection. ADR-DC-021 kan
verificere et separat menneskeligt valg af ét exact ADR-DC-020 candidate proof,
men observerer bevidst ikke runtime.

Før en faktisk host-observer må køre, skal de to evidenslinjer bindes sammen
fail-closed. Ellers kan et gyldigt preflight-requirements manifest i princippet
kombineres med et menneskeligt valg, der tilhører en anden trial, surface, task,
workspace eller local-commit policy.

## Decision

ADR-DC-022 indfører et inert `PilotRuntimePreflightBindingPlan`.

Planen indlejrer hele:

- exact `PilotPreflightRequirements` fra ADR-DC-017; og
- exact `PilotIntegrationHumanSelectionProof` fra ADR-DC-021.

Begge objekter replay-valideres gennem deres egne constructor-boundaries, og
planen binder samtidig SHA-256 for begge canonical JSON-artifacts.

## Exact cross-binding

ADR-017 requirements og den ADR-020 candidate, som ligger inde i det signerede
ADR-021 proof, skal være identiske på:

- `trial_scope_sha256`;
- `decision_proof_sha256`;
- repository;
- base SHA;
- requested-main SHA;
- trial ID;
- operator surface;
- selected pilot task ID;
- workspace-root digest;
- `local_commits_allowed`.

Candidate `local_commit_policy` skal desuden være præcis `forbid`, når scope
forbyder lokale commits, og `allow-local-only`, når scope tillader dem.

Planen kopierer feature flag, product route, runtime observer, task registry,
workspace policy, review/authorization roles og kill/revoke/cleanup direkte fra
den menneskeligt valgte exact candidate. Ved deserialisering skal alle kopierede
værdier stadig matche det indlejrede proof; rebinding fejler derfor lukket.

## Verified state

Et gyldigt ADR-DC-022 plan må kun sætte:

- `preflight_requirements_verified=true`;
- `human_selection_recorded=true`;
- `candidate_selection_verified=true`;
- `preflight_binding_verified=true`.

Det betyder alene, at exact requirements og exact human selection nu tilhører
samme trial og kan gives videre til et senere runtime-observation-led.

Følgende forbliver obligatorisk `false`:

- `integration_ready`;
- `preflight_observed`;
- `preflight_satisfied`;
- `pilot_start_authorized`;
- `product_pilot_started`;
- remote write;
- push og PR mutation;
- merge, release og deploy;
- production activation.

Authority er kun:

`dc-l16-runtime-preflight-binding-plan-only`

## Runtime boundary

Denne slice:

- læser ikke feature flags;
- observerer ikke host/runtime/process/netværk/credentials;
- registrerer ingen task eller command;
- kalder ingen executor;
- udfører ingen local commit;
- ændrer ingen `backend/`, `worker/`, `desktop/` eller `android/` produktkode;
- starter ikke DC-L16;
- giver ingen Git/GitHub/publication/release/deploy authority.

Der oprettes heller ikke et konkret Anders-signeret selection artifact. Tests må
konstruere deterministisk test-authority, men det er ikke product/pilot authority.

## Consequence

Et senere ADR kan definere den første faktiske runtime-observation. Det led skal
kræve et exact ADR-DC-022 plan, må ikke acceptere løse caller-supplied design-
værdier og skal bevise ADR-DC-017 kravene mod den human-selectede ADR-DC-020
candidate.

ADR-DC-022 selv observerer intet og kan ikke gøre `preflight_satisfied=true`.
