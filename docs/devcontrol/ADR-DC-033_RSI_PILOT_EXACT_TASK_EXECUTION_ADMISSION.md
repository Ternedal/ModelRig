# ADR-DC-033 — Replay-safe one-shot exact-task execution admission without task execution

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**Production activation:** false

## Kontekst

ADR-DC-032 kan host-attestere, at alle 25 fresh-revalidation checks for ét exact ADR-DC-031 packet er opfyldt. Selv et fully satisfied ADR-DC-032 proof er bevidst inert: det consumer hverken den menneskeligt signerede execution authorization eller den signerede execution nonce, og det sætter ikke `task_execution_authorized=true`.

Der mangler derfor en separat replay-safe authority-boundary mellem verified revalidation og en senere executor-transaktion.

## Beslutning

Der indføres en host-lokal create-once execution-admission ledger for ét exact ADR-DC-032 proof.

Admission kræver et fully satisfied canonical ADR-DC-032 proof og de tre detached signatures, som er nødvendige for fresh production-verification:

- ADR-DC-032 host revalidation-attestation signature;
- ADR-DC-030 human exact-task execution-authorization signature;
- ADR-DC-028 host execution-admission attestation signature.

Production re-verificerer ADR-DC-032 gennem dens host-pinnede facade. Denne verification re-verificerer samtidig ADR-DC-030 og ADR-DC-028 mod deres separate canonical verification-only trust roots. Caller-valgte verifiers accepteres ikke.

Den supplied ADR-DC-032 proof-identitet skal reproduceres af den fresh verification før ledger-mutation.

## One-shot replay identity

Ledgerens create-once key er den menneskeligt signerede `execution_nonce_sha256` fra ADR-DC-030.

Noncen er dermed den stabile one-shot identity på tværs af både re-attestation og eventuel genudstedelse af surrounding authorization metadata. Den samme nonce kan ikke få en ny replay-slot, blot fordi authorization proof, attestation-id, selected-task binding eller andre omkringliggende identiteter ændres.

Den exact authorization/task/workspace scope bliver fortsat bundet i den durable lock marker og i receiptet. Nonce-keying gør replay-reglen strengere; det fjerner ikke scope-bindingen.

Ledgeren publicerer først en create-once lock marker. Replay eller usikker publication fejler lukket og efterlader noncen reserveret for fremtidig admission.

Canonical production roots er:

- POSIX: `/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-execution-admission-ledger-v1`
- Windows: `C:\Program Files\ModelRig\DevControl\state\rsi-pilot-exact-task-execution-admission-ledger-v1`

Production kræver elevated operator og host-admin-controlled ledger root.

## Admission receipt

Et successfuldt live receipt binder transitivt og eksplicit:

- ADR-DC-032 proof/attestation/signature;
- ADR-DC-031 packet;
- ADR-DC-030 proof/signature;
- ADR-DC-028 proof/signature;
- ADR-DC-025 start receipt;
- execution nonce;
- selected task;
- workspace digest;
- human-signed local-commit upper bound;
- canonical ledger identity;
- fresh verification time og admission time.

Receiptets `admission_key_sha256` er exact lig `execution_nonce_sha256`, så den durable replay identity kan auditeres direkte uden en separat composite-key derivation.

Receiptet må sætte:

- `host_replay_guard_committed=true`;
- `execution_authorization_consumed=true`;
- `one_shot_execution_required=true`;
- `task_execution_admission_observed=true`;
- `task_execution_authorized=true`.

Det holder fortsat obligatorisk:

- `task_execution_started=false`;
- `execution_consumed=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- production activation=false.

Authority er kun:

`host-admitted-one-dc-l16-exact-task-execution-only`

Admission er host-lokal replay-sikkerhed for den signerede execution nonce; denne ADR fremsætter ingen påstand om global/distribueret replay-sikkerhed på tværs af uafhængige hosts eller ledger roots.

## Live transaction provenance

Den exact receipt-instans, som returneres fra den successfulde durable transaction, registreres med process-lokal live provenance bundet til de eksakte durable lock- og receipt-bytes.

`transaction_authenticated` serialiseres bevidst ikke. Et receipt, der er gemt, reloadet eller konstrueret fra canonical JSON, er derfor historisk evidence og kan ikke genvinde live execution authority alene.

En senere executor-boundary skal kræve den exact live receipt med `transaction_authenticated=true`, consume execution-admissionen one-shot og udstede separat post-execution evidence. Det er ikke en del af ADR-DC-033.

## Freshness

Admission må kun ske efter den fresh ADR-DC-032 verification og før det tidligste af:

- ADR-DC-030 human execution-authorization expiry;
- 300 sekunder efter ADR-DC-032 attestation time.

Hvis freshness udløber efter durable reservation men før receipt-publication, fejler transaktionen lukket og reservationen genbruges ikke.

## Authority stop

ADR-DC-033 udsteder kun execution admission. Den:

- kalder ingen task executor eller subprocess;
- registrerer ingen general shell eller model-defined command;
- muterer ikke workspace;
- opretter ingen local commit;
- laver ingen network write eller credential transport;
- muterer ikke Git/GitHub;
- merger, releaser eller deployer intet;
- starter ikke product pilot;
- aktiverer ikke production.

`task_execution_authorized=true` er derfor ikke det samme som `task_execution_started=true`.

## Næste boundary

Næste separate boundary er en executor-consumption transaction, som kun må acceptere den exact live ADR-DC-033 receipt, consume den én gang og køre den allerede fastlåste allowlisted command plan under de bounded execution-budget-, isolation-, kill/revoke- og network-write constraints, som ADR-DC-029/032 har verificeret.

Den boundary skal fortsat holde local commit- og remote publication-authority adskilt og udstede et exact post-execution receipt.

## Ikke omfattet

Denne ADR:

- opretter ingen rigtig ADR-DC-028/030/032 signature;
- kører ingen pilot-task;
- consumer ikke en ADR-DC-033 receipt i en executor;
- giver ingen local commit-authority;
- giver ingen remote publication-authority;
- aktiverer ikke production.

`production_activation=false`.
