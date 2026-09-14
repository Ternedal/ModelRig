# ADR-DC-018 — Exact-source product integration inventory before DC-L16 surface selection

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** false

## Context

ADR-DC-017 fastlåser hvilke runtime-egenskaber en senere DC-L16 preflight skal bevise, men ModelRig har endnu ingen autoriseret KalivDev-produktintegration. Issue #423 kræver desuden en separat menneskelig beslutning om operator surface, task-typer, workspace/repository-scope, review/authorization-roller, kill/revoke/cleanup og local-commit policy.

Repositoryet har allerede rigtige produktflader og sikre opt-in mønstre. De må kortlægges uden at blive forvekslet med et valg eller en aktivering.

## Decision

Indfør et statisk exact-source inventory, der kun registrerer eksisterende kandidatflader og deres Git blob-identiteter.

Inventoryet binder tre verificerede eksisterende produktkilder:

1. `desktop.control-center` → Desktop Control Center UI.
2. `android.control-center` → Android Control Center UI.
3. `backend.local-api-host-pattern` → backendens eksisterende route-host og default-off pilotmønstre.

Disse er **kandidater**, ikke valgte surfaces. `selected=false` er obligatorisk for alle entries.

## Verified facts

Inventory-kontrakten må verificere følgende imod exact tracked bytes:

- Desktop Control Center eksisterer og bruger manuel refresh uden automatisk polling.
- Android Control Center eksisterer og bruger manuel refresh uden automatisk polling.
- Backend har Bearer-beskyttede Control Center routes og eksisterende default-off eksperimentelle route-mønstre.
- De tre produktkilder importerer ikke `kaliv_dev_control`.
- Backend-kilden indeholder ikke en KalivDev/DevControl produkt-route eller et `KALIV_DEVCONTROL`/`KALIV_DEV` flag.
- Det normale `modelrig_command_catalog()` er fortsat tomt.

## Non-selection boundary

Inventoryet må ikke vælge eller udlede:

- operator surface;
- feature flag-navn;
- product route;
- runtime observer;
- task registry;
- local-commit policy.

Eksisterende Agent 3, Agent 4, scheduler og GitHub-connector flags er arkitekturpræcedens, ikke authority til at genbruge dem for DevControl.

## Non-authority

Et gyldigt inventory skal holde følgende falske:

- `integration_ready`
- `preflight_observed`
- `preflight_satisfied`
- `pilot_start_authorized`
- `product_pilot_started`
- remote write / push / PR mutation / merge / release / deploy
- production activation.

Authority er kun `dc-l16-product-integration-inventory-only`.

## Product isolation

Denne slice ændrer ingen filer under `backend/`, `worker/`, `desktop/` eller `android/`. Den tilføjer ingen produktimport af DevControl, ingen route, intet feature flag, ingen command registration, ingen observer og ingen executor.

## Consequences

Efter ADR-DC-018 kan en senere menneskelig beslutning vælge én af de dokumenterede surfaces eller en anden eksplicit surface med ny evidens. Inventoryet selv kan ikke bruges som GO, runtime-preflight eller pilot-start authority.

En senere implementation, der faktisk forbinder produktkode til DevControl, kræver separat review og må først ske inden for det menneskeligt valgte scope under #423.
