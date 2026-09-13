# ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. Signaturen betyder kun, at en identificeret menneskelig authority har anmodet om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke frozen `main`, starter ingen probes og giver ingen pilot-, publication- eller activation-authority.

Reservation-laget skal være sandfærdigt om fem forskellige authority-problemer:

1. **trust root** — caller må ikke vælge Ed25519-keyringen, der afgør om callerens egen signatur er trusted;
2. **runtime** — den Git-executable, der producerer authority-evidence, må ikke kunne udskiftes af den ordinary service-principal;
3. **observation target** — et host-attesteret Git-binærprogram må heller ikke læse `main` fra caller-writable Git metadata;
4. **time/replay** — caller må ikke backdate consumption eller genbruge samme request gennem production consume, og replay-state må ikke kunne rulles tilbage af den principal, guard'en skal beskytte imod;
5. **provenance** — persisted bytes, byte-identiske replacements eller rename/replay/restore må ikke kunne mint'e eller genoplive live authority.

En lokal filesystem-ledger kan kun etablere host-local replay/recovery-state. Den kan ikke bevise distribueret/global one-time use, og den giver ingen garanti mod en kompromitteret root/host-administrator. Derfor er `global_replay_safe=false`, og en senere fysisk campaign-admission/frozen-main boundary er fortsat nødvendig.

## Beslutning

Production authority-sekvensen er:

`host-pinned request trust root → elevated host operator + host-admin replay ledger → exact caller snapshots → host-admin-controlled signed Git runtime → host-admin-controlled Git metadata target → trusted preflight → permanent create-once replay-marker → trusted post-marker main read → current-time signed-chain reverify → create-once final → exact read-back → original-publication file provenance + Linux watch-before-trust directory history → transaction-authenticated in-memory receipt`

### 1. Public consume må ikke acceptere caller-valgt authority

Den eneste public authority-bearing path er:

`consume_physical_qualification_request_once(...)`

Caller-input er begrænset til exact `TrustedGitRuntime`, `PhysicalQualificationRequest`, `QualificationPacket`, `CandidateSnapshotReceipt` og `DetachedEd25519AuthoritySignature`.

Public API accepterer **ikke** verifier/keyring, observation, clock/`consumed_at_utc`, ledger-root/ID, repository-root, operation-root eller prebuilt reservation receipt.

Production resolver verification-only Ed25519-keyringen fra fast host-state:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-physical-request-authority-keyring-v1.json`;
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-physical-request-authority-keyring-v1.json`.

Keyringen skal være canonical, link-free, size-bounded, have schema `kaliv-rsi-physical-request-authority-keyring/v1`, korrekt authority-domain, korrekt issuer-system og gyldigt minimum keyring epoch. Der findes ingen fallback til caller-key, generated key, private-key loader, signing eller network lookup.

Host-control valideres platformsspecifikt:

- POSIX: keyring + directory-chain skal være root-owned, uden group/world-write og uden extended POSIX access/default ACLs;
- Windows: native owner/DACL på fil + directory-chain må kun give write/control til trusted host-admin principals.

Manglende, malformed, wrong-domain eller unsafe trust-state fejler lukket. Verifier-injection findes kun i en underscored/private deterministic test-seam. Det tidligere non-underscored compatibility-modul er fjernet.

Beslutningen påstår ikke isolation mod vilkårligt kompromitteret kode, der allerede kører i samme Python-proces. Production entrypointets kontrakt er, at caller ikke kan vælge trust-root eller andre authority-inputs.

### 2. Caller-ejede authority-objekter snapshots før brug

Før første authority-beslutning rekonstrueres request, qualification, snapshot receipt og detached signature til exact-type canonical lokale snapshots. Den host-resolved verifier rekonstrueres tilsvarende fra exact trusted-key values og minimum keyring epoch. Subclasses afvises.

Transactionen bruger derefter kun snapshots. Caller-mutation via fx `object.__setattr__` kan derfor ikke ændre den signerede chain eller de digests, som receiptet bygges fra efter verification.

