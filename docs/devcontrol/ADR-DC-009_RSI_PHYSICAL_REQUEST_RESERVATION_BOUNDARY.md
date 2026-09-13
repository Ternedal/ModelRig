# ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. En gyldig signatur beviser kun, at en identificeret human authority bad om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke, at `main` matcher SHA'en på reservationstidspunktet, og den forbruger ikke requesten.

Reservation-laget skal derfor lukke observation-, time- og replay-huller uden at overdrive, hvad et lokalt filesystem kan bevise. En lokal create-once ledger kan etablere fail-closed replay/recovery-state på den konkrete host, men kan hverken bevise global replay-eksklusion eller i sig selv autentificere, hvem der skrev en fil i ledger-mappen.

Desuden er en `TrustedGitRuntime`-instans ikke i sig selv en trust-beslutning. H2-kontrakten gør runtime-manifestet content-addressed og re-verificerbart, men kræver separat review/pinning. Reservationen må derfor kun bruge en Git-runtime, hvis dens manifest- og executable-digests matcher den `CandidateSnapshotReceipt`, hvis SHA allerede er bundet ind i den human-signerede qualification chain. Den caller-ejede runtime-tree må heller ikke forblive execution-path efter verification: en anden principal kan ellers udskifte executable/helpers mellem hash-check og process-start. Authority-transaktionen skal derfor kopiere den verificerede runtime til en transaction-private staging-root under sin canonical operation-root og udføre alle trusted Git-reads gennem den private kopi.

Caller-ejede Python-objekter er heller ikke immutable authority bare fordi deres dataclasses er `frozen=True`: subclasses kan override adfærd, og `object.__setattr__` kan mutere felter mellem verification og receipt-building. Authority-transaktionen skal derfor selv skabe lokale exact-type value snapshots af alle signerede/verificerede inputs, før nogen authority-beslutning bruges videre.

## Beslutning

Der foreslås et separat evidence-only reservation-led:

`caller input snapshot → verified human request → signed runtime pin → transaction-private runtime staging → trusted preflight → irreversible permanent host replay-marker → trusted main re-read → signed-chain reverify → create-once final replay state → exact-byte read-back → transaction-authenticated in-memory receipt`

### 1. Caller leverer ikke authority-evidence eller authority-paths

Den authority-bærende public consume-path må ikke acceptere:

- et caller-konstrueret `LocalMainHeadObservation`;
- et caller-valgt `consumed_at_utc`;
- caller-valgt ledger-root eller ledger-ID;
- caller-valgt repository-root eller Git operation-root;
- et prebuilt reservation-receipt til persistence.

Observationer er fortsat serialiserbar `evidence-only` data, men typen eller schema-validitet er ikke provenance. Produktionens repository-root udledes af checkoutet, der indeholder authority-koden, og host-state/operation-root er canonical lokale paths.

Før første authority-verifikation skal transaktionen desuden snapshotte caller-ejede inputs til nye, exact-type value objects:

- `PhysicalQualificationRequest` via canonical JSON parse;
- `QualificationPacket` via canonical JSON parse;
- `CandidateSnapshotReceipt` via canonical mapping reconstruction;
- `DetachedEd25519AuthoritySignature` via canonical mapping reconstruction;
- `Ed25519AuthorityVerifier` via en ny verifier bygget af exact-type, canonical-rekonstruerede trusted keys og samme minimum keyring epoch.

Subclasses af disse authority-typer afvises. Efter snapshot må transactionen kun bruge de lokale snapshots, så efterfølgende caller-mutation ikke kan ændre den request, qualification, signature, snapshot receipt eller keyring, som receiptet bindes til.

### 2. Git-runtime skal være pinned og flyttes ud af callerens mutable tree

Public consume modtager den `CandidateSnapshotReceipt`, som qualification-pakken refererer til. Callerens `TrustedGitRuntime` skal være exact type; subclasses afvises. Transaktionen verificerer caller-runtimeens manifest, receipt-layout og filer og opretter derefter en ny transaction-private staging-root under den canonical operation-root. Den komplette runtime kopieres create-once til denne private root via den eksisterende trusted-runtime staging-kontrakt og re-verificeres dér. Kun en ny `TrustedGitRuntime` over den private transaction-root må bruges til preflight, post-lock observation og runtime-evidence.

Før observation accepteres skal reservation-laget bevise:

- `snapshot_receipt.sha256 == qualification.snapshot_receipt_sha256`;
- samme task- og materialization-receipt-identitet;
- samme candidate commit/tree;
- den private runtimes `git_runtime_manifest_sha256` matcher snapshot-receiptet;
- den private runtimes `git_executable_sha256` matcher snapshot-receiptet.

Dermed kan en caller hverken bruge en overridable `TrustedGitRuntime` subclass, stage en anden integritetsgyldig Git-pakke eller mutere den oprindelige caller-ejede runtime efter snapshot og få en anden executable/helper til at producere authority-observationen. Runtime-kopien slettes først, når consume-forsøget har produceret eller fail-closed efter sin ledger-state; den caller-ejede tree bruges aldrig som execution-path efter staging.

### 3. Trusted main læses efter den irreversible replay-marker

