# ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. Signaturen betyder kun, at en identificeret menneskelig authority har anmodet om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke frozen `main`, starter ingen probes og giver ingen pilot-, publication- eller activation-authority.

Reservation-laget skal lukke fire adskilte huller:

1. **trust root** — caller må ikke vælge Ed25519-keyringen, der afgør om callerens egen signatur er trusted;
2. **runtime/observation** — authority-observation må ikke komme fra caller-supplied bytes eller en runtime, som samme service-bruger kan omskrive mellem verification og execution;
3. **time/replay** — caller må ikke backdate consumption eller genbruge samme request på den canonical host-ledger;
4. **provenance** — schema-valid persisted bytes, byte-identiske replacements eller rename/replay/restore må ikke kunne mint'e eller genoplive live authority.

En lokal filesystem-ledger kan kun etablere fail-closed replay/recovery-state på den konkrete host. Den kan ikke bevise distribueret/global one-time use. `global_replay_safe` forbliver derfor `false`, og fysisk campaign-admission er en separat senere boundary.

## Beslutning

Production authority-sekvensen er:

`host-pinned request trust root → exact caller snapshots → host-admin-controlled signed runtime → trusted preflight → permanent create-once replay-marker → trusted post-marker main read → current-time signed-chain reverify → create-once final → exact read-back → original-publication file provenance + POSIX directory-chain event-history binding → transaction-authenticated in-memory receipt`

### 1. Public consume må ikke acceptere caller-valgt trust root

Den eneste public authority-bearing path er:

`consume_physical_qualification_request_once(...)`

Caller-input er begrænset til exact `TrustedGitRuntime`, `PhysicalQualificationRequest`, `QualificationPacket`, `CandidateSnapshotReceipt` og `DetachedEd25519AuthoritySignature`.

Public API accepterer **ikke** verifier/keyring, observation, clock/`consumed_at_utc`, ledger-root/ID, repository-root, operation-root eller prebuilt reservation receipt.

Produktion resolver Ed25519-verifieren fra en fast host-kontrolleret verification-only keyring:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-physical-request-authority-keyring-v1.json`;
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-physical-request-authority-keyring-v1.json`.

Keyringen skal være canonical, link-free, size-bounded, have schema `kaliv-rsi-physical-request-authority-keyring/v1`, domain `rsi-dc-l15-physical-request`, korrekt issuer-system og gyldigt minimum keyring epoch. Manglende, malformed, wrong-domain eller unsafe state fejler lukket. Der findes ingen fallback til caller-input, generated key, private-key loader, signing eller network lookup.

Host-control valideres platformsspecifikt:

- POSIX: root-owned keyring og root-owned directory chain uden group/world-write;
- Windows: native owner/DACL på fil og beskyttet directory-chain; ordinary/broad principals må ikke have write/control authority.

Verifier-injection findes kun i en underscored/private deterministic test-seam. Det tidligere non-underscored compatibility-modul er fjernet. Beslutningen påstår ikke isolation mod vilkårligt kompromitteret kode i samme Python-proces; kontrakten er, at production entrypoint ikke giver caller-valg af trust-root.

### 2. Caller-ejede authority-objekter snapshots før brug

Før første authority-beslutning rekonstrueres request, qualification, snapshot receipt og detached signature til exact-type canonical lokale snapshots. Den host-resolved verifier rekonstrueres ligeledes fra exact trusted-key values og samme minimum keyring epoch. Subclasses afvises.

Transactionen bruger derefter kun snapshots. Caller-mutation via fx `object.__setattr__` kan derfor ikke ændre den signerede chain eller de digests, som receiptet bygges fra efter verification.

### 3. Production Git execution kræver host-admin-kontrolleret runtime

`TrustedGitRuntime` skal være exact type og dens manifest/executable identity skal matche den `CandidateSnapshotReceipt`, der allerede er bundet af qualification-kæden.

Production må **ikke** eksekvere fra en per-transaction runtime-copy, der kun er `0700` og stadig kan omskrives af en anden proces under samme OS-konto. Public consume bruger derfor en særskilt host-control boundary:

- POSIX: hele runtime-treeet og ancestor chain skal være root-owned og uden group/world-write;
- Windows: runtime skal ligge under `Program Files`, og tree + directory-chain skal have native owner/DACL-evidence, hvor write/control kun tilkommer host-admin principals.

En ordinary service-user-owned runtime — også med mode `0700` — er ikke production authority og fejler lukket.

Production Git-reader understøtter kun `rev-parse --verify refs/heads/main^{commit}`, bruger ingen shell, kører med bounded subprocess og et hardened environment uden caller-writable home/config/hooks/temp state, og re-attesterer runtime-treeet før og efter execution. Den signerede snapshot-chain binder fortsat manifest- og executable-digest.

Den underscored/private deterministic test-seam må fortsat bruge transaction-private runtime staging for race-tests. Det er test-infrastruktur, ikke public production authority.

### 4. Replay-marker kommer før authority-bearing main-observation

Et trusted preflight-read må afvise en åbenlyst forkert request uden at brænde den. Den authority-bærende observation sker først efter create-once reservation.

Replay-markeren er permanent host-local replay-state. Den oprettes med `O_CREAT|O_EXCL`, skrives og fsync'es, parent directory persisteres, og den oprindelige publication-descriptor/fil-identitet beholdes. Descriptoren genåbnes ikke senere for at vælge provenance-baseline.

Efter markerens oprettelse læses præcis `refs/heads/main^{commit}` igen gennem den host-admin-kontrollerede, snapshot-pinnede production Git-reader.

Hvis `main` flytter, trusted Git fejler eller requesten senere viser sig udløbet, er requesten stadig host-lokalt consumed/recovery-required. Replay-markeren rulles ikke tilbage.

### 5. Trusted time og signatur re-verificeres efter marker

Production clock afledes internt. Caller kan ikke levere eller backdate consumption time.

Efter replay-marker og post-marker `main` read re-verificeres signed request + qualification ved et nyt current-time timestamp mod den host-resolved/snapshottede verifier. Expiry eller signature/keyring mismatch fejler lukket og efterlader requesten consumed/recovery-required.

### 6. Durable bytes er recovery-state; live provenance er process- og historie-bundet

Canonical final/pending/replay-marker bytes er ikke reloadable authority:

- `PhysicalQualificationReservation.from_mapping(...)` og ledger reload giver aldrig transaction provenance;
- `transaction_authenticated` serialiseres ikke;
- direct filesystem forgery kan højst skabe replay/DoS/recovery-state.

Permanent replay-marker og final receipt publiceres create-once og beholder de **oprindelige descriptors/handles fra selve `O_CREAT|O_EXCL` publicationen**. Final read-back skal være byte-identisk med transactionens payload, men et senere path-open må aldrig definere authority-baselinen.

Registration claim'er de oprindelige final + replay-marker descriptors fra samme transaction-token og binder live provenance til exact receipt object identity, originating PID, canonical receipt SHA-256, exact bytes samt original fil-identitet og metadata-stamp (`ctime_ns` hvor platformen eksponerer den).

Konsekvenser:

- byte-identisk inode replacement før registration kan ikke blive ny baseline;
- unlink/replacement/delete→byte-identical recreate efter registration kan ikke genoplive receiptet;
- POSIX leaf rename-away/replay/rename-back ændrer retained `ctime_ns`; observeret durable mismatch revokerer live provenance permanent;
- receipt-object mutation giver midlertidigt `transaction_authenticated=false`; præcis restoration af original authenticated content kan blive valid igen, hvis durable provenance aldrig har mismatchet;
- fork-child arver ingen authority: PID skal matche, registries ryddes og inherited descriptors lukkes;
- enhver exception fra outer consume revokerer allerede registreret provenance for transaction-tokenet **før** exceptionen bliver caller-visible. Et receipt hentet fra traceback locals efter cleanup-failure er derfor unauthenticated.

#### POSIX directory-chain event-history

