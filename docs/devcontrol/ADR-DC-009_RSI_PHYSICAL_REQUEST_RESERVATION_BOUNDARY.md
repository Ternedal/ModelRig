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
4. **provenance** — schema-valid persisted bytes må ikke kunne opgraderes til live authenticated authority alene ved at ligge på den rigtige path eller ved senere at blive genskabt byte-identisk.

En lokal filesystem-ledger kan kun etablere fail-closed replay/recovery-state på den konkrete host. Den kan ikke bevise distribueret/global one-time use. Denne ADR holder derfor `global_replay_safe=false` og reserverer enhver senere fysisk campaign-admission til en separat boundary.

## Beslutning

Den authority-bærende sekvens er:

`host-pinned request trust root → caller value snapshots → signed request verification → signed runtime pin → transaction-private runtime staging → trusted preflight → irreversible permanent host replay-marker → trusted main re-read → post-marker signed-chain reverify → create-once final replay state → exact-byte read-back → descriptor/file-identity-bound transaction-authenticated in-memory receipt`

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

En underscored/private transaction-seam må fortsat modtage en injected verifier til deterministic tests. Den seam er ikke package-root API og har intet non-underscored verifier-taking consume-alias. Den tidligere implementation-namespace er authority-løs og eksponerer kun eksplicitte underscore-testseams; der findes ingen generel module-forwarding/traversal til en verifier-taking production route.

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

Create-once request-markeren er permanent replay-state, ikke midlertidig lock-cleanup. Efter markerens oprettelse læses præcis `refs/heads/main^{commit}` igen gennem transactionens private pinned runtime.

Observationen skal være lokal/read-only, uden network eller repository mutation, og binde canonical repository-root samt runtime manifest/executable identity.

Hvis `main` flytter efter preflight, eller trusted Git fejler efter replay-marker, er requesten stadig host-lokalt consumed/recovery-required. Markeren rulles ikke tilbage til en genbrugelig request.

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
- final read-back skal være byte-identisk med præcis den in-memory payload, transactionen create-once skrev;
- live provenance registreres først efter pending-cleanup og ny verification af både final og permanent replay-marker;
- transactionen åbner og **beholder** descriptor/handle til final og replay-marker og binder provenance til exact object identity, originating PID, authenticated receipt SHA-256, åbnet fil-identitet og exact bytes;
- senere `transaction_authenticated` validerer de holdte descriptors/handles og deres oprindelige fil-identitet/contents, ikke blot et nyt path lookup;
- unlink/replacement skaber derfor en anden eller unlinked fil-identitet og kan ikke repareres ved at skrive de gamle bytes tilbage på samme path;
- receipt-mutation ændrer digest og invaliderer provenance;
- POSIX fork-child arver ingen authority: PID skal matche, registry ryddes med `os.register_at_fork(after_in_child=...)`, og inherited descriptors kan ikke gøre child-receiptet authenticated.

Removal, replacement eller tamper af final/replay-marker invaliderer dermed live provenance irreversibelt for den receipt-instans. Byte-identisk delete→recreate kan ikke genoplive `transaction_authenticated=true`. Durable bytes kan højst skabe replay/DoS/recovery-state; de kan ikke mint'e eller resurrecte live authority.

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
4. re-verificér signed request ved trusted current time;
5. trusted preflight af `main` gennem private pinned runtime;
6. create-once permanent host-local replay-marker keyed af request SHA-256;
7. trusted post-marker `main` read gennem samme private pinned runtime;
8. trusted-current-time re-verifikation af signed request + qualification;
9. create-once pending payload;
10. create-once final canonical payload;
11. exact-byte read-back + canonical parse uden authority grant;
12. cleanup kun pending; replay-marker bevares;
13. åbn final + replay-marker, bind descriptors/handles til fil-identitet og exact payloads;
14. registrér kun den returnerede live instans med process/content/file-identity provenance;
15. cleanup transaction-private Git-runtime fail-closed.

Hvis noget fejler efter trin 6, kan requesten ikke genbruges på samme canonical host-ledger uden en separat eksplicit recovery-procedure.

## Fail-closed krav

Implementationen skal mindst afvise eller fail-close ved:

1. caller-supplied verifier/keyring/trust root i public consume;
2. manglende, malformed, wrong-domain, non-canonical eller unsafe host keyring;
3. POSIX ownership/mode-brud eller Windows owner/DACL, der giver ikke-admin principals write/control authority;
4. authority key for forkert issuer-system eller stale minimum keyring epoch;
5. non-underscored verifier-taking consume-alias eller generel implementation-module forwarding fra public/compatibility namespace;
6. forged/caller-supplied observation, clock eller authority-path;
7. subclasses/overridable authority-inputs eller `TrustedGitRuntime`;
8. caller-owned signed input mutation efter snapshot/verification;
9. caller runtime mutation efter private staging;
10. runtime identity mismatch mod signed `CandidateSnapshotReceipt`;
11. malformed/wrong `main` SHA eller `main` drift mellem preflight og post-marker read;
12. expired/invalid signed request efter marker;
13. duplicate canonical-host consume eller crash-left marker/pending/final state;
14. direct/prebuilt/fabricated final receipt persistence;
15. schema-valid final replacement mellem create-once write og read-back;
16. final/replay-marker removal eller replacement før provenance-registration;
17. final/replay-marker tamper efter registration;
18. delete→byte-identical recreate af final eller replay-marker;
19. live receipt mutation;
20. POSIX fork inheritance;
21. ethvert forsøg på at hæve global replay-, freeze-, campaign-, pilot-, publication- eller activation-authority.

## Artefakter

- `kaliv-rsi-physical-request-authority-keyring/v1` — host-kontrolleret verification-only public-key trust root;
- `kaliv-rsi-local-main-head-observation/v1` — parsebar evidence-only observation;
- `kaliv-rsi-physical-qualification-reservation/v1` — canonical host-local replay/evidence data;
- `consume_physical_qualification_request_once(...)` — eneste public authority-bearing consume path;
- canonical host ledger — final + permanent replay-marker som replay/recovery-state;
- transaction-private Trusted Git staging under canonical operation-root;
- process-local provenance registry med holdte final/replay-marker descriptors/handles og fil-identitet.

## Konsekvens

Efter denne boundary kan DevControl bevise, at en human-signed request blev verificeret mod en **host-pinned, caller-uafhængig public-key trust root med platform-specifik host-control validation**, matchede den signerede software/runtime chain, observerede det ønskede `main` gennem pinned trusted Git efter permanent host reservation og producerede et live process-bound receipt, hvis provenance er bundet til de oprindeligt åbnede durable fil-identiteter — ikke blot til senere path-bytes.

Det beviser fortsat ikke global replay-sikkerhed, persistent frozen `main`, fysisk campaign completion, pilot-GO, publication eller activation. De authority-led forbliver åbne og skal behandles i separate senere ADR'er/boundaries.