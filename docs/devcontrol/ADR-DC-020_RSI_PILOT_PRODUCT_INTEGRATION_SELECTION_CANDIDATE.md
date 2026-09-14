# ADR-DC-020 — Fail-closed product integration selection candidate before human recording

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** false

## Context

ADR-DC-019 fastlåser hvilke bindinger og produktdesignbeslutninger en senere DC-L16 integration selection skal indeholde. Den må ikke udvide den signerede human pilot decision eller ADR-DC-016 single-trial scope, og kendte product surfaces skal bindes til ADR-DC-018 exact-source inventory.

Det næste sikre kodeled er at kunne validere en konkret integrationskandidat uden at gøre selve valideringen til menneskelig selection-authority.

## Decision

Indfør en inert `PilotIntegrationSelectionCandidateProof` og en fail-closed validator.

Validatoren accepterer kun:

- exact `PilotTrialScopeProof` med positiv human GO og fortsat inert pilot-state;
- exact raw bytes af ADR-DC-018 inventory med pinned Git blob-identitet;
- exact raw bytes af ADR-DC-019 requirements-manifest med pinned Git blob-identitet;
- en konkret, komplet designkandidat for feature flag, product route, runtime observer, task registry, workspace policy, review/authorization roles, kill/revoke/cleanup og local-commit policy.

## Exact source binding

V1 binder:

- ADR-DC-018 inventory source head `30be16b320acd6655c07ab1476cceaead547e3e3`;
- inventory Git blob `babad0dfc82ad359ee053817bae2674a8f8b38a0`;
- ADR-DC-019 requirements Git blob `36253b5a0ee8807f51eaeb8c0cf10276e0bc7a63`;
- de tre kendte source kandidater og deres exact path/blob-identiteter.

Raw evidence ændres med blot én byte, fejler valideringen.

## Human scope binding

`operator_surface` må ikke komme fra validatoren. Den arves fra exact ADR-DC-016 scope og skal samtidig findes i det pinned inventory.

Hvis surface ikke findes i inventoryet, fejler V1 lukket med krav om frisk exact-source inventory. Validatoren må ikke auto-mappe eller gætte en ny surface.

`selected_pilot_task_id`, workspace digest og local-commit authority forbliver bundet i trial scope. `allow-local-only` accepteres kun når scope allerede tillader lokale commits; ellers kræves `forbid`.

## Product design candidate

En valideret kandidat skal angive alle ADR-DC-019 designfelter. Feature flag skal være et særskilt `KALIV_*` flag og må ikke genbruge Agent 3/Agent 4 authority flags. Product route skal være eksplicit `/api/v1/...` og DevControl-scoped.

Disse værdier er kun en kandidat. De bliver ikke skrevet til produktkode i denne slice.

## Deserialization boundary

Proof deserialization revaliderer:

- candidate ID == signed operator surface;
- candidate kind/path/blob == pinned inventory identity;
- inventory/requirements evidence identities;
- local-commit narrowing;
- alle non-authority booleans.

En manipuleret proof kan derfor ikke skifte source blob eller surface efter validering.

## Non-authority

Et successful proof må kun sætte:

- `human_pilot_go_verified=true`;
- `pilot_scope_verified=true`;
- `source_inventory_verified=true`;
- `selection_requirements_verified=true`;
- `design_candidate_validated=true`.

Følgende forbliver obligatorisk false:

- `human_selection_recorded`;
- `integration_ready`;
- `preflight_observed`;
- `preflight_satisfied`;
- `pilot_start_authorized`;
- `product_pilot_started`;
- remote write / push / PR mutation / merge / release / deploy;
- production activation.

Authority er kun `dc-l16-product-integration-selection-candidate-only`.

## Product isolation

Denne slice ændrer ingen filer under `backend/`, `worker/`, `desktop/` eller `android/`. Den tilføjer ingen feature flag reader, route, runtime observer, registry, executor, credentials eller network transport.

## Consequences

Efter ADR-DC-020 kan ModelRig deterministisk afvise stale, ukendte eller scope-bredere product-integration forslag uden at foregive et menneskeligt valg.

Det næste authority-led skal separat registrere eller signere et menneskeligt valg af én allerede valideret candidate proof, før runtime-preflight eller produktintegration kan begynde.