Fil-identitet på final/marker og ledger-root alene fanger ikke, at en **ancestor** til ledger-rooten kan rename's og senere sættes tilbage: ledger-child inode/bytes/ctime kan da forblive uændret, selv om canonical ledger-path midlertidigt pegede et andet sted og tillod replay.

Fra **før den første permanente publication** beholdes derfor directory descriptors + `(dev, ino)` for ledger-rooten og alle dens eksisterende ancestors tilbage til filesystem-rooten, og en kernel-event history monitor armeres for hele path-kæden:

- Linux: én inotify-instance overvåger parent directories for rename/create/delete af det præcise beskyttede child-navn på hvert ancestry-led og behandler parent `MOVE_SELF`/`DELETE_SELF`/`UNMOUNT`, `IN_IGNORED` samt queue overflow som history failure;
- BSD-style POSIX: kqueue vnode monitor anvender rename/delete og revoke på hvert retained directory-object, hvor platformen understøtter det;
- en POSIX-platform uden en understøttet exact directory-chain history primitive fejler lukket ved reservation publication i stedet for at degradere provenance lydløst.

Capture→monitor-arm-vinduet lukkes med en **setup-only metadata-stamp** på hvert retained directory-object: `(dev, ino)` og stampen skal matche både den åbne descriptor og den canonical path umiddelbart før/efter monitor-arming. En rename→restore i dette vindue skal derfor fail-close. Efter arming bruges stampen ikke som generel live-history; legitime child/sibling-operationer må fortsat ændre directory-metadata uden at revokere en ellers stabil reservation.

Linux-monitoren filtrerer child-events på exact navn, så oprettelse/sletning af **andre sibling entries** i en overvåget parent ikke revokerer en ellers uændret reservation. Efter monitor-arming verificeres hvert retained directory-object fortsat via både åben descriptor og canonical path-identitet. Et relevant history-event er monotont: senere path-restoration kan ikke gøre bindingen valid igen.

Både `ledger rename-away → replay → restore` og `ancestor rename-away → replay i replacement subtree → delete replacement → restore ancestor` efterlader derfor event-history, som ikke kan skjules ved at sætte de oprindelige pathnames tilbage.

Denne event-history mekanisme er eksplicit POSIX-specifik. Der påstås ikke tilsvarende Windows inotify/kqueue semantics.

### 7. Replay-scope er eksplicit host-local

Et schema-validt reservation receipt bevarer mindst:

- `ledger_scope=canonical-host-local-v1`;
- `main_head_match_confirmed=true`;
- `request_consumed=true`;
- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

Public production-pathen bruger canonical host-state og eksponerer ingen ledger-selector. Private test-ledgers ændrer aldrig `global_replay_safe=false`.

En senere campaign-admission boundary skal binde den faktiske physical host/runner og må ikke bruge reloadede ledger-bytes eller process-arvede receipts som execution authority.

### 8. Reservationen stopper før fysisk execution

Receiptet bevarer altid:

- `frozen_main_confirmed=false`;
- `physical_campaign_completed=false`;
- `campaign_start_authorized=false`;
- `pilot_go_authorized=false`;
- `activation_authorized=false`;
- `remote_publication_authorized=false`;
- `authority=consumed-request-evidence-only`.

Denne boundary starter ikke DC-L15 probes, cadence, persistent `main` freeze, fysisk isolation-evidens, pilot, merge/push/release/deploy, remote publication eller DC-L16 activation.

## Canonical production-rækkefølge

1. resolve og host-control-validér request-authority keyring/verifier;
2. snapshot exact-type request/qualification/snapshot/signature + verifier;
3. rekonstruér exact `TrustedGitRuntime`, verificér signed runtime identity og host-admin-control af tree + chain;
4. trusted preflight af `main` gennem den restricted host-controlled Git-reader;
5. opret transaction/publication token, bind ledger-root + ancestor directory objects med setup-only stamps, arm POSIX exact directory-chain history monitor og revalidér identity/stamps før første permanente publication;
6. create-once permanent replay-marker og behold original descriptor/fil-identitet;
7. trusted post-marker `main` read gennem samme host-controlled runtime;
8. trusted-current-time re-verifikation af signed request + qualification;
9. create-once pending payload;
10. create-once final canonical payload; behold original descriptor/fil-identitet;
11. exact-byte read-back + canonical parse uden authority grant;
12. cleanup kun pending; replay-marker bevares;
13. claim original final + marker publication descriptors fra samme transaction-token;
14. registrér exact live receipt med process/content/file provenance og, på POSIX, directory-chain event-history binding;
15. ved enhver outer exception: revokér registered provenance, frigiv unclaimed descriptors/history monitors og propagér derefter fejlen.

