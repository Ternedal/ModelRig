# ADR-DC-025 — Host-local replay-safe one-shot pilot-start authorization consumption

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Kontekst

ADR-DC-024 kan efter fresh host-pinned verification bevise en kortlivet,
human-signeret authorization til præcis én fremtidig lokal pilot-start. Et
sådant proof kan sætte `pilot_start_authorized=true`, men holder bevidst
`start_consumed=false` og `product_pilot_started=false`.

Det efterlader næste authority-gap: samme gyldige start-authorization må ikke
kunne bruges to gange, og et serialiseret ADR-DC-024 proof må ikke i sig selv
blive consumption authority. Samtidig må consumption ikke snige faktisk task-
execution eller produkt-start ind i replay-leddet.

## Beslutning

ADR-DC-025 indfører én host-local, create-once consumption transaction over den
signerede ADR-DC-024 `start_nonce_sha256` og udsteder et canonical consumption
receipt.

Successful consumption betyder kun, at den exact menneskelige start-
authorization er irreversibelt brugt på denne host. Det er **ikke** bevis for, at
en task eller produktpilot er startet.

### 1. Fresh upstream authority før replay-state røres

Production consumption accepterer:

- exact ADR-DC-024 `PilotStartAuthorizationProof`;
- den detached ADR-DC-024 human authorization-signatur;
- den detached ADR-DC-023 preflight-attestation-signatur.

Et serialiseret ADR-DC-024 proof er ikke selv-autentificerende. Før ledger-state
må muteres skal production kalde den offentlige ADR-DC-024 production-boundary,
som frisk re-verificerer både ADR-DC-023 og ADR-DC-024 mod deres canonical
host-controlled verification-only keyrings.

Den friske proof-identitet skal reproducere alle stabile signed/bound semantics
fra det supplied proof, herunder authorization/signature, upstream proof hashes,
start-nonce og authority flags. Kun `verified_at_utc` må naturligt ændres ved en
frisk verification.

Missing/invalid/revoked/untrusted upstream signature, proof drift, stale
authorization eller caller-konstrueret proof-shaped data fejler lukket **før**
consumption-ledgeren røres.

### 2. Canonical host-admin ledger

Production resolver kun én pre-provisioned, host-admin-kontrolleret replay-root:

- Windows: `C:\Program Files\ModelRig\DevControl\state\rsi-pilot-start-consumption-ledger-v1`
- POSIX: `/var/lib/modelrig/devcontrol/rsi-pilot-start-consumption-ledger-v1`

Consumption kræver elevated host operator og eksisterende host-controlled
ledger-root. Caller kan ikke vælge ledger-path, replay-store, verifier eller
clock.

Garantien er eksplicit host-local. Receiptet siger derfor:

- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

Distributed/global one-time use kræver en separat senere authority-model.

### 3. Signed start nonce er create-once replay key

Exact ADR-DC-024 `start_nonce_sha256` er ledgerens replay key.

Før final receipt publication oprettes en permanent create-once lock, der binder:

- ledger identity;
- exact start nonce;
- exact ADR-DC-024 authorization SHA-256;
- exact ADR-DC-024 human signature SHA-256.

Hvis lock/final/pending state allerede findes, fejler ny consumption lukket.
Nonce-genbrug kan derfor ikke blive en ny lokal start-authorization, heller ikke
hvis caller prøver at pakke den ind i et nyt objekt.

### 4. Freshness kontrolleres både før og efter irreversible reservation

Authorizationen skal stadig være gyldig ved første consume-check.

Efter create-once lock er publiceret kontrolleres tiden igen før final receipt.
Hvis authorizationen udløber mellem de to checks, fejler transaktionen lukket og
den permanente lock bliver stående som recovery-state. Authorizationen bliver
ikke genoplivet eller gjort brugbar igen.

Hvis authorizationen allerede er stale **før** lock-oprettelsen, skrives ingen
replay-state.

ADR-DC-025 definerer ikke automatisk recovery. Admin/recovery af en incomplete
consumption skal være en separat, eksplicit boundary; den må aldrig slette replay-
markøren og genåbne den signerede authorization.

### 5. Consumption receipt

Et successful receipt binder mindst:

- exact supplied ADR-DC-024 proof og dets SHA-256;
- SHA-256 af den fresh re-verificerede ADR-DC-024 proof-identitet;
- exact authorization SHA-256;
- exact ADR-DC-024 human signature SHA-256;
- exact ADR-DC-023 preflight signature SHA-256;
- exact signed `start_nonce_sha256`;
- canonical fresh verification time;
- canonical consumption time;
- canonical ledger-root path digest.

Receipt authority er kun:

`host-consumed-dc-l16-pilot-start-authorization-only`

Successful receipt sætter:

- `start_consumed=true`;
- `start_receipt_issued=true`;
- `host_replay_guard_committed=true`.

`pilot_start_authorized=true` bevares kun som historisk provenance: den
menneskelige start-permission var gyldig og blev consumed. For at undgå enhver
fortolkning som execution authority kræver receiptet samtidig eksplicit:

- `task_execution_authorized=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- `remote_write_authorized=false`;
- `push_authorized=false`;
- `pr_mutation_authorized=false`;
- `merge_authorized=false`;
- `release_authorized=false`;
- `deploy_authorized=false`;
- `production_activation_authorized=false`.

### 6. Durable receipt er audit state, ikke genindlæselig live authority

En receipt oprettet i den aktive consumption transaction får process-local live
transaction provenance, som også binder de durable final/lock bytes.

Denne provenance serialiseres ikke. Et receipt, der senere genindlæses fra JSON,
kan være audit-evidence, men får ikke automatisk live transaction authority.

En senere task-start boundary skal derfor ikke acceptere et vilkårligt
serialiseret ADR-DC-025 receipt som execution-admission. Den skal revalidere den
canonical host-ledger/provenance og exact upstream bindings i en separat ADR.

## Ikke en del af denne ADR

Denne slice:

- opretter ingen faktisk human-signatur;
- starter ingen DevControl task;
- registrerer ingen command i default catalog;
- aktiverer ingen feature flag, backend-route, Desktop- eller Android-surface;
- etablerer ingen executor;
- udfører ingen local commit;
- udfører ingen remote write, push, PR mutation, merge, release eller deploy;
- giver ingen production activation authority;
- påstår ingen distributed/global replay-safety;
- implementerer ingen automatisk recovery fra incomplete consumption.

## Falsificerbare kontrakter

ADR-DC-025 skal mindst bevise/afvise:

1. første consume af et fresh exact ADR-DC-024 proof lykkes;
2. andet consume af samme signed nonce fejler;
3. supplied/fresh ADR-DC-024 proof drift fejler;
4. stale authorization før lock efterlader ingen ledger-state;
5. expiry efter irreversible lock efterlader lock/recovery-state og intet receipt;
6. reload af serialized receipt genvinder ikke live transaction provenance;
7. receipt replay kan ikke sætte task execution/product start/integration/local commit/remote/publication/activation authority true;
8. production accepterer ikke caller-valgt ledger/root/verifier/clock;
9. root-package import registrerer ikke ADR-DC-025 som implicit capability;
10. implementationen indeholder ingen subprocess/network/GitHub write capability.

Kontrakten skal fortsat køre gennem den eksisterende Stage-B support-chain uden
at udvide den låste top-level `tests/*.py` inventory.

## Næste authority-led

En senere ADR kan definere exact task-start/execution admission over et live,
revalideret ADR-DC-025 consumption receipt. Den boundary skal være separat fra
consumption og skal fortsat holde local-commit scope, remote publication,
merge/release/deploy og production activation eksplicit adskilt.
