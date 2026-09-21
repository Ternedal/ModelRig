# ADR-DC-022 — Exact-bound runtime-preflight observation packet without preflight authority

**Dato:** 14/09-2026  
**Status:** Foreslået til beslutning

## Beslutning

DC-L16 får et separat, ikke-autoriserende observation-packet mellem den
menneskeligt signerede product-integration selection i ADR-DC-021 og en senere
host-controlled runtime-preflight verifier.

Packetet må kun samle og digest-binde evidence for de tolv krav, som allerede er
fastlåst i ADR-DC-017. Det må ikke selv observere hosten, verificere evidensens
sandhed, erklære preflight satisfied eller starte piloten.

## Exact input binding

Et packet kræver præcis:

1. et verificeret `PilotIntegrationHumanSelectionProof` fra ADR-DC-021 med
   authority `verified-human-dc-l16-product-integration-selection-only`; og
2. et `PilotPreflightRequirements` fra ADR-DC-017 med authority
   `dc-l16-pilot-preflight-requirements-only`.

De to inputs skal matche på:

- `trial_scope_sha256`;
- `decision_proof_sha256`;
- repository;
- base SHA og requested-main SHA;
- trial ID;
- operator surface;
- selected pilot task;
- workspace-root digest;
- local-commit choice/policy.

Et packet kan derfor ikke flytte et signeret integration-valg til et andet
trial, en anden workspace-root, en anden operator surface eller en bredere
local-commit policy.

## De tolv evidence slots

Packetet kræver én SHA-256 evidence-reference for hvert ADR-DC-017 krav:

1. feature flag observeret off;
2. pilot runtime boundary;
3. native Windows isolation;
4. trusted-Git closure;
5. kill switch prearmed;
6. restart/revoke prearmed;
7. network write blocked;
8. credentials absent;
9. unattended cadence forbidden;
10. off-state product import block;
11. exact source/base/head binding;
12. receipt binding.

`observation_set_complete=true` betyder **kun**, at alle tolv digest-slots er
udfyldt og exact-bound. Det betyder ikke, at de refererede bytes er verificeret,
at observationerne er sande eller at preflight er bestået.

## Authority boundary

ADR-DC-022 tvinger følgende værdier:

- `evidence_verified=false`;
- `integration_ready=false`;
- `preflight_observed=false`;
- `preflight_satisfied=false`;
- `pilot_start_authorized=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy = `false`;
- `production_activation_authorized=false`.

En senere ADR må definere en host-controlled verifier, som faktisk åbner og
validerer de refererede evidence-artifacts og kan afgøre, om
`preflight_observed` overhovedet må blive true. Selv den senere verification må
ikke implicit udstede pilot-start authority.

## Runtime-egenskaber

Implementeringen i denne ADR er ren data/canonicalization:

- ingen filesystem-, environment-, subprocess-, socket- eller network-I/O;
- ingen produktkodeændringer;
- ingen feature-flag læsning;
- ingen command registration;
- ingen `kaliv_dev_control` root-export;
- ingen task execution;
- ingen credentials;
- ingen signing/private keys.

Normal ModelRig command catalog forbliver tom.

## Hvorfor ikke kalde packetet et preflight proof?

Fordi SHA-256 references alene ikke beviser, hvem der producerede evidence,
hvordan host-state blev observeret, om bytes er friske eller om observationen
har TOCTOU-huller. At kalde dette `preflight_observed=true` ville derfor være en
falsk authority-eskalation.

ADR-DC-022 lukker kun chain-of-custody-kløften mellem det signerede valg og de
kommende runtime-evidence-artifacts.

## Ikke besluttet / ikke autoriseret

Denne ADR er ikke:

- Anders' konkrete product-integration selection artifact;
- en faktisk runtime observation;
- en host-verification;
- preflight satisfaction;
- pilot GO eller pilot start;
- executor/task-registry activation;
- local commit authority;
- GitHub mutation/publication;
- merge/release/deploy;
- production activation.