### 3. Production Git-runtime skal være host-admin-kontrolleret

`TrustedGitRuntime` skal være exact type, og dens manifest/executable identity skal matche den `CandidateSnapshotReceipt`, der allerede er bundet af qualification-kæden.

Production må ikke eksekvere fra en same-user transaction-copy, selv hvis den er mode `0700`. Public consume kræver:

- POSIX: hele runtime-treeet + ancestor-chain skal være root-owned, uden group/world-write og uden extended POSIX ACLs;
- Windows: runtime skal ligge under `Program Files`, og runtime-tree + directory-chain skal have native owner/DACL-evidence, hvor write/control kun tilkommer trusted host-admin principals.

En ordinary service-user-owned runtime er ikke production authority og fejler lukket.

Production Git-reader understøtter kun `rev-parse --verify refs/heads/main^{commit}`. Den bruger ingen shell og et hardened environment uden caller-writable home/config/hooks/temp state. Authority-pathen launcher præcis den host-attesterede Git executable direkte gennem den allerede indlæste stdlib process primitive; den relauncher **ikke** den generelle `bounded_subprocess.py` supervisor fra ordinary package storage efter runtime-attestation. Processen har separat process-group/session, bounded output, timeout og fail-closed nonzero/timeout/output-overflow. Runtime-treeet re-attesteres efter execution.

Den private deterministic test-seam må fortsat bruge transaction-private runtime staging og den generelle subprocess-infrastruktur. Det er test-/general-infrastruktur, ikke production authority.

### 4. Repository-targetet er en separat host-control boundary

En trusted Git executable er ikke nok, hvis dens `cwd/.git` kan omskrives af samme service-bruger under authority-readet. Production readeren kræver derfor et host-admin-kontrolleret observation target både før process-start og igen efter Git-processen er færdig.

På POSIX kræves:

- checkout-rooten og hele dens ancestor-chain er root-owned, uden group/world-write og uden extended POSIX ACLs;
- `.git` er en rigtig directory, ikke et link/redirect;
- hele `.git`-treeet er root-owned, uden group/world-write og uden extended POSIX ACLs.

På Windows kræves:

- checkout-rooten ligger under `Program Files`;
- checkout-root, `.git`-tree og ancestor-chain har native owner/DACL-evidence med write/control kun til trusted host-admin principals.

Repository-layouts, der kan sende Git authority-readet ud i ikke-attesteret state, fejler lukket. Denne revision afviser derfor mindst:

- `.git/commondir` / linked-common Git directories;
- `.git/objects/info/alternates` / external object stores;
- local Git config med `[include]` eller `[includeIf ...]`;
- non-canonical/ulæselig Git config eller unsupported host-control platform.

Denne boundary beskytter **Git metadata-observationen**, ikke hele worktreeet. Tracked worktree bytes erklæres ikke frozen af ADR-DC-009. `main_head_match_confirmed=true` betyder kun, at den beskyttede Git metadata-state producerede den forventede commit ved reservationstidspunktet. `frozen_main_confirmed` forbliver `false`.

### 5. Production replay-state er en elevated host-operator boundary

Live provenance kan opdage tamper, mens et receipt eksisterer, men kan ikke gøre et service-user-writable directory rollback-sikkert mellem processer eller efter restart. Production replay-ledgeren må derfor ikke ejes af eller være writable gennem den almindelige ModelRig service-identitet.

Public production resolver præcis én fast, pre-provisioned ledger:

- POSIX: `/var/lib/modelrig/devcontrol/rsi-physical-request-ledger-v1`;
- Windows: `C:\Program Files\ModelRig\DevControl\state\rsi-physical-request-ledger-v1`.

Consume-operationen er en **fysisk host-operator handling**, ikke produkt-runtime:

- POSIX kræver effektiv UID 0; ledger + hele ancestor-chain skal være root-owned, link-free, uden group/world-write og uden extended POSIX access/default ACLs;
- Windows kræver elevated token; ledgeren ligger under `Program Files`, og native owner/DACL må kun give write/control til trusted host-admin principals.

