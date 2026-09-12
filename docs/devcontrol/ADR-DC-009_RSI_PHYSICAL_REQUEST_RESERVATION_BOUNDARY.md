# ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. En gyldig signatur beviser kun, at en identificeret human authority bad om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke, at `main` matcher SHA'en på reservationstidspunktet, og den forbruger ikke requesten.

Reservation-laget skal derfor både lukke provenance-hullet og være præcist om sin egen rækkevidde. En lokal create-once ledger kan bevise one-time consumption på den konkrete fysiske host, men den kan ikke uden distribueret koordinering bevise global replay-eksklusion på tværs af flere hosts.

Desuden er en `TrustedGitRuntime`-instans ikke i sig selv en trust-beslutning. H2-kontrakten gør runtime-manifestet content-addressed og re-verificerbart, men kræver separat review/pinning. Reservationen må derfor kun bruge den staged Git-runtime, hvis dens manifest- og executable-digests matcher den `CandidateSnapshotReceipt`, hvis SHA allerede er bundet ind i den human-signerede qualification chain.

## Beslutning

Der foreslås et separat evidence-only reservation-led:

`verified human request → signed runtime pin → trusted preflight → irreversible host lock → trusted main re-read → signed-chain reverify → canonical host receipt`

### 1. Caller leverer ikke authority-evidence eller authority-paths

Den authority-bærende public consume-path må ikke acceptere:

- et caller-konstrueret `LocalMainHeadObservation`;
- et caller-valgt `consumed_at_utc`;
- caller-valgt ledger-root eller ledger-ID;
- caller-valgt repository-root eller Git operation-root;
- et prebuilt reservation-receipt til persistence.

Observationer er fortsat serialiserbar `evidence-only` data, men typen eller schema-validitet er ikke provenance. Produktionens repository-root udledes af checkoutet, der indeholder authority-koden, og host-state/operation-root er canonical lokale paths.

### 2. Git-runtime skal være pinned af den signerede softwarekæde

Public consume modtager den `CandidateSnapshotReceipt`, som qualification-pakken refererer til. Før observation accepteres skal reservation-laget bevise:

- `snapshot_receipt.sha256 == qualification.snapshot_receipt_sha256`;
- samme task- og materialization-receipt-identitet;
- samme candidate commit/tree;
- observationens `git_runtime_manifest_sha256` matcher snapshot-receiptet;
- observationens `git_executable_sha256` matcher snapshot-receiptet.

Dermed kan en caller ikke stage en anden integritetsgyldig Git-pakke, lade den lyve om `refs/heads/main` og få observationen behandlet som den runtime, som den signerede RSI-kæde faktisk bandt.

### 3. Trusted main læses efter den irreversible lock

Et preflight-read må bruges til at undgå at brænde en åbenlyst mismatchende request. Den authority-bærende observation foretages imidlertid først **efter** create-once reservation-locken er durably oprettet.

Den post-lock observation skal:

- læse præcis `refs/heads/main^{commit}` gennem den pinned staged `TrustedGitRuntime`;
- være lokal og read-only;
- udføre ingen network-operation;
- mutere intet repository;
- binde repository `Ternedal/ModelRig`;
- binde canonical repository-root path, signed snapshot receipt, Trusted Git runtime-manifest og executable digest;
- bruge timestamp afledt internt ved write-boundary'en.

Hvis `main` flytter mellem preflight og post-lock read, fejler operationen **efter requesten er host-lokalt consumed**. Den bliver ikke automatisk genbrugelig.

### 4. Signatur og expiry re-verificeres efter lock

Human request-signaturen og qualification-bindingen re-verificeres igen ved et internt current-time timestamp efter lock og post-lock observation.

Caller kan derfor ikke backdate consumption for at genbruge en udløbet request. Hvis requesten udløber efter lock men før final commit, forbliver lock-state fail-closed/recovery-required.

### 5. Final receipt mintes kun gennem den authenticated transaction

Der findes ingen public ledger-write API, som accepterer et allerede konstrueret `PhysicalQualificationReservation`.

Den canonical rækkefølge er:

1. re-verificér request + qualification ved internt current time;
2. trusted preflight af `main` gennem den signed/pinned Git-runtime;
3. create-once host-local lock keyed af requestens canonical SHA-256;
4. trusted post-lock `main` observation gennem samme pinned runtime;
5. trusted-current-time re-verifikation af signed request + qualification;
6. create-once pending payload;
7. create-once final canonical payload;
8. canonical read-back, som først dér mintes som `PhysicalQualificationReservation`;
9. durable cleanup af pending/lock.

Hvis noget fejler efter trin 3, må requesten ikke genbruges på samme canonical host ledger uden en separat eksplicit recovery-procedure.

### 6. Replay-scope er host-local, ikke global

Produktionens public API bruger én canonical host-local ledger-location og eksponerer ingen root/ID-selector. Receipt binder SHA-256 af den konkrete ledger-root samt canonical repository-root og pinned Git-runtime-identitet.

Et gyldigt receipt har altid:

- `ledger_scope=canonical-host-local-v1`;
- `main_head_match_confirmed=true`;
- `request_consumed=true`;
- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

`global_replay_safe=false` er en vigtig sandhed, ikke en mangel der må skjules. En lokal filesystem-ledger kan ikke bevise, at den samme signed request ikke er præsenteret på en anden host. En senere campaign-admission boundary skal derfor binde den autoriserede fysiske host/runner-identitet, før requesten kan bruges til faktisk execution.

### 7. Exact-main er stadig ikke persistent freeze

Post-lock observationen beviser kun, at `refs/heads/main` matchede `requested_frozen_main_sha` på det konkrete observationstidspunkt.

Receipt skal derfor fortsat have:

- `frozen_main_confirmed=false`;
- `physical_campaign_completed=false`;
- `campaign_start_authorized=false`;
- `pilot_go_authorized=false`;
- `activation_authorized=false`;
- `remote_publication_authorized=false`.

En senere campaign-admission boundary skal re-verificere relevant frozen-main/host evidence omkring selve fysiske runner-starten.

### 8. Ingen fysisk execution authority

Reservation-leddet må ikke:

- starte de 11 DC-L15 probes;
- oprette background cadence;
- erklære vedvarende `main` freeze;
- generere fysisk isolation-evidens;
- erklære DC-L15 completed;
- autorisere pilot-GO;
- autorisere merge, push, release, deploy eller remote publication;
- aktivere DC-L16.

## Artefakter

- `kaliv-rsi-local-main-head-observation/v1` — parsebar evidence-only observation;
- `kaliv-rsi-physical-qualification-reservation/v1` — canonical host-local reservation receipt;
- `consume_physical_qualification_request_once(...)` — eneste public authority-bearing write-path;
- `load_physical_qualification_reservation(...)` — loader kun fra canonical host-local ledger.

Reservationens authority er fast `consumed-request-evidence-only`.

## Fail-closed krav

Implementationen skal mindst afvise eller fail-close ved:

1. forged/caller-supplied observation i authority-pathen;
2. caller-supplied/backdated consumption time;
3. caller-valgt repository/operation/ledger path i public authority-pathen;
4. staged Git-runtime der ikke matcher snapshot-receiptet i den signerede qualification chain;
5. forkert eller malformed `main` SHA;
6. `main` der flytter mellem preflight og post-lock read;
7. expired eller ugyldig human request ved post-lock re-verifikation;
8. duplicate consumption i canonical host ledger;
9. enhver eksisterende final/pending/lock-state som genbrugelig request;
10. direct persistence af prebuilt/fabricated final receipt;
11. tampering med canonical final reservation;
12. receipt-forsøg på at hæve global replay-, freeze-, campaign-, pilot-, publication- eller activation-authority.

## Konsekvenser

Efter denne boundary kan DevControl sandfærdigt bevise, at en specifik human-signeret request blev re-verificeret, at observationen brugte den Git-runtime-identitet som den signerede softwarekæde allerede bandt, at den canonical lokale `main` matchede ved post-lock observationen, og at requesten blev taget ud af replay-puljen på den canonical fysiske host.

Det er fortsat **ikke** global replay-bevis, vedvarende frozen-main-bevis eller tilladelse til at starte fysisk execution. Det næste authority-led skal være en separat host/freeze/campaign-admission boundary.