Et preflight-read må bruges til at undgå at brænde en åbenlyst mismatchende request. Den authority-bærende observation foretages imidlertid først **efter** create-once reservation-markeren er durably oprettet.

Den post-lock observation skal:

- læse præcis `refs/heads/main^{commit}` gennem transactionens private, signed/pinned staged `TrustedGitRuntime`;
- være lokal og read-only;
- udføre ingen network-operation;
- mutere intet repository;
- binde repository `Ternedal/ModelRig`;
- binde canonical repository-root path, signed snapshot receipt, Trusted Git runtime-manifest og executable digest;
- bruge timestamp afledt internt ved write-boundary'en.

Hvis `main` flytter mellem preflight og post-lock read, fejler operationen **efter requesten er host-lokalt consumed/recovery-required**. Den bliver ikke automatisk genbrugelig.

### 4. Signatur og expiry re-verificeres efter replay-marker

Human request-signaturen og qualification-bindingen re-verificeres igen ved et internt current-time timestamp efter replay-marker og post-lock observation. Re-verifikationen bruger fortsat kun transactionens lokale snapshots af request, qualification, signature og verifier/keyring.

Caller kan derfor ikke backdate consumption for at genbruge en udløbet request eller mutere signerede inputs efter en tidligere verification og få de nye værdier ind i reservation-receiptet. Hvis requesten udløber efter replay-marker men før final commit, forbliver marker-state fail-closed/recovery-required.

### 5. Durable ledger-state er ikke reloadable authority

Et centralt trust-princip er, at eksistensen af en canonical JSON-fil i den lokale ledger **ikke** beviser, at den authenticated consume-transaktion skabte filen. En principal med direkte filesystem-write kan ellers fremstille de samme bytes.

Derfor gælder følgende:

- persisted final/pending/permanent replay-marker er replay- og recovery-state, ikke selvstændig authority;
- `PhysicalQualificationReservation.from_mapping(...)` giver altid `transaction_authenticated=false`;
- privat durability-load giver altid `transaction_authenticated=false`, også for en legitim tidligere transaction;
- der findes ingen public `load_physical_qualification_reservation(...)` authority-loader;
- `transaction_authenticated` serialiseres aldrig og kan derfor ikke mintes via JSON;
- live provenance bindes til **objekt-identitet + originating PID + SHA-256 af de autentificerede canonical receipt-contents + exact final-path/payload + exact permanent replay-marker-path/payload**;
- et efterfølgende `object.__setattr__`-angreb eller anden feltmutation ændrer canonical digest og gør straks `transaction_authenticated=false`;
- en POSIX child-process må ikke arve authority: PID skal matche, og registry ryddes desuden via `os.register_at_fork(after_in_child=...)`;
- final read-back skal være **byte-identisk med præcis den canonical payload, som transactionen netop gav til create-once write**;
- den permanente replay-marker skal stadig eksistere med præcis de bytes transactionen oprettede, både før provenance registreres og ved enhver senere `transaction_authenticated`-læsning;
- hvis final eller replay-marker fjernes, erstattes eller muteres, bliver live provenance straks falsk;
- kun den igangværende authenticated consume-transaktion må registrere live provenance, og først efter exact-payload read-back, pending-cleanup og en sidste exact-byte verification af både final og replay-marker.

Den canonical rækkefølge er:

1. snapshot exact-type caller authority-inputs;
2. verificér callerens exact-type Trusted Git-runtime og stage en transaction-private, content-identisk runtime-copy under canonical operation-root;
3. re-verificér request + qualification ved internt current time med de lokale snapshots;
4. trusted preflight af `main` gennem den private signed/pinned Git-runtime;
5. create-once **permanent** host-local replay-marker keyed af snapshot-requestens canonical SHA-256;
6. trusted post-marker `main` observation gennem samme private pinned runtime;
7. trusted-current-time re-verifikation af den lokale signed request + qualification;
8. create-once pending payload;
9. create-once final canonical payload;
10. læs final tilbage og kræv byte-identitet med payloaden fra trin 9, derefter parse + canonical validation uden at grant'e authority;
11. cleanup kun pending-state; den create-once replay-marker bevares permanent;
12. re-læs final og replay-marker og kræv exact byte-identitet med transactionens egne payloads;
13. registrér kun den returnerede in-memory instans med `(origin_pid, authenticated_receipt_sha256, object identity, final path/payload, replay-marker path/payload)`.

`transaction_authenticated=true` kræver derefter ved hver læsning, at samme objekt stadig lever, at processen har samme PID, at receiptets aktuelle canonical SHA-256 er identisk med den registrerede digest, og at både final og replay-marker fortsat findes som regular link-free files med exact registrerede bytes.

Hvis noget fejler efter trin 5, må requesten ikke genbruges på samme canonical host ledger uden en separat eksplicit recovery-procedure. Hvis processen crasher efter final write men før trin 13, bevares replay-state, men authority må ikke rekonstrueres automatisk fra filen.