Ledgeren oprettes ikke automatisk som service-user state. Manglende, ikke-pre-provisioned, linked, forkert ejet eller for bredt writable host-state fejler lukket før reservationstransaktionen starter.

Denne boundary gør replay-state rollback-resistent over for ordinary/non-admin service-principals. Den påstår bevidst **ikke** modstand mod kompromitteret root/host-administrator. En principal, der kontrollerer trust-root, protected runtime, protected Git metadata og replay-ledger, ligger uden for `host_replay_guard_committed`-garantien.

### 6. Replay-marker kommer før authority-bearing main-observation

Et trusted preflight-read må afvise en åbenlyst forkert request uden at brænde den. Den authority-bærende observation sker først efter create-once reservation.

Replay-markeren er permanent host-local replay-state. Den oprettes med `O_CREAT|O_EXCL`, skrives og fsync'es, parent directory persisteres, og den oprindelige publication-descriptor/fil-identitet beholdes.

Efter markerens oprettelse læses præcis `refs/heads/main^{commit}` igen gennem den host-admin-kontrollerede Git-runtime **mod det host-admin-kontrollerede repository metadata-target**.

Hvis `main` flytter, repository/runtime attestation fejler, trusted Git fejler eller requesten senere viser sig udløbet, er requesten stadig host-lokalt consumed/recovery-required. Replay-markeren rulles ikke tilbage af transactionen.

### 7. Trusted time og signatur re-verificeres efter marker

Production clock afledes internt. Caller kan ikke levere eller backdate consumption time.

Efter replay-marker og post-marker `main` read re-verificeres signed request + qualification ved et nyt current-time timestamp mod den host-resolved/snapshottede verifier. Expiry eller signature/keyring mismatch fejler lukket og efterlader requesten consumed/recovery-required.

### 8. Durable bytes er recovery-state; live provenance er process- og historie-bundet

Canonical final/pending/replay-marker bytes er ikke reloadable authority:

- `PhysicalQualificationReservation.from_mapping(...)` og ledger reload giver aldrig transaction provenance;
- `transaction_authenticated` serialiseres ikke;
- direct filesystem forgery kan højst skabe replay/DoS/recovery-state.

Permanent replay-marker og final receipt publiceres create-once og beholder de **oprindelige descriptors/handles fra selve `O_CREAT|O_EXCL` publicationen**. Final read-back skal være byte-identisk med transactionens payload, men et senere path-open må aldrig definere authority-baselinen.

Registration claim'er de oprindelige final + replay-marker descriptors fra samme transaction-token og binder live provenance til exact receipt object identity, originating PID, canonical receipt SHA-256, exact bytes samt original fil-identitet og metadata-stamp.

Konsekvenser:

- byte-identisk inode replacement før registration kan ikke blive ny baseline;
- unlink/replacement/delete→byte-identical recreate efter registration kan ikke genoplive receiptet;
- POSIX leaf rename-away/replay/rename-back ændrer retained metadata-stamp; observeret durable mismatch revokerer live provenance permanent;
- receipt-object mutation giver midlertidigt `transaction_authenticated=false`; exact restoration af original content kan blive valid igen, hvis durable provenance aldrig har mismatchet;
- fork-child arver ingen authority;
- enhver exception fra outer consume revokerer transaction-token-bound provenance før exceptionen bliver caller-visible.

File-descriptor provenance og directory-history provenance deler én process-local re-entrant registry lock. Registry state kan derfor ikke blive stale-true på grund af concurrent registration/revocation/weakref cleanup. Production replay-ledgerens separate host-admin boundary er det, der forhindrer ordinary service-principals i at udføre filesystem-races mod markerne.

#### Linux directory-chain event-history og watch-before-trust

Fil-identitet på final/marker og ledger-root alene fanger ikke en ancestor rename/replay/restore. Derfor bindes ledger-rooten og hele dens eksisterende ancestry til kernel-event history **før første permanente publication**.

På Linux sker setup i denne rækkefølge:

1. canonical ledger path-chain beregnes;
2. én inotify-instance armerer parent-directory watches for hvert beskyttet ancestry-led **før directory-identiteter accepteres som trusted provenance**;
3. directory descriptors + `(dev, ino)` captures;
4. queued history drænes;
5. canonical path-identiteter re-verificeres;
6. kernel-history drænes **igen efter identity-validation**, før bindingen må returnere true eller publication fortsætte.

Det samme pre/post-history check gælder ved senere live `transaction_authenticated`-validering. Relevant `MOVED_FROM`, `MOVED_TO`, `CREATE`, `DELETE`, parent self-move/delete/unmount, ignored watch eller queue overflow revokerer monotont. Unrelated sibling churn ignoreres.

Setup-only metadata stamps bevares som defense-in-depth, men Linux production-sikkerheden afhænger ikke af timestamp-unikhed. Regressions dækker bl.a. whole-ledger replay/restore, ancestor replay/restore, constant-metadata watch-before-trust og rename→restore præcis mellem første history-drain og ancestry-stat-validation.

BSD-style kqueue kan ikke etablere samme exact watch-before-trust guarantee før descriptor capture. Public production fejler derfor aktuelt lukket på **non-Linux POSIX** frem for at overclaim'e race-free semantics. Windows er afgrænset af native owner/DACL-, elevated-operator- og file-provenance guarantees og påstår ikke inotify-semantik.

### 9. Replay-scope er eksplicit host-local

Et schema-validt reservation receipt bevarer mindst:

- `ledger_scope=canonical-host-local-v1`;
- `main_head_match_confirmed=true`;
- `request_consumed=true`;
- `host_replay_guard_committed=true`;
- `global_replay_safe=false`.

`host_replay_guard_committed=true` betyder, at create-once-markeren blev durably committed i den canonical host-admin-kontrollerede ledger under en elevated production consume. Det betyder ikke host-admin/root-compromise resistance og heller ikke distribueret/global one-time use.

En senere campaign-admission boundary skal binde den faktiske physical host/runner og må ikke bruge reloadede ledger-bytes eller process-arvede receipts som execution authority.

### 10. Reservationen stopper før fysisk execution

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

1. resolve og host-control-validér request-authority keyring/verifier, inkl. POSIX ACL-state;
2. kræv elevated host-operator context og host-control-validér fixed canonical replay-ledger;
3. snapshot exact-type request/qualification/snapshot/signature + verifier;
4. rekonstruér exact `TrustedGitRuntime`, verificér signed runtime identity og host-admin-control af runtime tree + chain, inkl. POSIX ACL-state;
5. host-control-validér repository root/ancestor chain + hele `.git` metadata-treeet; afvis external Git metadata redirects;
6. trusted preflight af `main` gennem den restricted direct host-controlled Git-reader;
7. opret transaction/publication token; på Linux arm ancestry watches før ledger directory-identiteter accepteres;
8. create-once permanent replay-marker og behold original publication descriptor/identity;
9. re-attestér repository target + runtime, udfør trusted post-marker `main` read, og re-attestér begge efter read;
10. trusted-current-time re-verifikation af signed request + qualification;
11. create-once pending payload;
12. create-once final canonical payload; behold original publication descriptor/identity;
13. exact-byte read-back + canonical parse uden authority grant;
14. cleanup kun pending; replay-marker bevares;
15. claim original final + marker publication descriptors fra samme transaction-token;
16. registrér exact live receipt med process/content/file provenance og, på Linux, watch-before-trust directory-chain history;
17. ved enhver outer exception: revokér registered provenance, frigiv unclaimed descriptors/history monitors og propagér derefter fejlen.

Hvis noget fejler efter replay-markerens publication, kan requesten ikke genbruges gennem normal production consume på samme canonical host-ledger uden separat eksplicit host-admin recovery/tamper-handling.

## Fail-closed krav

Implementationen skal mindst afvise eller fail-close ved:

1. caller-supplied verifier/keyring/trust root, observation, clock eller authority-path i public consume;
2. manglende/malformed/wrong-domain/non-canonical host keyring;
3. POSIX keyring/runtime/repository state, der er forkert ejet, group/world-writable eller har extended POSIX ACLs;
4. Windows keyring/runtime/repository state med unsafe owner/DACL eller uden for den krævede Program Files boundary;
5. packaged/non-underscored verifier-taking compatibility route eller traversal til private verifier-injection;
6. subclasses/overridable authority-inputs eller `TrustedGitRuntime`;
7. caller mutation af signed inputs efter snapshot;
8. runtime manifest/executable mismatch mod signed `CandidateSnapshotReceipt`;
9. production runtime, der er service-user-writable;
10. repository root/ancestor chain eller `.git` metadata-tree, der er service-user-writable eller ikke host-admin-kontrolleret;
11. `.git/commondir`, external object alternates eller local config include/includeIf, som kan redirecte authority-readet ud af attesteret state;
12. production replay consume uden elevated host-operator context;
13. unsafe/missing/non-pre-provisioned replay-ledger;
14. malformed/wrong `main` SHA eller drift mellem preflight og post-marker read;
15. expired/invalid signed request efter replay-marker;
16. duplicate consume eller crash-left marker/pending/final state;
17. direct/prebuilt/fabricated final persistence eller reload som authority;
18. non-canonical/non-identical final read-back;
19. replacement/tamper/delete/recreate af final eller marker;
20. missing/mismatched original publication descriptor;
21. POSIX leaf rename-away/replay/restore;
22. Linux ledger-root/ancestor rename/replay/restore, relevant queued event, monitor loss eller overflow;
23. production på non-Linux POSIX, hvor exact watch-before-trust history setup ikke kan bevises;
24. live receipt mutation uden exact content restoration;
25. POSIX fork inheritance;
26. cross-transaction descriptor/history-monitor claim eller leaked retained state;
27. outer consume/cleanup failure, der ellers ville efterlade traceback-reachable authenticated receipt;
28. concurrent registry mutation, der ellers kunne skabe stale-true authority;
29. ethvert forsøg på at hæve `main_head_match_confirmed` til persistent frozen-main, global replay, campaign-start, pilot, publication eller activation authority.

## Artefakter

- `kaliv-rsi-physical-request-authority-keyring/v1` — host-kontrolleret verification-only trust root;
- `kaliv-rsi-local-main-head-observation/v1` — parsebar evidence-only observation;
- `kaliv-rsi-physical-qualification-reservation/v1` — canonical host-local replay/evidence data med eksplicit ikke-global replay-scope;
- `consume_physical_qualification_request_once(...)` — eneste public authority-bearing consume path og en elevated physical host-operator operation;
- fixed pre-provisioned host-admin replay-ledger;
- admin-controlled production `TrustedGitRuntime` + restricted direct Git reader;
- admin-controlled checkout identity + `.git` metadata target uden external Git redirects;
- private transaction-staged runtime/ledger seams — deterministic tests only;
- original-publication descriptor registry for final/replay-marker;
- Linux ledger-root + ancestor parent-watches og watch-before-trust event-history;
- process-local live provenance registry med process/content/file/history binding, shared fork-safe RLock og transaction-token exception revocation.

## Konsekvens

Efter denne boundary kan DevControl bevise, at en human-signed request blev verificeret mod en caller-uafhængig host-pinned trust root; at reservationen blev udført af en elevated physical host-operator mod en pre-provisioned host-admin replay-ledger; at den signerede Git-runtime ikke var ordinary-service-writable; at den authority-bærende `main`-observation blev udført mod host-admin-kontrolleret Git metadata uden external redirects; og at transactionen producerede et live process-bound receipt bundet til de oprindelige durable publications og Linux directory-history.

Det beviser fortsat **ikke** host-admin/root-compromise resistance, global/distribueret replay-sikkerhed, trusted worktree contents, persistent frozen `main`, fysisk campaign completion, pilot-GO, publication eller activation. De authority-led forbliver åbne og kræver separate senere boundaries.