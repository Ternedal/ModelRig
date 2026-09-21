# ADR-DC-010 — Authenticated one-shot admission før DC-L15 physical campaign

**Dato:** 13/09-2026  
**Status:** foreslået til beslutning  
**Beslutningsejer:** Anders  
**Afhænger af:** ADR-DC-001, ADR-DC-007, ADR-DC-008 og ADR-DC-009

## Problem

ADR-DC-009 kan returnere én in-memory `PhysicalQualificationReservation`, som
beviser, at den human-signerede request netop blev autentificeret og host-lokalt
forbrugt gennem den canonical replay-ledger. Persisted reservation-bytes er med
vilje **ikke** authority: deserialisering genetablerer ikke
`transaction_authenticated`.

Det næste led må derfor ikke gøre en schema-valid receipt til execution authority.
Det skal både bevare ADR-DC-009's transaction provenance og navngive de konkrete
runner-bytes, som et menneske faktisk tillader at starte en DC-L15-kampagne med.

Repoet har physical-report/verifier-kontrakten, men ingen autoritativ production-
runner for de elleve I0b-probes. En caller-supplied runner-label, filsti,
verification keyring, same-user Git runtime eller reloadet ledger-receipt ville
derfor være falsk provenance.

## Beslutning

Der indføres to artifacts:

1. `kaliv-rsi-physical-campaign-runner-authorization/v1` — et kortlivet payload,
   som en separat human Ed25519 authority signerer;
2. `kaliv-rsi-physical-campaign-admission/v1` — et host-lokalt create-once
   admission-artifact, som først mintes efter post-lock re-verifikation.

Admissionen er kun en smal starttilladelse til én manuel fysisk kampagne. Den
udfører ingen probe og giver ingen publication-, merge-, release-, deploy- eller
activation-authority.

### 1. Parent-reservation skal stadig være transaction-authenticated

Den authority-bærende admission-path accepterer kun det **samme in-memory
reservation-objekt**, som ADR-DC-009 returnerede efter successful authenticated
consume. `PhysicalQualificationReservation.from_mapping(...)` eller ledger
`load()` kan aldrig løftes til campaign-start, selv når bytes og hashes er
identiske.

Qualification packet og `CandidateSnapshotReceipt` bindes igen til reservationen,
inklusive candidate/task og Trusted-Git runtime identity. Reservationens live
provenance re-verificeres både før admission-locken og umiddelbart før final
commit. Hvis ADR-DC-009's final receipt, permanente replay marker eller live
provenance mister autenticitet undervejs, fejler admissionen lukket.

### 2. Human-signeret exact runner-pin med host-kontrolleret trust root

Runner-authorization binder mindst:

- reservation SHA-256 og host-local scope digest;
- request-, qualification- og snapshot-digests;
- campaign ID, proposal/task/repository/base SHA og human-requested main SHA;
- repo-relativ runner-path, exact runner SHA-256 og byte count;
- requestens collector som required operator og dens separate approver;
- `kaliv-windows-isolation-physical-report/v1`;
- `os_isolated` + `network=deny`;
- hele det eksakte eksisterende 11-probe `REQUIRED_PROBES`-univers;
- kort `authorized_at`/`expires_at` vindue, højst 15 minutter;
- `automatic_start=false` og ingen pilot/publication/activation authority.

Signaturen skal komme fra authority-system
`kaliv-rsi-dc-l15-runner-authority-v1`. En korrekt Ed25519-signatur fra et andet
system er ikke tilstrækkelig.

Production må ikke lade calleren vælge public-key trust. Verifieren resolver fra
én fast verification-only runner-keyring:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-physical-campaign-runner-authority-keyring-v1.json`
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-physical-campaign-runner-authority-keyring-v1.json`

Keyringen har schema
`kaliv-rsi-physical-campaign-runner-authority-keyring/v1`, authority-domain
`rsi-dc-l15-physical-campaign-runner`, exact issuer-system og monoton minimum
keyring epoch. Den genbruger ADR-DC-009's host-control policy: POSIX kræver
root-owned/non-group-world-writable file + directory chain; Windows kræver
Program Files samt owner/DACL uden ordinary/broad write/control authority.

Det historiske public `verifier`-argument er kun en fail-closed compatibility
surface: enhver non-`None` værdi afvises. Den private underscored transaction kan
fortsat injicere verifier til deterministiske adversarial tests; det er ikke
production authority.

### 3. Public admission-path udleder sin egen provenance

`issue_physical_campaign_admission_once(...)` må ikke acceptere caller-supplied:

- trusted runner verification keyring;
- main-observation eller wall-clock timestamp;
- ledger root, repository root eller Git operation root;
- campaign ID/operator actor uden for den signerede authorization;
- runner path/hash/bytes uden for det signerede payload;
- prebuilt admission receipt.