Direkte filesystem-injektion, removal eller race-replacement af en perfekt canonical final-fil eller replay-marker kan derfor højst brænde/blokere den lokale request, skabe recovery/DoS-state eller invalidere et eksisterende live receipt. Det kan ikke gennem denne boundary skabe eller bevare et `transaction_authenticated=true` receipt med en brudt replay guard.

### 6. Replay-scope er host-local, ikke global

Produktionens public API bruger én canonical host-local ledger-location og eksponerer ingen root/ID-selector. Receipt binder SHA-256 af den konkrete ledger-root samt canonical repository-root og pinned Git-runtime-identitet.

Et schema-validt receipt beskriver altid:

- `ledger_scope=canonical-host-local-v1`;
- `main_head_match_confirmed=true`;
- `request_consumed=true`;
- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

Men de serialiserede felter er data, ikke transaction provenance. Kun den live returnerede, uændrede instans i den oprindelige proces med `transaction_authenticated=true` beviser, at netop denne proces gennemførte den authenticated consume-sekvens **og at dens final + permanente replay-marker stadig er intakte**. En senere boundary må aldrig opgradere et reloadet ledger-artifact alene til execution authority.

`global_replay_safe=false` er en vigtig sandhed. En lokal filesystem-ledger kan ikke bevise, at den samme signed request ikke er præsenteret på en anden host. En senere campaign-admission boundary skal derfor binde den autoriserede fysiske host/runner-identitet, før requesten kan bruges til faktisk execution.

### 7. Exact-main er stadig ikke persistent freeze

Post-marker observationen beviser kun, at `refs/heads/main` matchede `requested_frozen_main_sha` på det konkrete observationstidspunkt i den live authenticated transaction.

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
- canonical host ledger — final + permanent replay-marker som replay/recovery-state, eksplicit ikke public reloadable authority;
- transaction-private Trusted Git staging under canonical operation-root — authority-owned execution-copy, ikke callerens mutable runtime-tree.

Reservationens serialiserede authority-label er fast `consumed-request-evidence-only`; den ikke-serialiserede `transaction_authenticated` provenance er separat, content-bound, process-bound og durable-state-bound og kan ikke overleve reload, fork eller removal/tamper af final/replay-marker som authority.

## Fail-closed krav

Implementationen skal mindst afvise eller fail-close ved:

1. forged/caller-supplied observation i authority-pathen;
2. caller-supplied/backdated consumption time;
3. caller-valgt repository/operation/ledger path i public authority-pathen;
4. subclasses/overridable varianter af authority-inputs eller `TrustedGitRuntime`;
5. staged Git-runtime der ikke matcher snapshot-receiptet i den signerede qualification chain;
6. mutation/replacement af callerens runtime executable/helpers efter snapshot må ikke påvirke den transaction-private execution-copy;
7. mutation af caller-owned request/qualification/snapshot/signature/verifier efter snapshot/verification må ikke ændre det receipt, transactionen bygger;
8. forkert eller malformed `main` SHA;
9. `main` der flytter mellem preflight og post-marker read;
10. expired eller ugyldig human request ved post-marker re-verifikation;
11. duplicate consumption i canonical host ledger;
12. enhver eksisterende final/pending/replay-marker-state som genbrugelig request;
13. direct persistence af prebuilt/fabricated final receipt som authority;
14. perfekt canonical direct-written final file må stadig have `transaction_authenticated=false` ved load;
15. final-file replacement mellem create-once write og read-back skal fejle, også hvis replacement er schema-valid og canonical;
16. final removal/replacement efter read-back men før provenance-registration må ikke kunne returnere authenticated authority;
17. permanent replay-marker removal/replacement før eller efter provenance-registration skal fail-close eller gøre live provenance false;
18. mutation af et legitimt live receipt med `object.__setattr__` eller tilsvarende må straks miste transaction provenance;
19. POSIX fork-child må ikke arve parentens transaction provenance;
20. tampering med canonical final reservation;
21. receipt-forsøg på at hæve global replay-, freeze-, campaign-, pilot-, publication- eller activation-authority.

## Konsekvenser

Efter denne boundary kan DevControl i **den samme succesfulde authenticated transaction, i den oprindelige proces, mens receiptets canonical contents er uændrede og mens exact final + permanente replay-marker bytes fortsat eksisterer** sandfærdigt bevise, at en specifik human-signeret request blev re-verificeret fra lokale immutable value snapshots, at observationen blev udført gennem en transaction-private Git-runtime-copy med samme signed/pinned manifest og executable som softwarekæden bandt, at den canonical lokale `main` matchede ved post-marker observationen, og at præcis de bytes transactionen byggede blev create-once committed og læst tilbage før live provenance blev registreret.

Efter process exit eller fork kan ledger-state stadig fail-close replay og drive en særskilt recovery-procedure, men den kan ikke alene rekonstruere authenticated authority. Det næste host/freeze/campaign-admission-led skal derfor enten fortsætte direkte fra en live `transaction_authenticated=true` reservation i den oprindelige proces eller definere sin egen særskilt autentificerede recovery/attestation; det må ikke stole på et reloadet eller process-arvet ledger-artifact alene.

Det er fortsat **ikke** global replay-bevis, vedvarende frozen-main-bevis eller tilladelse til at starte fysisk execution.
