# ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. Signaturen må kun betyde, at en identificeret menneskelig authority har anmodet om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke, at `main` stadig matcher, den starter ingen probes, og den giver ingen pilot-, publication- eller activation-authority.

Reservation-laget skal derfor lukke fire forskellige huller uden at blande dem sammen:

1. **trust root** — caller må ikke selv vælge den Ed25519-keyring, der afgør om callerens egen signatur er trusted;
2. **runtime/observation** — caller må ikke levere en fabrikeret `main`-observation eller en mutable Git-runtime, der kan udskiftes mellem verification og execution;
3. **time/replay** — caller må ikke backdate consumption eller genbruge samme request på den canonical host-ledger;
4. **provenance** — schema-valid persisted bytes må ikke kunne opgraderes til live authenticated authority alene ved at ligge på den rigtige path, ved at blive udskiftet byte-identisk før registration eller ved senere at blive genskabt.

En lokal filesystem-ledger kan kun etablere fail-closed replay/recovery-state på den konkrete host. Den kan ikke bevise distribueret/global one-time use. Denne ADR holder derfor `global_replay_safe=false` og reserverer enhver senere fysisk campaign-admission til en separat boundary.

## Beslutning

Den authority-bærende sekvens er:

`host-pinned request trust root → caller value snapshots → signed request verification → signed runtime pin → transaction-private runtime staging → trusted preflight → create-once permanent replay-marker med retained original descriptor → trusted main re-read → post-marker signed-chain reverify → create-once final med retained original descriptor → exact-byte/canonical read-back → claim af de oprindelige create-once fil-identiteter → transaction-authenticated in-memory receipt`

### 1. Public consume må ikke acceptere caller-valgt trust root

Den eneste public authority-bearing path er:

`consume_physical_qualification_request_once(...)`

Dens caller-input er begrænset til:

- exact `TrustedGitRuntime`;
- `PhysicalQualificationRequest`;
- `QualificationPacket`;
- `CandidateSnapshotReceipt`;
- `DetachedEd25519AuthoritySignature`.

Public API må **ikke** acceptere:

- `Ed25519AuthorityVerifier` eller anden keyring/trust-root;
- caller-konstrueret `LocalMainHeadObservation`;
- caller-valgt clock/`consumed_at_utc`;
- caller-valgt ledger-root/ledger-ID;
- caller-valgt repository-root eller Git operation-root;
- prebuilt reservation receipt.

Produktion resolver selv Ed25519-verifieren fra en fast host-kontrolleret public-keyring:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-physical-request-authority-keyring-v1.json`;
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-physical-request-authority-keyring-v1.json`.

Keyringen bruger schema `kaliv-rsi-physical-request-authority-keyring/v1` og authority-domain `rsi-dc-l15-physical-request`. Den skal være canonical JSON, non-empty, size-bounded, link-free og indeholde exact `TrustedEd25519AuthorityKey`-evidence for issuer-system `kaliv-rsi-dc-l15-request-authority-v1` med et gyldigt minimum keyring epoch. Manglende, malformed, wrong-domain eller unsafe keyring fejler lukket; der findes ingen fallback til caller-input, genereret nøgle eller repository-embedded private key.

Host-control verificeres platform-specifikt:

- på POSIX kræves root-owned keyring og root-owned directory chain uden group/world-write;
- på Windows inspiceres native security descriptors for keyring-filen og den beskyttede directory-chain under `Program Files`; owner skal være en host-admin principal, og write/control ACEs må ikke gives til almindelige brugere eller brede principals. Manglende/ukendt/uforståelig ACL-evidence fejler lukket.

Der tilføjes ingen private-key loader, signer, credential transport eller network lookup. Modulet er verification-only.

En underscored/private transaction-seam må fortsat modtage en injected verifier til deterministic tests. Den seam er ikke package-root API. Det tidligere non-underscored `improvement_physical_reservation_impl` compatibility-modul er fjernet fra pakken, så der ikke findes et importérbart compatibility-namespace, der via forwarded functions, `__globals__` eller closure-state kan traverseres til verifier-injection. Denne ADR påstår ikke, at Python-underscore-navne beskytter mod vilkårlig kompromitteret kode i samme proces; authority-kontrakten er, at production entrypoint ikke giver caller-valg af trust-root.