Den udleder canonical host/repository paths internt og bruger current time.
Caller-ejede qualification/snapshot/runner-authorization/signature-data kopieres
til exact-type canonical value snapshots. Authority-subclasses afvises.

### 4. Production Trusted Git er host-admin-kontrolleret

Callerens `TrustedGitRuntime` skal være exact type og være den host-admin-
kontrollerede runtime-model, som ADR-DC-009 kræver i production. Production
kopierer ikke executable/runtime bytes til en same-user `0700` staging-root.

Runtime-tree og ancestor chain re-valideres før/efter reads, og
`refs/heads/main^{commit}` køres direkte gennem den restricted host-controlled
Git reader med no-shell, bounded output, disabled hooks/config/network protocols
og uden caller-kontrolleret mutable Git state.

Den private underscored deterministic test-seam beholder transaction-private
staging, så race- og failure-tests kan bruge syntetiske runtimes uden at blive
forvekslet med production authority. Production skaber kun en tom disposable
cleanup-sentinel under operation-state; executable bytes kopieres ikke dertil.

### 5. Frisk pre-start main + exact runner bytes

Før admission-locken:

1. runner-signaturen verificeres mod current time og host trust-root;
2. `refs/heads/main^{commit}` genlæses gennem host-controlled Trusted Git;
3. observationen skal matche requestens main SHA, repository-root og samme
   Git-runtime/executable identity;
4. reservationen må højst være 15 minutter gammel;
5. main-observationen må højst være ét minut gammel;
6. runner-filen åbnes gennem den eksisterende stabile, link-frie bounded-read
   boundary og skal matche exact SHA-256 + byte count.

Admissionens runner-budget er højst 16.000.000 bytes og udvider ikke den
etablerede reader-boundary.

Derefter tages en create-once admission-lock. Efter lock gentages main-read,
runner-hash, runner-signatur-verifikation og parent-reservationens live provenance.
Hvis main flytter, runneren ændres, authorization udløber eller parent-provenance
svigter efter lock, forbliver admissionen host-lokalt consumed/recovery-required;
den må ikke blive genbrugelig.

## Original-publication provenance er authority-bærende

Admission-ledgeren følger samme sikkerhedsmodel som ADR-DC-009. Final receipt og
permanent replay marker publiceres gennem `O_CREAT|O_EXCL`, og deres **oprindelige
publication descriptors/fil-identiteter beholdes frem til provenance-registration**.
Registration må kun claim'e de originaler, som den samme authenticated transaction
netop publicerede. En eksisterende eller senere genoprettet path med de samme bytes
er ikke en erstatning for den originale publication.

Live provenance binder dermed:

1. exact admission-object identity;
2. originating PID;
3. canonical admission SHA-256 ved registrering;
4. exact transaction payload for final receipt og replay marker;
5. de oprindelige file identities/descriptors for begge create-once publications;
6. transaction-tokenet, så en anden transaction ikke kan claim'e publicationen.

File/path mismatch er **monoton**. Unlink/replacement eller delete → byte-identical
recreate kan ikke etablere en ny baseline og kan ikke genoplive en tidligere live
admission. Ren in-memory receipt-mutation er derimod kun midlertidigt invalid, hvis
den eksakte oprindelige værdi gendannes og durable provenance aldrig har svigtet.

Descriptor-, weakref- og live registries bruger samme re-entrant registry lock som
ADR-DC-009. Publication, registration, live check, revocation og fork-cleanup kan
derfor ikke interleave på en måde, der lukker retained descriptors under en anden
authority-check.

## POSIX ledger + ancestor directory-history

File identity alene opdager ikke et skjult whole-ledger
`rename-away → byte-identical replay → restore`, hvis original-pathen er tilbage,
inden næste live check. Derfor arver DC-010 også ADR-DC-009's directory-history
boundary.

På den understøttede Linux production-path armeres inotify-history på den
canonical admission-ledger og hele dens eksisterende ancestor-kæde **før**
directory-identiteter accepteres som provenance. Watches filtreres på exact
protected child-name. Relevant rename/create/delete, parent self-move/delete,
unmount, ignored watch eller queue overflow fejler lukket. Unrelated sibling
churn må fortsat være neutral.

Det lukker både:

- whole-ledger `rename → replacement replay → restore`;
- ancestor `rename → replay i replacement subtree → restore`;
- byte-identisk replay af final + lock under en replacement tree.

Setup-only metadata-stamps er defense-in-depth; authority må ikke baseres på, at
ctime alene tilfældigvis har tilstrækkelig opløsning. Public production på
non-Linux POSIX følger parent-boundaryens fail-closed policy. Der påstås ikke
Windows inotify/kqueue directory-history semantics i denne ADR.

## Transaction failure revokerer authority

