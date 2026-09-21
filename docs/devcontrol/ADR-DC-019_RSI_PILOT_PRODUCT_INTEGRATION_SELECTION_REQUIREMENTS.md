# ADR-DC-019 — Human-bound product integration selection requirements before DC-L16 runtime preflight

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** false

## Context

ADR-DC-018 kortlægger eksisterende produktkandidater med exact source-identitet, men vælger bevidst ingen operator surface, feature flag, route, observer eller task registry. ADR-DC-015 og ADR-DC-016 fastlægger samtidig, at et fremtidigt positivt human pilot decision proof og dets single-trial projection allerede ejer den menneskelige authority for operator surface, task, workspace og local-commit scope.

Det næste sikre led er derfor ikke at vælge noget automatisk. Det er at fastlåse hvilke bindinger og designbeslutninger en senere product-integration selection skal opfylde, så produktkode ikke kan få en bredere authority end den signerede human decision chain.

## Decision

Indfør et inert requirements-manifest for en senere separat product-integration selection.

Manifestet binder exact ADR-DC-018 inventory ved source head, path, Git blob-SHA og de tre candidate IDs. Det registrerer kun krav; det indeholder ingen valgt surface og ingen runtime-observation.

## Human authority binding

En senere selection må kun accepteres, hvis den kan bindes til:

- et verificeret ADR-DC-015 human pilot decision proof;
- et positivt `GO` eller `GO WITH CONDITIONS`;
- exact ADR-DC-016 single-trial scope;
- exact `operator_surface` fra den signerede scope;
- exact single-trial task;
- exact workspace-root digest;
- en local-commit policy, der aldrig er bredere end den signerede scope.

Hvis den signerede operator surface matcher en kendt ADR-DC-018 kandidat, skal selectionen binde exact inventory-kandidat og dens source identity. Hvis den ikke matcher inventoryet, kræves frisk exact-source inventory evidence før selection; ukendt surface må ikke implicit godkendes.

## Product design decisions required before implementation

Følgende skal være eksplicit besluttet i en senere separat selection-artifact, før produktintegration kan implementeres:

1. operator surface;
2. feature-flag navn;
3. product route;
4. runtime observer;
5. task registry;
6. workspace policy;
7. review/authorization roles;
8. kill/revoke/cleanup flow;
9. local-commit policy.

Requirements-manifestet udfylder ingen af disse værdier.

## Non-selection boundary

Et gyldigt manifest skal holde alle selection-state felter falske, inklusive `human_selection_recorded=false`.

Det må ikke udlede en surface fra eksisterende produktkode, det må ikke opfinde et feature flag, og det må ikke genbruge eksisterende Agent 3/Agent 4/GitHub-connector flags som DevControl authority.

## Non-authority

Et gyldigt manifest skal holde følgende falske:

- `integration_ready`;
- `preflight_observed`;
- `preflight_satisfied`;
- `pilot_start_authorized`;
- `product_pilot_started`;
- remote write / push / PR mutation / merge / release / deploy;
- production activation.

Authority er kun `dc-l16-product-integration-selection-requirements-only`.

Repositoryets normale `modelrig_command_catalog()` skal fortsat være tomt.

## Product isolation

Denne slice tilføjer ingen produktimport af `kaliv_dev_control`, ingen route, intet feature flag, ingen runtime observer, ingen command registration, ingen executor og ingen credential/network transport.

Den ændrer ikke ADR-DC-015/016 authority-semantik og kan ikke stå i stedet for et menneskeligt GO eller en senere human-bound integration selection.

## Consequences

Efter ADR-DC-019 er den næste kodebare grænse en separat selection/proof-model, der kun må materialisere de krævede produktdesignvalg, når de er exact bundet til en verificeret positiv human pilot decision + single-trial scope og den relevante exact-source inventory evidence.

Før den selection findes, er product integration fortsat dormant og default-deny.
