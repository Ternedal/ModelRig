# ADR-DC-023 — Human-signed one-shot pilot-start authorization without consuming or starting the pilot

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Kontekst

ADR-DC-022 kan verificere et host-attesteret runtime-preflight og kan bevise, at
alle ADR-DC-017 checks er tilfredsstillet. Det proof er bevidst ikke en tilladelse
til at starte piloten: `pilot_start_authorized=false` og
`product_pilot_started=false`.

Den næste authority-grænse skal derfor være et separat menneskeligt valg, bundet
til præcis det preflight-proof der blev observeret. Et host-observer-proof må ikke
kunne ophøje sig selv til start-authority, og en caller må ikke kunne genbinde
human approval til en anden candidate, receipt, workspace eller trial.

## Beslutning

Der indføres to nye artifacts:

1. `PilotStartAuthorization` — canonical bytes til ekstern human signering.
2. `PilotStartAuthorizationProof` — resultatet af verificeret detached Ed25519
   human authority.

Claimen indlejrer hele exact ADR-DC-022 `PilotRuntimePreflightProof` og binder
separat dets digest samt:

- observation SHA-256;
- ADR-DC-021 selection-proof SHA-256;
- candidate-proof SHA-256;
- ADR-DC-017 requirements SHA-256;
- ADR-DC-016 trial-scope SHA-256;
- runtime-receipt SHA-256;
- repository, base/main SHA, trial, operator surface, selected task og workspace;
- local-commit scope;
- start-authorizer actor;
- authorization time + expiry;
- separat start nonce SHA-256;
- explicit intent `authorize-one-local-pilot-start`.

## Preflight er en hård prerequisite

Kun et exact ADR-DC-022 proof med:

- `preflight_observed=true`;
- `preflight_satisfied=true`;
- `pilot_start_authorized=false`;
- `product_pilot_started=false`;
- alle remote/production-authorities false

kan anvendes.

Et gyldigt signeret, men fejlet runtime-preflight kan fortsat bevares som audit
evidence under ADR-DC-022, men kan ikke blive input til ADR-DC-023.

## Human authority

Start-authorizeren skal være den samme human actor, der signerede det exact
ADR-DC-021 candidate-valg. ADR-DC-023 tillader ikke, at host-observeren fra
ADR-DC-022 bliver start-authority.

Det er bevidst fail-closed, indtil en senere ADR eventuelt etablerer et andet
role/delegation-system med selvstændig authority evidence.

## Kort validity window

Authorizationen skal have canonical UTC-second timestamps og må være gyldig i
højst **15 minutter**. Den må ikke være signeret før preflight-proofets
verification-time.

Verification skal ske inden for authorization-vinduet. Udløbet authority kan
ikke genoplives ved deserialisering eller ved at ændre verifier-clock gennem den
offentlige production-facade.

## One-shot intent uden consumption

Et verified proof kan sætte:

- `pilot_start_authorized=true`;
- `one_shot_start_required=true`.

Men det skal samtidig bevare:

- `start_consumed=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `remote_write_authorized=false`;
- `push_authorized=false`;
- `pr_mutation_authorized=false`;
- `merge_authorized=false`;
- `release_authorized=false`;
- `deploy_authorized=false`;
- `production_activation_authorized=false`.

ADR-DC-023 er dermed authorization, ikke replay-safe consumption og ikke pilot
execution. En senere separat gate skal atomisk consume start-authority og bevise,
at den exact start nonce ikke allerede er brugt, før product pilot kan starte.

## Trust boundary

Detached Ed25519 verification bruger et separat issuer-system:

`kaliv-rsi-dc-l16-pilot-start-human-authority-v1`

Production-facaden accepterer ikke caller-valgt verifier. Den resolver kun en
host-controlled verification-only public-key keyring fra den canonical
DevControl authority-location og kræver elevated host operator.

Repo/runtime indeholder ingen signing/private key.

## Fail-closed invariants

Verification skal afvise mindst:

- preflight med `preflight_satisfied=false`;
- nested/rebound preflight proof;
- anden human actor end ADR-DC-021 selection maker;
- host-observer som start-authorizer;
- forkert issuer-domain eller signer actor;
- signature timestamp der ikke matcher authorization timestamp;
- verification uden for validity window;
- validity window over 15 minutter;
- placeholder start nonce;
- nonce/candidate/receipt/workspace/trial rebinding uden ny human signatur;
- proof replay der forsøger at sætte `start_consumed`, `product_pilot_started`
  eller remote/production authority.

## Ikke i denne slice

Denne ADR:

- opretter ikke et faktisk human-signeret start artifact;
- consumer ikke start-authority;
- implementerer ikke replay-ledger;
- ændrer ingen product integration;
- registrerer ingen commands;
- eksekverer ingen pilot-task;
- laver ingen local pilot commit;
- udfører ingen remote write/push/PR/merge/release/deploy;
- aktiverer intet i production.

`production_activation=false`.
