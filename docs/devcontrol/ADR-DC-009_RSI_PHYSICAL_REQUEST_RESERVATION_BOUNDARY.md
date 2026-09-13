# ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. En gyldig signatur beviser kun, at en identificeret human authority bad om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke, at `main` matcher SHA'en på reservationstidspunktet, og den forbruger ikke requesten.

Reservation-laget skal derfor lukke observation-, time- og replay-huller uden at overdrive, hvad et lokalt filesystem kan bevise. En lokal create-once ledger kan etablere fail-closed replay/recovery-state på den konkrete host, men kan hverken bevise global replay-eksklusion eller i sig selv autentificere, hvem der skrev en fil i ledger-mappen.

Desuden er en `TrustedGitRuntime`-instans ikke i sig selv en trust-beslutning. H2-kontrakten gør runtime-manifestet content-addressed og re-verificerbart, men kræver separat review/pinning. Reservationen må derfor kun bruge den staged Git-runtime, hvis dens manifest- og executable-digests matcher den `CandidateSnapshotReceipt`, hvis SHA allerede er bundet ind i den human-signerede qualification chain.

## Beslutning

Der foreslås et separat evidence-only reservation-led:

`verified human request → signed runtime pin → trusted preflight → irreversible host lock → trusted main re-read → signed-chain reverify → create-once replay state → transaction-authenticated in-memory receipt`

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

Hvis `main` flytter mellem preflight og post-lock read, fejler operationen **efter requesten er host-lokalt consumed/recovery-required**. Den bliver ikke automatisk genbrugelig.

### 4. Signatur og expiry re-verificeres efter lock

Human request-signaturen og qualification-bindingen re-verificeres igen ved et internt current-time timestamp efter lock og post-lock observation.

Caller kan derfor ikke backdate consumption for at genbruge en udløbet request. Hvis requesten udløber efter lock men før final commit, forbliver lock-state fail-closed/recovery-required.

### 5. Durable ledger-state er ikke reloadable authority

Et centralt trust-princip er, at eksistensen af en canonical JSON-fil i den lokale ledger **ikke** beviser, at den authenticated consume-transaktion skabte filen. En principal med direkte filesystem-write kan ellers fremstille de samme bytes.

Derfor gælder følgende:

- persisted final/pending/lock er replay- og recovery-state, ikke selvstændig authority;
- `PhysicalQualificationReservation.from_mapping(...)` giver altid `transaction_authenticated=false`;
- privat durability-load giver altid `transaction_authenticated=false`, også for en legitim tidligere transaction;
- der findes ingen public `load_physical_qualification_reservation(...)` authority-loader;
- `transaction_authenticated` serialiseres aldrig og kan derfor ikke mintes via JSON;
- live provenance bindes til **objekt-identitet + originating PID + SHA-256 af de autentificerede canonical receipt-contents**;
- et efterfølgende `object.__setattr__`-angreb eller anden feltmutation ændrer canonical digest og gør straks `transaction_authenticated=false`;
- en POSIX child-process må ikke arve authority: PID skal matche, og registry ryddes desuden via `os.register_at_fork(after_in_child=...)`;
- kun den igangværende authenticated consume-transaktion må registrere live provenance, og først efter create-once final write, canonical byte-identisk read-back og succesfuld cleanup.

Den canonical rækkefølge er:

1. re-verificér request + qualification ved internt current time;
2. trusted preflight af `main` gennem den signed/pinned Git-runtime;
3. create-once host-local lock keyed af requestens canonical SHA-256;
4. trusted post-lock `main` observation gennem samme pinned runtime;
5. trusted-current-time re-verifikation af signed request + qualification;
6. create-once pending payload;
7. create-once final canonical payload;
8. parse + canonical byte-identisk read-back uden at grant'e authority;
9. durable cleanup af pending/lock;
10. registrér kun den returnerede in-memory instans med `(origin_pid, authenticated_receipt_sha256, object identity)`.