### 2. Caller-ejede authority-objekter snapshots før brug

Før første authority-beslutning rekonstruerer transactionen caller-ejede signed/value inputs til exact-type lokale snapshots:

- `PhysicalQualificationRequest` fra canonical JSON;
- `QualificationPacket` fra canonical JSON;
- `CandidateSnapshotReceipt` fra canonical mapping;
- `DetachedEd25519AuthoritySignature` fra canonical mapping.

Den host-resolved production-verifier snapshots ligeledes til en lokal exact `Ed25519AuthorityVerifier` med canonical-rekonstruerede exact `TrustedEd25519AuthorityKey`-værdier og samme minimum keyring epoch.

Subclasses af authority-typer afvises. Fra dette punkt bruger transactionen kun de lokale snapshots. Efterfølgende caller-mutation via fx `object.__setattr__` kan derfor ikke ændre request, qualification, signature, snapshot receipt eller keyring, som receiptet bygges fra.

### 3. Trusted Git execution flyttes væk fra callerens mutable tree

Callerens `TrustedGitRuntime` skal være exact type. Den verificeres og bindes mod runtime-identiteten i den `CandidateSnapshotReceipt`, hvis SHA allerede indgår i qualification-kæden.

Derefter kopieres hele runtime-treeet create-once til en transaction-private staging-root under canonical operation-root. Kopien re-verificeres, og kun en ny `TrustedGitRuntime` over denne private transaction-root må bruges til preflight og post-marker `refs/heads/main^{commit}` reads.

Reservationen kræver fortsat:

- snapshot receipt SHA matcher qualification;
- task/materialization identity matcher;
- candidate commit/tree matcher;
- Git runtime manifest digest matcher signed snapshot;
- Git executable digest matcher signed snapshot.

Mutation eller replacement af callerens oprindelige executable/helpers efter snapshot kan derfor ikke ændre den runtime, der producerer authority-observationen.

### 4. Replay-marker kommer før authority-bearing main-observation

Et preflight-read må bruges til at undgå at brænde en åbenlyst forkert request. Den authority-bærende observation sker først efter create-once host reservation.

Create-once request-markeren er permanent replay-state, ikke midlertidig lock-cleanup. Den reservation-specifikke publication opretter markeren med `O_CREAT|O_EXCL`, skriver og fsync'er payloaden, persisterer parent directory og **beholder den oprindelige åbne descriptor/fil-identitet** under transactionens private token. Descriptoren genåbnes ikke senere for at vælge authority-baseline.

Efter markerens oprettelse læses præcis `refs/heads/main^{commit}` igen gennem transactionens private pinned runtime.

Observationen skal være lokal/read-only, uden network eller repository mutation, og binde canonical repository-root samt runtime manifest/executable identity.

Hvis `main` flytter efter preflight, eller trusted Git fejler efter replay-marker, er requesten stadig host-lokalt consumed/recovery-required. Markeren rulles ikke tilbage til en genbrugelig request. En fejlet transaction lukker eventuelle endnu ikke claimed descriptors/handles, mens den durable marker/final-state forbliver fail-closed recovery-state.

### 5. Trusted time og signatur re-verificeres efter marker

Production clock afledes internt ved transaction-boundaryen. Caller kan ikke levere eller backdate consumption time.

Efter replay-marker og post-marker `main` read re-verificeres den lokale signed request + qualification chain mod et nyt current-time timestamp og den host-resolved/snapshottede verifier.

Hvis requesten udløber mellem preflight og commit, eller signaturen/keyring-bindingen ikke længere verificerer, fejler transactionen lukket og efterlader requesten consumed/recovery-required på den canonical host-ledger.

### 6. Persisted ledger-bytes er replay/recovery-state, ikke reloadable authority

Canonical final/pending/replay-marker bytes må ikke i sig selv bevise, at den authenticated transaction skabte dem.

Derfor:

- `PhysicalQualificationReservation.from_mapping(...)` giver aldrig transaction provenance;
- private ledger reload giver `transaction_authenticated=false`;
- der findes ingen public authority-loader for persisted reservation bytes;
- `transaction_authenticated` serialiseres ikke;
- permanent replay-marker og final receipt publiceres create-once med descriptors/handles, der beholdes fra **selve `O_CREAT|O_EXCL` publicationen**;
- final read-back skal være byte-identisk med præcis den in-memory payload, transactionen create-once skrev, men et senere path-open må aldrig definere provenance-baselinen;
- pending-state er midlertidig recovery-state og behøver ingen live provenance-descriptor; den ryddes efter final publication;
- live provenance registreres først efter pending-cleanup og verification af både final og permanent replay-marker;
- registration skal **claim'e de oprindelige create-once descriptors/fil-identiteter** for final og replay-marker fra samme transaction-token. Mangler de, er bytes ændret, er original inode blevet unlinked, eller peger pathen på en anden inode, fejler transactionen lukket;
- byte-identisk replacement mellem create-once publication og provenance-registration kan derfor ikke blive registreret som ny authority-baseline;
- live provenance bindes til exact receipt object identity, originating PID, authenticated receipt SHA-256, de oprindelige create-once fil-identiteter og exact bytes;
- hver senere `transaction_authenticated` validerer de holdte descriptors/handles og kræver, at canonical paths stadig peger på de samme fil-identiteter med de samme bytes;
- unlink/replacement skaber derfor en anden eller unlinked fil-identitet og kan ikke repareres ved at skrive de gamle bytes tilbage på samme path;
- receipt-mutation ændrer digest og invaliderer provenance;
- POSIX fork-child arver ingen authority: PID skal matche, registry ryddes med `os.register_at_fork(after_in_child=...)`, inherited descriptors lukkes, og child-receiptet kan ikke være authenticated;
- transaction-scopet er isoleret med en per-context token; failed transactions frigiver alle unclaimed retained descriptors, så ingen senere transaction kan claim'e dem.

Removal, replacement eller tamper af final/replay-marker invaliderer dermed live provenance irreversibelt for den receipt-instans. Byte-identisk replacement **både før og efter registration** kan ikke mint'e eller genoplive `transaction_authenticated=true`. Durable bytes kan højst skabe replay/DoS/recovery-state; de kan ikke mint'e eller resurrecte live authority.

### 7. Replay-scope er eksplicit host-local

Et schema-validt reservation receipt siger altid:

- `ledger_scope=canonical-host-local-v1`;
- `main_head_match_confirmed=true`;
- `request_consumed=true`;
- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

Public production-pathen bruger én canonical host-state/ledger-location og eksponerer ingen selector. Private test-ledgers må bruges til deterministic regressions, men de kan aldrig ændre `global_replay_safe=false`.

En senere campaign-admission boundary skal derfor binde den faktiske physical host/runner og må ikke bruge reloadede ledger-bytes eller et process-arvet receipt alene som execution authority.

### 8. Reservationen stopper før fysisk execution

Reservation receipt skal altid bevare:

- `frozen_main_confirmed=false`;
- `physical_campaign_completed=false`;
- `campaign_start_authorized=false`;
- `pilot_go_authorized=false`;
- `activation_authorized=false`;
- `remote_publication_authorized=false`;
- `authority=consumed-request-evidence-only`.

Denne boundary må ikke starte de 11 DC-L15 probes, oprette cadence, erklære persistent `main` freeze, generere fysisk isolation-evidens, autorisere pilot, merge/push/release/deploy, remote publication eller DC-L16 activation.

## Canonical transaction-rækkefølge

