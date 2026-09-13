# ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. Signaturen betyder kun, at en identificeret menneskelig authority har anmodet om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke frozen `main`, starter ingen probes og giver ingen pilot-, publication- eller activation-authority.

Reservation-laget skal lukke fire adskilte huller:

1. **trust root** — caller må ikke vælge Ed25519-keyringen, der afgør om callerens egen signatur er trusted;
2. **runtime/observation** — authority-observation må ikke komme fra caller-supplied bytes eller en runtime, som samme service-bruger kan omskrive mellem verification og execution;
3. **time/replay** — caller må ikke backdate consumption eller genbruge samme request gennem production consume; replay-state må samtidig ikke kunne rulles tilbage af den ordinary service-principal, som reservationen skal beskytte imod;
4. **provenance** — schema-valid persisted bytes, byte-identiske replacements eller rename/replay/restore må ikke kunne mint'e eller genoplive live authority.

En lokal filesystem-ledger kan kun etablere fail-closed replay/recovery-state på den konkrete host, når ledgeren selv ligger bag en separat host-admin boundary. Den kan ikke bevise distribueret/global one-time use, og den giver ingen garanti mod en kompromitteret host-administrator/root principal. `global_replay_safe` forbliver derfor `false`, og fysisk campaign-admission er en separat senere boundary.

## Beslutning

Production authority-sekvensen er:

`host-pinned request trust root → elevated host operator + host-admin-controlled replay ledger → exact caller snapshots → host-admin-controlled signed runtime → trusted preflight → permanent create-once replay-marker → trusted post-marker main read → current-time signed-chain reverify → create-once final → exact read-back → original-publication file provenance + Linux watch-before-trust directory-chain history → transaction-authenticated in-memory receipt`

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

Production Git-reader understøtter kun `rev-parse --verify refs/heads/main^{commit}`, bruger ingen shell og et hardened environment uden caller-writable home/config/hooks/temp state, og re-attesterer runtime-treeet før og efter execution. Authority-pathen bruger **ikke** den generelle Linux `bounded_subprocess.py` supervisor, fordi den ville genlæse en ModelRig package-fil fra disk efter runtime-attestation. I stedet launcher den allerede indlæste production-path præcis den host-attesterede Git executable direkte gennem stdlib-processprimitive, med separat process-group/session, 120-sekunders timeout, bounded combined stdout/stderr og fail-closed nonzero/timeout/output-overflow. Dermed bliver ingen ordinary ModelRig package-source genlæst som child-side execution authority mellem runtime-attestation og Git-read. Den signerede snapshot-chain binder fortsat manifest- og executable-digest.

Den underscored/private deterministic test-seam må fortsat bruge transaction-private runtime staging og den generelle subprocess-infrastruktur for race-tests. Det er test-/general-infrastruktur, ikke public production Git authority.

### 4. Production replay-state er en elevated host-operator boundary

Live provenance kan opdage tamper, mens et receipt eksisterer, men kan ikke gøre et ordinary service-user-writable directory rollback-sikkert mellem processer eller efter restart. Production replay-ledgeren må derfor ikke ejes af eller være writable gennem den almindelige ModelRig service-identitet.

Public production resolver præcis én fast, pre-provisioned ledger:

- POSIX: `/var/lib/modelrig/devcontrol/rsi-physical-request-ledger-v1`;
- Windows: `C:\Program Files\ModelRig\DevControl\state\rsi-physical-request-ledger-v1`.

Selve consume-operationen er en **fysisk host-operator handling**, ikke produkt-runtime:

- POSIX kræver effektiv UID 0. Ledger-directory og hele ancestor chain skal være root-owned, uden group/world-write og uden extended POSIX access/default ACLs. Ordinary service-processer kan derfor ikke create, unlinke, replace eller nulstille replay-markers;
- Windows kræver et elevated access token. Ledgeren skal ligge under `Program Files`, og directory-chainens native owner/DACL må kun give write/control til de allerede trusted host-admin principals (`SYSTEM`, `Administrators`, `TrustedInstaller`).

Ledgeren oprettes **ikke** automatisk som service-user state. Manglende, ikke-pre-provisioned, linket, forkert ejet eller for bredt writable host-state fejler lukket før reservationstransaktionen starter.