Hvis noget fejler efter replay-markerens publication, kan requesten ikke genbruges på samme canonical host-ledger uden en separat eksplicit recovery-procedure.

## Fail-closed krav

Implementationen skal mindst afvise eller fail-close ved:

1. caller-supplied verifier/keyring/trust root i public consume;
2. manglende/malformed/wrong-domain/non-canonical/unsafe host keyring;
3. POSIX keyring ownership/mode-brud eller Windows owner/DACL med ikke-admin write/control;
4. forkert issuer-system eller stale minimum keyring epoch;
5. packaged/non-underscored verifier-taking compatibility route eller traversal til private verifier-injection;
6. forged observation, caller clock eller caller authority-path;
7. subclasses/overridable authority-inputs eller `TrustedGitRuntime`;
8. caller mutation af signed inputs efter snapshot;
9. production runtime, der er service-user-writable eller ikke host-admin-kontrolleret;
10. runtime manifest/executable mismatch mod signed `CandidateSnapshotReceipt`;
11. malformed/wrong `main` SHA eller drift mellem preflight og post-marker read;
12. expired/invalid signed request efter replay-marker;
13. duplicate consume eller crash-left marker/pending/final state;
14. direct/prebuilt/fabricated final persistence;
15. non-canonical/non-identical final read-back;
16. byte-identisk eller ændret final/marker replacement før registration;
17. missing/mismatched original publication descriptor ved claim;
18. final/marker tamper efter registration;
19. delete→byte-identical recreate af final/marker;
20. POSIX leaf rename-away/replay/rename-back;
21. POSIX ledger-root eller ancestor rename-away/replay/restore eller tab af directory-chain history monitor;
22. POSIX rename→restore under directory-history monitor arming;
23. POSIX-platform uden understøttet exact directory-chain rename-history primitive;
24. live receipt mutation uden exact content restoration;
25. POSIX fork inheritance;
26. cross-transaction descriptor/history-monitor claim eller leaked retained state;
27. outer consume/cleanup failure, der ellers ville efterlade traceback-reachable authenticated receipt;
28. ethvert forsøg på at hæve global replay-, freeze-, campaign-, pilot-, publication- eller activation-authority.

## Artefakter

- `kaliv-rsi-physical-request-authority-keyring/v1` — host-kontrolleret verification-only trust root;
- `kaliv-rsi-local-main-head-observation/v1` — parsebar evidence-only observation;
- `kaliv-rsi-physical-qualification-reservation/v1` — canonical host-local replay/evidence data;
- `consume_physical_qualification_request_once(...)` — eneste public authority-bearing consume path;
- admin-controlled production `TrustedGitRuntime` + restricted physical Git reader;
- private transaction-staged runtime seam — deterministic tests only;
- canonical host ledger — final + permanent replay-marker som recovery/replay-state;
- original-publication descriptor registry for final/replay-marker;
- POSIX ledger-root + ancestor directory descriptors, setup-only arming stamps og kernel event-history monitor;
- process-local live provenance registry med process/content/file/history binding og transaction-token-bound exception revocation.

## Konsekvens

Efter denne boundary kan DevControl bevise, at en human-signed request blev verificeret mod en caller-uafhængig host-pinned trust root, matchede den signerede software/runtime chain, observerede det ønskede `main` gennem en host-admin-kontrolleret runtime efter permanent host reservation og producerede et live process-bound receipt, hvis provenance er bundet til de oprindelige durable publications og — på POSIX — den canonical ledger-paths monotone directory-chain event history.
