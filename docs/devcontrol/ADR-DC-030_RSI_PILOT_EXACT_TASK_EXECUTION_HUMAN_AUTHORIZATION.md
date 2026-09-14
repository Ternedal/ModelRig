# ADR-DC-030 — Human-signed exact-task execution authorization without executor authority

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**Production activation:** false

## Beslutning

Efter exact ADR-DC-029 requirements indføres en separat, kortlivet menneskeligt
signeret authorization for præcis én senere exact-task execution. Dette led
registrerer kun verificeret human intent. Det consumer ikke authorizationen,
udsteder ikke execution-admission og kalder ikke en executor.

Authorizationen skal være exact bundet til hele ADR-DC-029 manifestet og dermed
til den allerede fastlåste ADR-DC-028/027/026/025 lineage: host-attestation,
detached attestation-signatur, observation packet, consumed pilot-start receipt,
repository/base/main, trial, operator surface, selected task, workspace og det
menneskeligt signerede local-commit upper bound.

## Human authority

Den menneskelige execution-authorizer skal være samme actor som signerede den
upstream ADR-DC-024 pilot-start authorization. Dermed kan modellen eller et nyt
produktlag ikke udskifte den menneskelige authority-identitet undervejs.
Execution-authorizeren skal samtidig være forskellig fra ADR-DC-028 host-
attestoren.

Claimen har kun intent:

`authorize-one-exact-task-execution`

Authorization-vinduet er højst 10 minutter. Claimen binder en separat
`execution_nonce_sha256`, som ikke må være placeholder og ikke må genbruge den
allerede consumed ADR-DC-024/025 pilot-start nonce.

Repo/runtime indeholder ingen human private signing key og fremstiller ingen
faktisk human signatur i denne ADR.

## Fresh upstream provenance

Et serialiseret ADR-DC-028 proof er ikke selv-autentificerende. Production må
ikke løfte human execution intent alene på baggrund af proofets felter.

Før den nye menneskelige signatur vurderes, skal production derfor fresh
re-verificere den detached ADR-DC-028 host-attestation-signatur mod ADR-DC-028's
canonical host-controlled verification-only trust-root. Fresh verification skal
genskabe de stabile proof-semantikker, herunder attestation/signatur/key/signer,
packet/start-receipt binding, satisfied-state og alle non-authority-felter.

Derefter verificeres den nye human-signatur mod en separat host-admin-
kontrolleret verification-only Ed25519-keyring. Public production-verifikation
accepterer ikke caller-valgt verifier og kræver elevated host operator.

Canonical human execution keyring:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-execution-authorization-keyring-v1.json`
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-execution-authorization-keyring-v1.json`

## Claim vs. verified proof

Selve claimen er inert og har:

- `human_task_execution_authorization_verified=false`;
- `execution_authorization_consumed=false`;
- `task_execution_admission_observed=false`;
- `task_execution_authorized=false`;
- `task_execution_started=false`.

Et cryptographically valid proof må kun løfte:

- `human_task_execution_authorization_verified=true`;
- `one_shot_execution_required=true`.

Selv det verificerede proof holder:

- `execution_authorization_consumed=false`;
- `task_execution_admission_observed=false`;
- `task_execution_authorized=false`;
- `task_execution_started=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority er kun
`verified-human-dc-l16-exact-task-execution-authorization-only`.

## Replay og næste boundary

Dette proof er ikke replay-safe execution-admission. Den signerede execution
nonce er kun input til et senere separat host-local one-shot consume/admission-
led med canonical replay-ledger. Det senere led skal også revalidere de øvrige
ADR-DC-029 requirements fresh, før `task_execution_authorized` overhovedet kan
blive sand.

Selv en senere consumed/admitted authorization må holdes adskilt fra den faktiske
executor-transaction og dens post-execution receipt, så crash/uncertainty ikke
kan skjules som succesfuld execution.

## Ikke del af denne ADR

Denne slice registrerer ingen command, kalder ingen executor, ændrer ingen
workspace-bytes, opretter ingen local commit, bruger ingen credentials eller
network transport og muterer ikke Git/GitHub. Den merger, releaser eller deployer
intet og aktiverer ikke produktion.