`transaction_authenticated=true` kræver derefter ved hver læsning, at samme objekt stadig lever, at processen har samme PID, og at receiptets aktuelle canonical SHA-256 er identisk med den digest, der blev registreret ved trin 10.

Hvis noget fejler efter trin 3, må requesten ikke genbruges på samme canonical host ledger uden en separat eksplicit recovery-procedure. Hvis processen crasher efter final write men før trin 10, bevares replay-state, men authority må ikke rekonstrueres automatisk fra filen.

Direkte filesystem-injektion af en perfekt canonical final-fil kan derfor højst brænde/blokere den lokale request og skabe recovery/DoS-state. Den kan ikke gennem denne boundary skabe et transaction-authenticated receipt.

### 6. Replay-scope er host-local, ikke global

Produktionens public API bruger én canonical host-local ledger-location og eksponerer ingen root/ID-selector. Receipt binder SHA-256 af den konkrete ledger-root samt canonical repository-root og pinned Git-runtime-identitet.

Et schema-validt receipt beskriver altid:

- `ledger_scope=canonical-host-local-v1`;
- `main_head_match_confirmed=true`;
- `request_consumed=true`;
- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

Men de serialiserede felter er data, ikke transaction provenance. Kun den live returnerede, uændrede instans i den oprindelige proces med `transaction_authenticated=true` beviser, at netop denne proces gennemførte den authenticated consume-sekvens. En senere boundary må aldrig opgradere et reloadet ledger-artifact alene til execution authority.

`global_replay_safe=false` er en vigtig sandhed. En lokal filesystem-ledger kan ikke bevise, at den samme signed request ikke er præsenteret på en anden host. En senere campaign-admission boundary skal derfor binde den autoriserede fysiske host/runner-identitet, før requesten kan bruges til faktisk execution.

### 7. Exact-main er stadig ikke persistent freeze

Post-lock observationen beviser kun, at `refs/heads/main` matchede `requested_frozen_main_sha` på det konkrete observationstidspunkt i den live authenticated transaction.

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
- `kaliv-rsi-physical-qualification-reservation/v1` — canonical host-local replay/evidence data;
- `consume_physical_qualification_request_once(...)` — eneste public authority-bearing path og eneste vej til en live `transaction_authenticated=true` instans;
- canonical host ledger — replay/recovery-state, eksplicit ikke public reloadable authority.

Reservationens serialiserede authority-label er fast `consumed-request-evidence-only`; den ikke-serialiserede `transaction_authenticated` provenance er separat, content-bound, process-bound og kan ikke overleve reload eller fork som authority.

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
10. direct persistence af prebuilt/fabricated final receipt som authority;
11. perfekt canonical direct-written final file må stadig have `transaction_authenticated=false` ved load;
12. mutation af et legitimt live receipt med `object.__setattr__` eller tilsvarende må straks miste transaction provenance;
13. POSIX fork-child må ikke arve parentens transaction provenance;
14. tampering med canonical final reservation;
15. receipt-forsøg på at hæve global replay-, freeze-, campaign-, pilot-, publication- eller activation-authority.

## Konsekvenser

Efter denne boundary kan DevControl i **den samme succesfulde authenticated transaction, i den oprindelige proces og så længe receiptets canonical contents er uændrede** sandfærdigt bevise, at en specifik human-signeret request blev re-verificeret, at observationen brugte den Git-runtime-identitet som den signerede softwarekæde allerede bandt, at den canonical lokale `main` matchede ved post-lock observationen, og at create-once replay-state blev committed på den lokale host.

Efter process exit eller fork kan ledger-state stadig fail-close replay og drive en særskilt recovery-procedure, men den kan ikke alene rekonstruere authenticated authority. Det næste host/freeze/campaign-admission-led skal derfor enten fortsætte direkte fra en live `transaction_authenticated=true` reservation i den oprindelige proces eller definere sin egen særskilt autentificerede recovery/attestation; det må ikke stole på et reloadet eller process-arvet ledger-artifact alene.

Det er fortsat **ikke** global replay-bevis, vedvarende frozen-main-bevis eller tilladelse til at starte fysisk execution.