Denne boundary gør replay-state rollback-resistent over for ordinary/non-admin service-principals. Den påstår bevidst **ikke** modstand mod kompromitteret root/host-administrator: en principal, der allerede kontrollerer trust-root, protected runtime og den administrative ledger, ligger uden for `host_replay_guard_committed`-garantien. Reservation-schemaet beskriver samme afgrænsning machine-readable og holder `global_replay_safe=false`.

Den private underscored test-seam kan fortsat bruge caller-valgte midlertidige ledgers til deterministiske regressions; det giver ingen production authority.

### 5. Replay-marker kommer før authority-bearing main-observation

Et trusted preflight-read må afvise en åbenlyst forkert request uden at brænde den. Den authority-bærende observation sker først efter create-once reservation.

Replay-markeren er permanent host-local replay-state. Den oprettes med `O_CREAT|O_EXCL`, skrives og fsync'es, parent directory persisteres, og den oprindelige publication-descriptor/fil-identitet beholdes. Descriptoren genåbnes ikke senere for at vælge provenance-baseline.

Efter markerens oprettelse læses præcis `refs/heads/main^{commit}` igen gennem den host-admin-kontrollerede, snapshot-pinnede production Git-reader.

Hvis `main` flytter, trusted Git fejler eller requesten senere viser sig udløbet, er requesten stadig host-lokalt consumed/recovery-required. Replay-markeren rulles ikke tilbage af transactionen.

### 6. Trusted time og signatur re-verificeres efter marker

Production clock afledes internt. Caller kan ikke levere eller backdate consumption time.

Efter replay-marker og post-marker `main` read re-verificeres signed request + qualification ved et nyt current-time timestamp mod den host-resolved/snapshottede verifier. Expiry eller signature/keyring mismatch fejler lukket og efterlader requesten consumed/recovery-required.

### 7. Durable bytes er recovery-state; live provenance er process- og historie-bundet

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

File-descriptor provenance og directory-history provenance deler én process-local re-entrant registry lock. Registration, live authentication, weakref cleanup, transaction revocation og retained-publication cleanup kan derfor ikke mutere de to authority-registries samtidigt eller skabe et stale-true vindue mellem file- og directory-evidence. Registry entries detach'es atomisk under låsen; descriptors/history handles lukkes efter detach. Fork-child erstatter det arvede lock før cleanup.

#### Linux directory-chain event-history og watch-before-trust

Fil-identitet på final/marker og ledger-root alene fanger ikke, at en **ancestor** til ledger-rooten kan rename's og senere sættes tilbage: ledger-child inode/bytes/ctime kan da forblive uændret, selv om canonical ledger-path midlertidigt pegede et andet sted og tillod replay.

Fra **før den første permanente publication** bindes derfor ledger-rooten og hele dens eksisterende ancestry til kernel-event history. På Linux sker setup i denne rækkefølge:

1. den canonical path-kæde beregnes;
2. én inotify-instance armerer parent-directory watches for hvert ancestry-led **før directory-identiteter accepteres som trusted provenance**;
3. directory descriptors + `(dev, ino)` captures;
4. queued history drænes;
5. canonical path-identiteter re-verificeres mod de retained descriptors;
6. kernel-history drænes **igen efter identity-validation**, før bindingen må returnere true eller første permanente publication fortsætte.

Det samme dobbeltcheck gælder ved hver senere live `transaction_authenticated`-validering: en relevant event, der bliver queued efter det første drain men mens ancestry-stat-checket kører, skal observeres af post-validation-drainet og revokere bindingen før `true` kan returneres.

Linux-monitoren filtrerer hvert parent-watch på det præcise beskyttede child-navn. `MOVED_FROM`, `MOVED_TO`, `CREATE` eller `DELETE` for dette navn samt parent `MOVE_SELF`/`DELETE_SELF`/`UNMOUNT`, `IN_IGNORED` eller queue overflow er monotont history failure. Oprettelse/sletning af **andre sibling entries** revokerer derimod ikke en ellers uændret reservation.

Det eksisterende setup-only metadata-stamp check (`ctime_ns`, hvor tilgængeligt) bevares som defense-in-depth i den lavere provenance-implementation, men production-sikkerheden på Linux afhænger ikke af, at en rename nødvendigvis giver en unik timestamp. Regressionerne neutraliserer metadata-stampen og kræver stadig, at `rename→restore` efter watch-arming fejler på queued inotify-history alene, og injicerer desuden `rename→restore` præcis mellem første history-drain og ancestry-stat-validation for at bevise, at post-validation-drainet afviser før et stale `true`.

