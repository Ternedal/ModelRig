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

Repoet har i dag physical-report/verifier-kontrakten, men ingen autoritativ
produktion-runner for de elleve I0b-probes. En caller-supplied runner-label eller
filsti ville derfor være falsk provenance.

## Beslutning

Der indføres to artifacts:

1. `kaliv-rsi-physical-campaign-runner-authorization/v1` — et kortlivet payload,
   som en separat human Ed25519 authority signerer;
2. `kaliv-rsi-physical-campaign-admission/v1` — et host-lokalt create-once
   admission-artifact, som først mintes efter post-lock re-verifikation.

### 1. Parent-reservation skal stadig være transaction-authenticated

Den authority-bærende admission-path accepterer kun det **samme in-memory
reservation-objekt**, som ADR-DC-009 returnerede efter successful authenticated
consume. `PhysicalQualificationReservation.from_mapping(...)` kan derfor aldrig
løftes til campaign-start, selv når bytes og hashes er identiske.

Qualification packet og `CandidateSnapshotReceipt` bindes igen til reservationen,
inklusive candidate/task og Trusted-Git runtime identity. Reservationens live
provenance re-verificeres både før admission-locken og igen umiddelbart før final
commit. Hvis ADR-DC-009's final receipt eller permanente replay marker flyttes,
ændres eller forsvinder undervejs, mister parent-reservationen authority og
admissionen failer lukket.

### 2. Human-signeret exact runner-pin

Runner-authorization binder mindst:

- reservation SHA-256;
- host-local scope digest;
- request-, qualification- og snapshot-digests;
- campaign ID;
- proposal/task/repository/base SHA;
- human-requested main SHA;
- repo-relativ runner-path;
- exact runner SHA-256 og byte count;
- requestens collector som required operator;
- requestens separate approver;
- `kaliv-windows-isolation-physical-report/v1`;
- `os_isolated` + `network=deny`;
- hele det eksakte eksisterende 11-probe `REQUIRED_PROBES`-univers;
- kort `authorized_at`/`expires_at` vindue, højst 15 minutter;
- `automatic_start=false` og ingen pilot/publication/activation authority.

Signaturen skal komme fra authority-system
`kaliv-rsi-dc-l15-runner-authority-v1`. En korrekt Ed25519-signatur fra et andet
system er ikke tilstrækkelig.

### 3. Public admission-path udleder sin egen provenance

`issue_physical_campaign_admission_once(...)` må ikke acceptere caller-supplied:

- main-observation;
- wall-clock timestamp;
- ledger root;
- repository root;
- Git operation root;
- campaign ID eller operator actor;
- runner path/hash/bytes uden for det signerede runner-payload;
- prebuilt admission receipt.

Den udleder canonical host/repository paths internt og bruger current time.
Caller-ejede qualification/snapshot/runner-authorization/signature/verifier-data
kopieres til exact-type canonical value snapshots. Authority-subclasses afvises.

Callerens `TrustedGitRuntime` skal være exact type. Runtime-bytes kopieres til en
transaction-private staged runtime under den interne Git operation-root, med
process-private POSIX permissions hvor platformen understøtter det. Kun den
private runtime bruges til de trusted Git reads. Den caller-ejede runtime kan
derfor ikke ændres efter snapshot og få ændringen til at påvirke admissionens
Git-observationer. Private runtime-data fjernes efter transactionen; cleanup-fejl
efter successful commit failer lukket.

### 4. Frisk pre-start main + exact runner bytes

Før admission-locken:

1. runner-signaturen verificeres mod current time;
2. `refs/heads/main^{commit}` genlæses gennem den transaction-private kopi af den
   staged Trusted-Git runtime, som ADR-DC-009 og snapshot receipt bindede;
3. observationen skal matche requestens ønskede main SHA, samme repository-root
   og samme Git-runtime/executable identity;
4. reservationen må højst være 15 minutter gammel;
5. main-observationen må højst være ét minut gammel;
6. den signerede repo-relative runner-fil åbnes gennem den eksisterende stabile,
   link-frie bounded-read boundary og skal matche exact SHA-256 + byte count.
   Admissionens runner-budget er højst 16.000.000 bytes og må ikke udvide den
   allerede hærdede read-boundary.

Derefter tages en create-once admission-lock. Efter lock gentages main-read,
runner-hash, runner-signatur-verifikation og parent-reservationens live provenance.
Hvis main flytter, runneren ændres, authorization udløber eller parentens replay
markers ændres efter lock, forbliver admissionen host-lokalt
consumed/recovery-required; den må ikke blive genbrugelig.

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

Kun det exact objekt, som returneres direkte fra denne successful transaction,
registreres som live `transaction_authenticated` authority. Live provenance
bindes samtidigt til:

1. exact object identity;
2. canonical admission SHA-256 på registreringstidspunktet;
3. originating process ID;
4. de exact bytes i final admission-artifactet;
5. de exact bytes i den permanente create-once replay marker.

Før registrering skal final + replay marker genlæses via bounded regular-file
reads og være byte-identiske med transactionens egne payloads. Efter registrering
re-validerer `transaction_authenticated` de samme marker-bytes hver gang.
Sletning, udskiftning eller byte-drift i enten final eller lock invaliderer live
authority straks.

`from_mapping()` og ledger `load()` kan fortsat kun genskabe replay/recovery
evidence. `object.__setattr__`-mutation af et registreret receipt ændrer digest og
invaliderer authority. På POSIX ryddes registry i fork-child via
`os.register_at_fork`, og PID-kontrollen er et ekstra fail-closed lag. Ingen af
disse provenance-egenskaber serialiseres.

## Ingen falsk frozen-main påstand

Selv to eller tre punktobservationer beviser ikke, at `main` aldrig flyttede sig
mellem målingerne. Derfor forbliver `frozen_main_confirmed=false`.

En senere physical-completion boundary skal kræve en frisk post-campaign
main-observation og binde det faktiske signerede 11-probe report til campaign,
task, collector/approver og runner-pin. Først derefter kan et separat human
pilot-GO overhovedet vurderes.

## Fail-closed krav

Admission skal blandt andet fejle ved:

- deserialiseret eller anden ikke-transaction-authenticated reservation;
- parent-reservation hvis final/replay marker ændres eller fjernes;
- qualification/snapshot/runtime drift;
- overridable `TrustedGitRuntime` eller authority subclasses;
- mutation af caller-runtime efter den private runtime-copy;
- fremmed runner authority-system;
- runner-signatur eller payload-tamper;
- forkert host scope, campaign/task/base eller actor-binding;
- absolute/traversal/backslash/ADS-lignende runner paths;
- runner byte/hash drift;
- wrong/stale main;
- stale reservation;
- runner authorization før start eller efter expiry;
- manglende/ændret 11-probe-univers;
- duplicate admission på samme canonical host ledger;
- crash-left pending/lock state;
- final-artifact race replacement før exact-byte read-back;
- admission final/replay-marker drift efter commit;
- admission-receipt mutation eller process-fork provenance inheritance;
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