Descriptor- og directory-history scopes omslutter hele private issue-transactionen.
Enhver outer exception revokerer allerede registreret live provenance for samme
transaction-token, før traceback kan gøre et in-frame receipt synligt for caller.
Det gælder også cleanup-failure efter durable commit. Unclaimed retained
publication descriptors og directory bindings frigives altid ved scope-exit.

Fork-child nulstiller process-lokale registries/locks og kan ikke arve
`transaction_authenticated=true` fra parent-processen.

## Host-local scope er ikke global maskine-identitet

`host_scope_sha256` binder ADR-DC-009's canonical ledger scope/root,
repository-root, snapshot receipt, Trusted-Git runtime/executable og request SHA.
Det gør authorizationen specifik for den reservation-hostscope, der blev målt.

Det hævdes **ikke**, at dette er en globalt unik hardwareidentitet. Derfor er
`global_replay_safe=false` fortsat et invariant. En separat host-key/attestation
kan senere skærpe distribueret replay, men den må ikke opfindes implicit her.

## Authority

Et successful admission må sætte:

```text
campaign_start_authorized = true
human_runner_pin_verified = true
host_admission_guard_committed = true
manual_operator_required = true
single_campaign_only = true
automatic_start = false
```

Men skal samtidig fastholde:

```text
physical_campaign_completed = false
post_campaign_main_observation_required = true
frozen_main_confirmed = false
global_replay_safe = false
pilot_go_authorized = false
activation_authorized = false
remote_publication_authorized = false
merge_authority = human
authority = single-physical-campaign-start-only
```

Admission-artifactet **starter ikke** runneren. Det er kun den ene smalle
forudsætning en senere, separat operator-invoked execution-boundary må kræve.

## Persisted admission er ikke authority

Create-once ledgeren bruger lock → pending → final → exact-byte read-back →
pending-cleanup. Admission-locken slettes **ikke** efter successful commit; den
bliver den permanente host-lokale replay marker for denne reservation/admission.

`PhysicalCampaignAdmission.from_mapping(...)` og ledger `load()` kan kun genskabe
replay/recovery evidence. De kan ikke rekonstruere retained descriptors,
directory-history, transaction-token eller process-local weakref-registration og
får derfor aldrig `transaction_authenticated=true`.

## Ingen falsk frozen-main påstand

Selv gentagne punktobservationer beviser ikke, at `main` aldrig flyttede sig
mellem målingerne. Derfor forbliver `frozen_main_confirmed=false`.

En senere physical-completion boundary skal kræve en frisk post-campaign
main-observation og binde det faktiske signerede 11-probe report til campaign,
task, collector/approver og runner-pin. Først derefter kan et separat human
pilot-GO overhovedet vurderes.

## Fail-closed krav

Admission skal blandt andet fejle ved:

- deserialiseret/reloadet eller anden ikke-transaction-authenticated reservation;
- parent-reservation hvis final/replay provenance svigter;
- qualification/snapshot/runtime drift;
- overridable `TrustedGitRuntime` eller authority subclasses;
- caller-selected runner verifier/keyring;
- manglende, malformed, wrong-domain, wrong-issuer eller ikke-host-kontrolleret
  production runner-keyring;
- caller-/same-user-writable production Trusted-Git runtime eller unsafe
  runtime ancestor chain;
- fremmed runner authority-system eller signature/payload tamper;
- forkert host scope, campaign/task/base eller actor-binding;
- absolute/traversal/backslash/ADS-lignende runner paths;
- runner byte/hash drift, wrong/stale main eller stale reservation;
- authorization før start eller efter expiry;
- manglende/ændret 11-probe-univers;
- duplicate admission på samme canonical host ledger;
- crash-left pending/lock state;
- final-artifact race replacement før exact-byte read-back;
- final eller replay-marker unlink/replacement/byte-identical recreate;
- whole-ledger rename→replay→restore;
- ancestor rename→replacement-subtree replay→restore;
- directory-history monitor loss/overflow på den understøttede Linux path;
- receipt mutation eller process-fork provenance inheritance;
- outer cleanup failure efter registration;
- forsøg på at serialisere pilot, activation, publication, global replay eller
  continuous-freeze claims ind i admissionen.

## Bevidste ikke-mål

Denne ADR og slice må ikke:

- implementere eller køre den faktiske 11-probe runner;
- kalde Tier-A executor/ToolHost;
- starte baggrundsagent eller cadence;
- kontakte remote Git/GitHub;
- merge, release eller deploye;
- erklære DC-L15 completed;
- udstede DC-L16 pilot-GO;
- aktivere DevControl eller ModelRig.

## Næste led

Efter denne slice er næste manglende led en separat fysisk execution/completion
boundary: en rigtig operator-invoked runner skal forbruge den authenticated
admission, udføre det signerede probe-univers på den navngivne host og producere
et `WindowsIsolationPhysicalReport`, som bindes tilbage til admissionen plus en
frisk post-campaign main-observation. Denne ADR godkender ikke det senere led.