BSD-style kqueue kræver et target descriptor før vnode-filteret kan registreres og kan derfor ikke levere samme watch-before-trust egenskab. Den public production facade fejler derfor aktuelt lukket på **non-Linux POSIX** i stedet for at påstå exact race-free directory-history setup. Den lavere private provenance-implementation kan fortsat indeholde kqueue-kode til isolation/eksperimenter, men den udgør ikke production authority.

Både `ledger rename-away → replay → restore` og `ancestor rename-away → replay i replacement subtree → delete replacement → restore ancestor` efter monitor-arming efterlader history, som ikke kan skjules ved at sætte de oprindelige pathnames tilbage.

Der påstås ikke tilsvarende Windows inotify/kqueue semantics; Windows authority er afgrænset af de separate native owner/DACL-, elevated-operator- og file-provenance guarantees i denne ADR.

### 8. Replay-scope er eksplicit host-local

Et schema-validt reservation receipt bevarer mindst:

- `ledger_scope=canonical-host-local-v1`;
- `main_head_match_confirmed=true`;
- `request_consumed=true`;
- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

`host_replay_guard_committed=true` betyder, at create-once-markeren blev durably committed i den canonical host-admin-kontrollerede ledger under en elevated production consume. Det betyder **ikke** host-admin/root-compromise resistance og heller ikke distribueret/global one-time use.

Public production-pathen eksponerer ingen ledger-selector og kræver den elevated operator + protected ledger boundary ovenfor. Private test-ledgers ændrer aldrig `global_replay_safe=false`.

En senere campaign-admission boundary skal binde den faktiske physical host/runner og må ikke bruge reloadede ledger-bytes eller process-arvede receipts som execution authority.

### 9. Reservationen stopper før fysisk execution

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
2. kræv elevated host-operator context og resolve/host-control-validér den fixed canonical replay-ledger; ordinary service-user state accepteres ikke;
3. snapshot exact-type request/qualification/snapshot/signature + verifier;
4. rekonstruér exact `TrustedGitRuntime`, verificér signed runtime identity og host-admin-control af tree + chain;
5. trusted preflight af `main` gennem den restricted host-controlled Git-reader, som launcher den attesterede Git executable direkte og ikke relauncher ModelRig package-source som Linux supervisor;
6. opret transaction/publication token; på Linux arm exact ancestry parent-watches **før** directory-identiteter captures, dræn history, validér ledger-root + ancestors, og dræn history igen før første permanente publication; non-Linux POSIX fejler lukket;
7. create-once permanent replay-marker og behold original descriptor/fil-identitet;
8. trusted post-marker `main` read gennem samme host-controlled direct Git path;
9. trusted-current-time re-verifikation af signed request + qualification;
10. create-once pending payload;
11. create-once final canonical payload; behold original descriptor/fil-identitet;
12. exact-byte read-back + canonical parse uden authority grant;
13. cleanup kun pending; replay-marker bevares;
14. claim original final + marker publication descriptors fra samme transaction-token;
15. registrér exact live receipt med process/content/file provenance og, på Linux, watch-before-trust directory-chain event-history binding med pre- og post-identity history drain;
16. ved enhver outer exception: revokér registered provenance, frigiv unclaimed descriptors/history monitors og propagér derefter fejlen.

Hvis noget fejler efter replay-markerens publication, kan requesten ikke genbruges gennem den normale production consume på samme canonical host-ledger uden en separat eksplicit host-admin recovery/tamper-handling. En kompromitteret host-admin/root principal er eksplicit uden for denne receipts replay-garanti.

## Fail-closed krav

Implementationen skal mindst afvise eller fail-close ved:

1. caller-supplied verifier/keyring/trust root i public consume;
2. manglende/malformed/wrong-domain/non-canonical/unsafe host keyring;
3. POSIX keyring ownership/mode-brud eller Windows owner/DACL med ikke-admin write/control;
4. production replay consume uden elevated host-operator context;
5. manglende, ikke-pre-provisioned, linked, forkert ejet, group/world-writable eller ACL-udvidet POSIX replay-ledger chain;
6. Windows replay-ledger uden for Program Files eller med unsafe owner/DACL;
7. forkert issuer-system eller stale minimum keyring epoch;
8. packaged/non-underscored verifier-taking compatibility route eller traversal til private verifier-injection;
9. forged observation, caller clock eller caller authority-path;
10. subclasses/overridable authority-inputs eller `TrustedGitRuntime`;
11. caller mutation af signed inputs efter snapshot;
12. production runtime, der er service-user-writable eller ikke host-admin-kontrolleret;
13. authority-bearing Linux Git launch, der genlæser ordinary ModelRig package-source som child-side supervisor efter runtime-attestation;
14. runtime manifest/executable mismatch mod signed `CandidateSnapshotReceipt`;
15. malformed/wrong `main` SHA eller drift mellem preflight og post-marker read;
16. expired/invalid signed request efter replay-marker;
17. duplicate consume eller crash-left marker/pending/final state;
18. direct/prebuilt/fabricated final persistence;
19. non-canonical/non-identical final read-back;
20. byte-identisk eller ændret final/marker replacement før registration;
21. missing/mismatched original publication descriptor ved claim;
22. final/marker tamper efter registration;
23. delete→byte-identical recreate af final/marker;
24. POSIX leaf rename-away/replay/rename-back;
25. Linux ledger-root eller ancestor rename-away/replay/restore, monitor loss eller relevant queued ancestry-event;
26. relevant inotify-event queued under ancestry identity-validation efter det første history-drain;
27. production på non-Linux POSIX, hvor exact watch-before-trust directory-history setup ikke kan bevises;
28. live receipt mutation uden exact content restoration;
29. POSIX fork inheritance;
30. cross-transaction descriptor/history-monitor claim eller leaked retained state;
31. outer consume/cleanup failure, der ellers ville efterlade traceback-reachable authenticated receipt;
32. concurrent registry mutation, der ellers kunne give stale-true eller iteration failure under revocation/cleanup;
33. ethvert forsøg på at hæve host-admin-compromise resistance, global replay-, freeze-, campaign-, pilot-, publication- eller activation-authority ud over receiptets eksplicitte scope.

## Artefakter

- `kaliv-rsi-physical-request-authority-keyring/v1` — host-kontrolleret verification-only trust root;
- `kaliv-rsi-local-main-head-observation/v1` — parsebar evidence-only observation;
- `kaliv-rsi-physical-qualification-reservation/v1` — canonical host-local replay/evidence data med eksplicit ikke-global/non-host-admin-compromise replay-scope;
- `consume_physical_qualification_request_once(...)` — eneste public authority-bearing consume path og en elevated physical host-operator operation;
- fixed pre-provisioned host-admin replay ledger under `/var/lib/modelrig/devcontrol/...` eller `Program Files\ModelRig\DevControl\state\...`;
- admin-controlled production `TrustedGitRuntime` + restricted direct physical Git reader, som launcher kun den attesterede Git executable og ikke en ModelRig package-file supervisor;
- private transaction-staged runtime/ledger seams — deterministic tests only;
- original-publication descriptor registry for final/replay-marker;
- Linux ledger-root + ancestor parent-watches, retained directory descriptors og watch-before-trust kernel event-history med history-drain både før og efter ancestry identity-validation;
- process-local live provenance registry med process/content/file/history binding, shared fork-safe re-entrant registry lock og transaction-token-bound exception revocation.

## Konsekvens

Efter denne boundary kan DevControl bevise, at en human-signed request blev verificeret mod en caller-uafhængig host-pinned trust root, at reservationen blev udført af en elevated physical host-operator mod en pre-provisioned host-admin-kontrolleret replay-ledger, at requesten matchede den signerede software/runtime chain, at det ønskede `main` blev observeret gennem en host-admin-kontrolleret runtime efter permanent host reservation uden at authority-pathen genindlæste ordinary ModelRig package-source som process-supervisor, og at transactionen producerede et live process-bound receipt, hvis provenance er bundet til de oprindelige durable publications og — på Linux — den canonical ledger-paths monotone watch-before-trust directory-chain event history med et afsluttende history-drain efter ancestry identity-validation.

Det beviser fortsat **ikke** replay-resistance mod kompromitteret host-admin/root, global/distribueret replay-sikkerhed, persistent frozen `main`, fysisk campaign completion, pilot-GO, publication eller activation. De authority-led forbliver åbne og kræver separate senere boundaries.