1. resolve og host-control-validér RSI request-authority keyring/verifier;
2. snapshot exact-type request/qualification/snapshot/signature og den host-resolved verifier;
3. verificér callerens exact `TrustedGitRuntime` og stage transaction-private runtime-copy;
4. opret transaction-private publication token og re-verificér signed request ved trusted current time;
5. trusted preflight af `main` gennem private pinned runtime;
6. create-once permanent host-local replay-marker keyed af request SHA-256, og behold descriptor/fil-identitet fra den oprindelige publication;
7. trusted post-marker `main` read gennem samme private pinned runtime;
8. trusted-current-time re-verifikation af signed request + qualification;
9. create-once pending payload;
10. create-once final canonical payload, og behold descriptor/fil-identitet fra den oprindelige publication;
11. exact-byte read-back + canonical parse uden authority grant;
12. cleanup kun pending; replay-marker bevares;
13. claim de oprindelige final + replay-marker create-once descriptors fra samme transaction-token og kræv, at paths stadig peger på samme identiteter/bytes;
14. registrér kun den returnerede live instans med process/content/original-file-identity provenance;
15. frigiv eventuelle unclaimed transaction descriptors og cleanup transaction-private Git-runtime fail-closed.

Hvis noget fejler efter trin 6, kan requesten ikke genbruges på samme canonical host-ledger uden en separat eksplicit recovery-procedure.

## Fail-closed krav

Implementationen skal mindst afvise eller fail-close ved:

1. caller-supplied verifier/keyring/trust root i public consume;
2. manglende, malformed, wrong-domain, non-canonical eller unsafe host keyring;
3. POSIX ownership/mode-brud eller Windows owner/DACL, der giver ikke-admin principals write/control authority;
4. authority key for forkert issuer-system eller stale minimum keyring epoch;
5. et packaged/non-underscored verifier-taking compatibility-modul eller forwarded live implementation objects, som kan traverseres til private verifier-injection;
6. forged/caller-supplied observation, clock eller authority-path;
7. subclasses/overridable authority-inputs eller `TrustedGitRuntime`;
8. caller-owned signed input mutation efter snapshot/verification;
9. caller runtime mutation efter private staging;
10. runtime identity mismatch mod signed `CandidateSnapshotReceipt`;
11. malformed/wrong `main` SHA eller `main` drift mellem preflight og post-marker read;
12. expired/invalid signed request efter marker;
13. duplicate canonical-host consume eller crash-left marker/pending/final state;
14. direct/prebuilt/fabricated final receipt persistence;
15. non-canonical eller non-identical final read-back;
16. byte-identisk eller ændret final/replay-marker inode replacement mellem create-once publication og provenance-registration;
17. manglende/mismatched original create-once descriptor ved provenance claim;
18. final/replay-marker tamper efter registration;
19. delete→byte-identical recreate af final eller replay-marker efter registration;
20. live receipt mutation;
21. POSIX fork inheritance;
22. cross-transaction descriptor claim eller lækkede unclaimed descriptors efter failure;
23. ethvert forsøg på at hæve global replay-, freeze-, campaign-, pilot-, publication- eller activation-authority.

## Artefakter

- `kaliv-rsi-physical-request-authority-keyring/v1` — host-kontrolleret verification-only public-key trust root;
- `kaliv-rsi-local-main-head-observation/v1` — parsebar evidence-only observation;
- `kaliv-rsi-physical-qualification-reservation/v1` — canonical host-local replay/evidence data;
- `consume_physical_qualification_request_once(...)` — eneste public authority-bearing consume path;
- canonical host ledger — final + permanent replay-marker som replay/recovery-state;
- transaction-private Trusted Git staging under canonical operation-root;
- transaction-scoped original-publication descriptor registry for final/replay-marker;
- process-local live provenance registry med de claimed oprindelige final/replay-marker descriptors/handles og fil-identiteter.

## Konsekvens

Efter denne boundary kan DevControl bevise, at en human-signed request blev verificeret mod en **host-pinned, caller-uafhængig public-key trust root med platform-specifik host-control validation**, matchede den signerede software/runtime chain, observerede det ønskede `main` gennem pinned trusted Git efter permanent host reservation og producerede et live process-bound receipt, hvis provenance er bundet til de **oprindelige create-once durable fil-identiteter fra publicationstidspunktet** — ikke til senere path-bytes eller en fil, der først blev åbnet ved registration.

Det beviser fortsat ikke global replay-sikkerhed, persistent frozen `main`, fysisk campaign completion, pilot-GO, publication eller activation. De authority-led forbliver åbne og skal behandles i separate senere ADR'er/boundaries.