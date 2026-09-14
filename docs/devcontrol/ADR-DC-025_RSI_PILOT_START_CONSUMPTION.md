# ADR-DC-025 — Host-local one-shot consumption of one verified DC-L16 pilot-start authorization

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Kontekst

ADR-DC-024 kan verificere en kortlivet, menneskeligt signeret authorization til
præcis én fremtidig lokal pilot-start. Det proof er stadig bevidst uforbrugt:
`one_shot_start_required=true`, `start_consumed=false` og
`product_pilot_started=false`.

Et verificeret start-proof må ikke kunne genbruges to gange, og et crash midt i
forbruget må ikke gøre samme nonce brugbar igen. Samtidig må selve consume-leddet
ikke blive en skjult executor eller udvide authority til local commits, remote
write, merge, release, deploy eller production activation.

## Beslutning

ADR-DC-025 indfører en separat, host-local replay-boundary, som kan **forbruge**
én exact ADR-DC-024 authorization og skrive et crash-durable receipt. Consumption
er admission-token accounting; det er ikke pilot execution.

### 1. Kun frisk verificeret ADR-DC-024 authority må forbruges

Private deterministic tests må arbejde med et exact `PilotStartAuthorizationProof`.
Production må derimod ikke stole på et serialiseret proof alene. Public consume
skal modtage proofet samt de detached ADR-DC-024 og ADR-DC-023 signaturer og før
ledger-mutation:

1. re-verificere ADR-DC-024 gennem den host-pinnede production facade;
2. dermed også kræve frisk host-side ADR-DC-023 provenance-verifikation;
3. kræve at den detached ADR-DC-024-signatur matcher proofets signature SHA;
4. kræve at fresh verification reproducerer samme authorization, signer,
   preflight/packet/selection/candidate/requirements/trial binding og alle
   authority-semantikker.

Fresh `verified_at_utc` må ændre sig; den signerede authorization og dens scope må
ikke.

### 2. Consumption binder hele start-chainen

Receiptet indlejrer det exact fresh ADR-DC-024 proof og binder separat:

- authorization-proof SHA-256;
- authorization SHA-256 og detached-signatur SHA-256;
- preflight-proof, attestation og packet SHA-256;
- selection-, candidate-, requirements- og trial-scope SHA-256;
- start nonce SHA-256;
- repository/base/requested-main/trial/operator surface/task/workspace;
- signed local-commit scope;
- canonical ledger ID og consume time.

Rebinding af nonce, scope eller nested proof kræver ny upstream authority og kan
ikke ske via receipt-deserialisering.

### 3. Host-local replay-state er fixed og administrator-kontrolleret

Production resolver selv en pre-provisioned ledger:

- POSIX: `/var/lib/modelrig/devcontrol/rsi-pilot-start-consumption-ledger-v1`
- Windows: `C:\Program Files\ModelRig\DevControl\state\rsi-pilot-start-consumption-ledger-v1`

Public API accepterer ikke caller-valgt ledger-root, clock eller prebuilt receipt.
Mutation kræver elevated host operator og den eksisterende host-control
validering. Ordinary ModelRig service-identiteter er ikke replay-state writers.

Garantien er eksplicit host-local. `global_replay_safe=false`; kompromitteret
root/host-admin eller distribueret replay på tværs af hosts er uden for denne
slices garanti.

### 4. Create-once reservation gør crash-uncertainty fail-closed

Ledger-keyen er exact `start_nonce_sha256`. Consumption bruger den eksisterende
crash-durable no-overwrite primitive og følgende monotone rækkefølge:

1. create-once lock/reservation;
2. create-once pending canonical receipt;
3. create-once final canonical receipt;
4. reparse/revalidate final receipt;
5. durable cleanup af pending + lock.

Hvis trin 1 er lykkedes, men et senere trin fejler eller processen crasher,
regnes noncen stadig som **forbrugt/uncertain**. En senere consume må ikke
forsøge igen og må ikke gøre noncen reusable. Uden et valid final receipt er der
heller ingen downstream execution-authority.

Recovery af uncertain state er bevidst ikke automatisk i ADR-DC-025; en senere
separat recovery/execute-boundary må definere den authority, hvis den bliver
nødvendig.

### 5. Receipt stopper før execution

Et valid receipt må sætte:

- `host_local_replay_guard_committed=true`;
- `one_shot_start_required=true`;
- `start_consumed=true`;
- `pilot_start_authorized=true`.

Det skal samtidig holde:

- `global_replay_safe=false`;
- `pilot_execution_authorized=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority er kun:

`verified-host-local-dc-l16-pilot-start-consumption-only`

Et receipt er derfor bevis på, at tokenet er brændt på én host — ikke bevis på at
piloten er startet.

## Fail-closed krav

ADR-DC-025 skal mindst afvise:

1. ikke-exact eller replay-invalid ADR-DC-024 proof;
2. proof uden `pilot_start_authorized=true`;
3. proof der allerede hævder consumed/product-start/local-commit/remote authority;
4. consume før verification eller efter authorization expiry;
5. caller-valgt production ledger eller clock;
6. manglende/ugyldig detached upstream signature ved production fresh verify;
7. en nonce med existing final, pending eller lock state;
8. malformed/non-canonical/tampered receipt;
9. receipt der ændrer nested proof/scope/nonce bindings;
10. receipt der hævder pilot execution, product start, local commit eller remote/production authority;
11. forsøg på at erklære host-local ledger globalt replay-safe.

## Ikke i denne slice

ADR-DC-025 tilføjer ikke:

- product import eller feature-flag enable;
- command registry;
- task executor;
- workspace mutation;
- local commit;
- network/GitHub write;
- merge/release/deploy;
- faktisk pilot-start;
- production activation.

Et senere led skal kræve exact ADR-DC-025 receipt før nogen host-local pilot
execution kan overvejes.
