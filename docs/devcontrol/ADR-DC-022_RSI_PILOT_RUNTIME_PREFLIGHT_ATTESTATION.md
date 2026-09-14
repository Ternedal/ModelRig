# ADR-DC-022 — Host-attested runtime preflight evidence without pilot-start authority

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Kontekst

ADR-DC-017 fastlåser de checks, en senere DC-L16 runtime-preflight skal bevise.
ADR-DC-020 validerer én exact product-integration candidate, og ADR-DC-021 kan
verificere et separat menneskeligt signeret valg af netop den candidate.

Det næste hul i authority-kæden er selve runtime-preflight-evidensen. Det må ikke
være muligt for en almindelig caller at indsende en samling `true`-booleans og
få dem ophøjet til preflight-proof. Samtidig skal en faktisk fejlet preflight
kunne bevares som verificeret audit-evidence uden at blive forvekslet med en
satisfied preflight.

## Beslutning

Der indføres et separat ADR-DC-022 observation/proof-lag.

### 1. Exact upstream binding

Et runtime-preflight observation-artifact skal være exact bundet til:

- ét verificeret ADR-DC-021 `PilotIntegrationHumanSelectionProof`;
- ét inert ADR-DC-017 `PilotPreflightRequirements`;
- selection-proofets exact ADR-DC-020 candidate SHA;
- exact trial-scope SHA, repository, base/main SHA, trial, operator surface,
  selected task, workspace digest og local-commit policy;
- exact candidate blob, feature flag, product route, runtime observer, task
  registry, workspace policy og kill/revoke/cleanup design-id.

Requirements og human selection skal desuden matche hinanden på den scope, som
begge arver fra ADR-DC-016. Stale eller rebound requirements fejler lukket.

### 2. Observation er ikke proof

Observation-artifactet indeholder de tolv ADR-DC-017 runtime checks:

- feature flag off observed;
- pilot runtime verified;
- native Windows isolation verified;
- trusted Git closure verified;
- kill switch prearmed;
- restart/revoke prearmed;
- network write block verified;
- credentials absent verified;
- unattended cadence forbidden verified;
- off-state import block verified;
- exact source binding verified;
- receipt binding verified.

Observationen binder også en exact runtime-receipt SHA-256, observer actor,
observer host og canonical UTC observation time.

Selve observationen er kun en signable claim. Derfor er
`preflight_observed=false`, `preflight_satisfied=false` og alle downstream
activation-felter false i observation-artifactet, uanset check-værdierne.

### 3. Separat host-attesteret Ed25519 authority

En observation kan kun blive til proof gennem en detached Ed25519-signatur fra
ADR-DC-022's eget issuer-system:

`kaliv-rsi-dc-l16-pilot-runtime-preflight-observer-v1`

Production-facaden accepterer ikke caller-valgt verifier. Den resolver kun en
separat verification-only public-key keyring fra den canonical host-controlled
DevControl authority-path og kræver elevated host operator, efter samme
trust-pattern som ADR-DC-015 og ADR-DC-021.

Private signing keys, signer og credential transport er ikke del af repo eller
runtime.

### 4. Verified failure er gyldig evidence

Et gyldigt signeret observation-artifact giver altid:

- `preflight_observed=true`.

`preflight_satisfied=true` må kun være sandt, hvis **alle tolv** checks i det
signerede artifact er exact `true`.

Hvis blot én check er false, er proofet stadig gyldigt audit-evidence med:

- `preflight_observed=true`;
- `preflight_satisfied=false`.

Deserialisering revaliderer denne relation og afviser et proof, hvor
`preflight_satisfied` ikke svarer til de signerede check-værdier.

### 5. Ingen pilot-start eller integration authority

Selv et fully satisfied ADR-DC-022 proof holder følgende false:

- `integration_ready`;
- `pilot_start_authorized`;
- `product_pilot_started`;
- `remote_write_authorized`;
- `push_authorized`;
- `pr_mutation_authorized`;
- `merge_authorized`;
- `release_authorized`;
- `deploy_authorized`;
- `production_activation_authorized`.

Authority-label er kun:

`verified-dc-l16-pilot-runtime-preflight-only`

Et senere, separat authority-step skal være nødvendigt for enhver pilot-start.

## Ikke en del af denne ADR

Denne slice:

- implementerer ingen faktisk Desktop/Android/backend product integration;
- læser ikke selv feature flags fra produktet;
- starter ingen runtime observer eller executor;
- registrerer ingen DevControl commands eller task registry entries;
- opretter ingen faktisk signed preflight observation;
- udfører ingen local commit, remote write, push, PR mutation, merge, release,
  deploy eller production activation.

## Falsificerbare kontrakter

ADR-DC-022 skal mindst afvise:

1. caller-selected production verifier;
2. forkert issuer-system eller observer actor;
3. stale/rebound ADR-DC-017 requirements;
4. observation, der ikke matcher human-selected candidate;
5. ændret feature flag/design/source binding uden ny signatur;
6. ændret runtime receipt uden ny signatur;
7. proof med `preflight_satisfied=true`, hvis en signeret check er false;
8. proof med `preflight_satisfied=false`, hvis alle signerede checks er true;
9. enhver downstream authority escalation i replay/deserialisering.

Kontrakten skal fortsat køre gennem den eksisterende Stage-B support-kæde, så
den genererede test-inventory ikke ændres alene på grund af ADR-DC-022.
