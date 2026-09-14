# DevControl — arkitekturbeslutninger

Dette er det **komplette indeks** over DevControl-beslutninger. Fuldteksterne bor
i `docs/devcontrol/` og står kun dér; denne fil gengiver ikke beslutningstekst.

DevControl er ikke Agent 4 og nummereres bevidst i sin egen serie. Beslutninger
føres som **ADR-DC-NNN**.

ADR'er beskriver beslutninger, aldrig aktuel merge-status — den aflæses af de
genererede tilstandsdokumenter.

## ADR-DC-001 — DevControl som isoleret, dvalende autoritetskæde for kontrolleret selvudvikling

**Truffet af Anders 05/08-2026. Status: besluttet.**

Fastlægger otte beslutninger: DevControl som selvstændig pakke uden
produktkobling; menneskelig terminal autoritet der ikke kan delegeres;
fail-closed på hvert autoritetslag; fysisk evidens som forudsætning frem for
rapport; indeslutning som operativsystemets ansvar; bevist dvale; en
aktiveringsport der kræver sin egen ADR for enhver faktisk publikationsevne; og
egen ADR-serie. Syv obligatoriske kontrakttests.

Vedtaget FØR implementeringen landes, så efterprøvningen af PR #338 måler
branchen mod ADR'en frem for omvendt.

Fuldtekst: `docs/devcontrol/ADR-DC-001_DEVCONTROL_AUTHORITY_BOUNDARY.md`

## ADR-DC-002 — RSI-forbedringsforslag som ikke-autoriserende lag

**Dato 12/09-2026. Status: foreslået til beslutning.**

Afgrænser RSI-leddet fra eval-evidens til et modeludarbejdet, men
ikke-autoriserende forbedringsforslag. Forslaget er SHA/digest-bundet,
falsificerbart og må kun foreslå scope/tests; det kan ikke tildele DevControl
execution authority eller konverteres automatisk til `DevelopmentTask`.

Første adapter er `kaliv-agent3-model-eval/v1`; ren evidens producerer intet
opfundet forbedringsarbejde. Promotion til en rigtig udviklingsopgave forbliver
et separat authority-step under ADR-DC-001.

Fuldtekst: `docs/devcontrol/ADR-DC-002_RSI_IMPROVEMENT_PROPOSAL_BOUNDARY.md`

## ADR-DC-003 — Signeret promotion fra RSI-forslag til DevelopmentTask

**Dato 12/09-2026. Status: foreslået til beslutning.**

Gør proposal → `DevelopmentTask` til en separat, human-signed authority-grænse.
Hele task-scope, commands, budget, risk og acceptance criteria skal ligge i det
signerede authorization-artifact; intet execution scope må arves implicit fra
modellens suggestions.

Fuldtekst: `docs/devcontrol/ADR-DC-003_RSI_PROPOSAL_PROMOTION_BOUNDARY.md`

## ADR-DC-004 — Candidate-vs-incumbent regression proof for RSI

**Dato 12/09-2026. Status: foreslået til beslutning.**

Binder incumbent til proposalets originale evidence digest og kræver identisk
eval-univers for candidate. En kandidat accepteres kun ved målbar forbedring
uden request-, discipline- eller risk-regression og uden at give ny authority.

Fuldtekst: `docs/devcontrol/ADR-DC-004_RSI_CANDIDATE_REGRESSION_PROOF.md`

## ADR-DC-005 — RSI candidate runtime provenance

**Dato 12/09-2026. Status: foreslået til beslutning.**

Lukker provenance-kløften mellem DC-L13's materialiserede candidate commit/tree
og den runtime-kode, som Agent 3-evalen faktisk målte. Exact Git-tree,
worker-fingerprint, candidate-eval og accepted regression proof bindes uden
publication-, merge- eller activation-authority.

Fuldtekst: `docs/devcontrol/ADR-DC-005_RSI_CANDIDATE_RUNTIME_PROVENANCE.md`

## ADR-DC-006 — Read-only RSI candidate snapshot collection

**Dato 12/09-2026. Status: foreslået til beslutning.**

Indsamler tracked candidate-bytes fra DC-L13's local-only bare repository gennem
staged `TrustedGitRuntime`, med objektbinding og budgets. Collection er offline,
read-only, re-verificerer materialization og tilføjer ingen Git/GitHub write-
eller execution-authority.

Fuldtekst: `docs/devcontrol/ADR-DC-006_RSI_CANDIDATE_SNAPSHOT_COLLECTION.md`

## ADR-DC-007 — RSI pre-physical qualification packet før DC-L15/DC-L16

**Dato 12/09-2026. Status: foreslået til beslutning.**

Samler hele software-RSI chain-of-custody i et evidence-only qualification
packet, men holder de fysiske og menneskelige gates eksplicit åbne. Et packet
kan derfor bevise softwarekæden uden at erklære GO, starte DC-L15/DC-L16 eller
autorisere publication/activation.

Fuldtekst: `docs/devcontrol/ADR-DC-007_RSI_PRE_PHYSICAL_QUALIFICATION_PACKET.md`

## ADR-DC-008 — Human-signed RSI request før DC-L15 fysisk qualification

**Dato 12/09-2026. Status: foreslået til beslutning.**

Indfører et kortlivet, Ed25519-verificeret human request-artifact, der binder én
pre-physical qualification-pakke til en ønsket frozen-main SHA, det eksisterende
11-probe I0b-univers og forskellige collector/approver-aktører. Verifikation
beviser kun den menneskelige anmodning; den bekræfter ikke frozen `main`,
forbruger ikke requesten og giver ikke campaign-start, pilot, publication eller
activation authority.

Fuldtekst: `docs/devcontrol/ADR-DC-008_RSI_PHYSICAL_QUALIFICATION_REQUEST_BOUNDARY.md`

## ADR-DC-009 — Authenticated host-local request-reservation før DC-L15

**Dato 12/09-2026. Status: foreslået til beslutning.**

Gør request-reservation til én authenticated host-local transaction med
caller-uafhængig Ed25519 trust-root, elevated host-operator replay-state,
host-admin-kontrolleret Git runtime **og et separat host-admin-kontrolleret Git
metadata-target**. Public consume accepterer ikke verifier/keyring, observation,
clock, ledger/root paths eller prebuilt receipt.

POSIX host-control er ACL-aware: keyring, runtime, repository-target og replay
state skal være root-owned, uden group/world-write og uden extended POSIX
access/default ACLs. Windows bruger Program Files + native owner/DACL evidence,
hvor ordinary/broad principals ikke må have write/control authority.

Production Git-readet tillader kun `rev-parse --verify refs/heads/main^{commit}`.
Authority-pathen launcher den attesterede Git executable direkte og relauncher
ikke den generelle `bounded_subprocess.py` package-supervisor. Den beskytter også
observationens target: checkout-root/ancestor-chain og hele `.git` metadata-treeet
skal være host-admin-kontrolleret før og efter readet. Linked/common Git dirs,
external object alternates og local config `include`/`includeIf` fejler lukket,
så en beskyttet executable ikke kan omdirigeres til caller-writable Git state.
Det beskytter **ikke** alle tracked worktree bytes og er derfor ikke et frozen-
main proof.

Production replay-ledgeren er fast og pre-provisioned. POSIX kræver effektiv UID
0; Windows kræver elevated token. Ordinary ModelRig service-identiteter er ikke
replay-state writers. `host_replay_guard_committed=true` beskriver kun den
canonical host-admin-ledger; kompromitteret root/host-admin og distributed/global
one-time use er eksplicit uden for garantien, og `global_replay_safe=false`.

Replay-marker/final beholder original-publication descriptors, og live provenance
binder receipt identity, PID, digest, durable file identity og Linux directory
history. Linux bruger watch-before-trust på hele ledger ancestry med history-drain
både før og efter identity-validation; non-Linux POSIX production fejler aktuelt
lukket frem for at overclaim'e tilsvarende race-free semantics.

Reservationen er fortsat evidence-only: `frozen_main_confirmed=false`,
`physical_campaign_completed=false`, `campaign_start_authorized=false`,
`pilot_go_authorized=false`, `remote_publication_authorized=false` og
`activation_authorized=false`. Persistent freeze, fysisk campaign-admission,
pilot, publication og activation forbliver separate authority-gates.

Fuldtekst: `docs/devcontrol/ADR-DC-009_RSI_PHYSICAL_REQUEST_RESERVATION_BOUNDARY.md`

## ADR-DC-010 — Authenticated one-shot admission før DC-L15 physical campaign

**Dato 13/09-2026. Status: foreslået til beslutning.**

Gør den live transaction-authenticated host-reservation plus en separat
human-signeret exact runner-pin til en smal, host-local one-shot campaign-start
admission. Production resolver runner-signature trust fra en fast host-admin-
kontrolleret verification-only keyring; caller-valgt verifier er ikke authority.
Den exact `TrustedGitRuntime` skal samtidig være host-admin-kontrolleret og køres
direkte gennem den restricted read-only Git-reader — production kopierer ikke
executable bytes til en same-user staging-root. Private underscored tests kan
fortsat bruge injectable verifier + transaction-private runtime staging.

Admission-lock og final receipt arver ADR-DC-009's original-publication
provenance: de oprindelige `O_CREAT|O_EXCL` descriptors/filidentiteter beholdes
gennem registration, og live authority bindes til exact objekt/PID/SHA og de
oprindelige marker-identiteter. På Linux bindes admission-ledgeren og dens
ancestor-kæde desuden til watch-before-trust directory-history før første
permanente publication. Byte-identisk unlink/recreate, whole-ledger
rename→replay→restore og ancestor rename→replay→restore kan derfor ikke etablere
en ny authority-baseline; unrelated sibling-churn forbliver neutral.
Runner-budgettet er højst 16.000.000 bytes inden for den allerede hardened
stable-read boundary.

Admission kan kun give `campaign_start_authorized=true` for én manuel fysisk
kampagne. Den kører ingen probes og giver ikke frozen-main, physical-complete,
pilot, merge, publication, release, deploy eller activation authority.

Fuldtekst: `docs/devcontrol/ADR-DC-010_RSI_PHYSICAL_CAMPAIGN_ADMISSION_BOUNDARY.md`

## ADR-DC-011 — Host-pinned post-campaign physical evidence uden DC-L15 completion authority

**Dato 13/09-2026. Status: foreslået til beslutning.**

Verificerer eksisterende DC-L04 Windows physical-report evidence efter en live
ADR-DC-010 admission og binder resultatet til en frisk post-campaign `main`-
observation. Production afviser caller-valgt verifier/evidence-root og resolver i
stedet en fast host-admin-kontrolleret evidence-root og HMAC-keyring; Trusted Git
skal fortsat være host-admin-kontrolleret og kører gennem den direct read-only
Git-boundary uden same-user runtime-copy.

Det legacy HMAC-format giver verifieren signing-equivalent secret-materiale og
binder hverken `campaign_id` eller exact runner-bytes. En frisk post-campaign SHA
beviser heller ikke continuous freeze. Snapshot'et er derfor eksplicit
`verified-physical-evidence-only`: runner-execution binding, continuous-main
freeze, DC-L15 completion, independent human verdict og pilot GO forbliver åbne
gates. Ingen merge, publication, release, deploy eller activation autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-011_RSI_POST_CAMPAIGN_PHYSICAL_EVIDENCE_BOUNDARY.md`

## ADR-DC-012 — Human/Ed25519 exact-runner execution binding efter physical evidence

**Dato 13/09-2026. Status: foreslået til beslutning.**

Lukker kun `exact_runner_execution_binding` med en separat human-signeret
Ed25519-claim, der binder hele ADR-DC-011 snapshot-digesten til exact
campaign/admission/task/base, exact runner path/SHA/byte-count og exact physical
report-digests/ID. Signeren skal være den fysiske operator/collector og må ikke
være approveren.

Production afviser caller-valgt verifier og resolver kun en fast host-admin-
kontrolleret public-key keyring. Successful verification er eksplicit
`verified-human-exact-runner-execution-binding-only`: den menneskelige signatur
er en execution-attestation, ikke kernel telemetry, og den re-verificerer ikke
det legacy HMAC report.

Continuous-main freeze, DC-L15 completion, independent human verdict og pilot GO
forbliver separate gates. Ingen Git/GitHub write, merge, publication, release,
deploy eller activation autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-012_RSI_EXACT_RUNNER_EXECUTION_BINDING.md`

## ADR-DC-013 — Live continuous `main` freeze over one physical campaign

**Dato 13/09-2026. Status: foreslået til beslutning.**

Lukker kun `continuous_main_freeze_confirmation` med en live, process-local
watch-before-observe lease, der skal være armet før exact runner execution og
forblive aktiv gennem evidence + execution-binding. Linux bruger `inotify` og
Windows overlapped `ReadDirectoryChangesW`; ref mutation→revert, queue/watch loss
og path replacement fejler lukket.

Files-ref backend overvåges via exact `main`/`main.lock`,
`packed-refs`/`packed-refs.lock`, config og Git-path ancestry. Reftable,
linked/common Git dirs og symbolic main er ikke understøttet og fejler lukket.

Successful proof er kun `verified-continuous-main-freeze-only`; DC-L15 completion,
independent human verdict og pilot GO forbliver separate. Ingen merge,
publication, release, deploy eller activation autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-013_RSI_CONTINUOUS_MAIN_FREEZE.md`

## ADR-DC-014 — Independent human verdict closes DC-L15, not pilot GO

**Dato 13/09-2026. Status: foreslået til beslutning.**

Lukker kun `dc_l14_independent_human_verdict` ved verification af et separat
Ed25519-signeret human verdict over exact ADR-DC-013 main-freeze proof og exact
ADR-DC-012 execution proof. Reviewer skal være forskellig fra både physical
operator og approver; production resolver kun en host-admin-kontrolleret
verification-only public-key keyring og indeholder ingen signer/private key.

Kun `approve` kan blive til et completion proof. `request_changes` og `reject`
kan være gyldigt signerede review-artifacts, men kan ikke lukke DC-L15.
Successful approval kan sætte `physical_campaign_completed=true` og
`dc_l15_complete=true`, men `human_pilot_go_decision` forbliver den eneste åbne
gate. Pilot, merge, publication, release, deploy og activation autoriseres ikke.

Fuldtekst: `docs/devcontrol/ADR-DC-014_RSI_INDEPENDENT_HUMAN_VERDICT.md`

## ADR-DC-015 — Human-signed pilot decision without starting DC-L16

**Dato 13/09-2026. Status: foreslået til beslutning.**

Lukker kun `human_pilot_go_decision` ved verification af en separat Ed25519-
signeret `GO`, `NO-GO` eller `GO WITH CONDITIONS` beslutning over exact
ADR-DC-014 completion proof og en eksplicit lokal pilot-scope. Scope binder
operator surface, allowlisted task IDs, workspace-root digest, local-commit valg
og default-deny invariants for remote write, push/PR/merge/release/deploy og
production activation.

Et verificeret positivt verdict kan kun sætte `pilot_go_authorized=true`; det
starter ikke en product pilot og holder feature flag default-off. `NO-GO`
forbliver et verificeret decision proof med `pilot_go_authorized=false`.
Production resolver kun en host-admin-kontrolleret verification-only public-key
keyring og indeholder ingen signer/private key eller produktentrypoint.

Fuldtekst: `docs/devcontrol/ADR-DC-015_RSI_HUMAN_PILOT_DECISION.md`

## ADR-DC-016 — Single-trial scope projection without pilot-start authority

**Dato 13/09-2026. Status: foreslået til beslutning.**

Indsnævrer et allerede verificeret positivt ADR-DC-015 human pilot decision proof
til præcis én allowlisted lokal trial. Projection binder exact decision proof,
campaign/task/base/main, decision maker, operator surface, workspace digest, ét
selected task ID, local-commit narrowing og signed decision notes/conditions.

`GO WITH CONDITIONS` bevarer conditions og kan ikke deserialiseres uden mindst
én note. Successful projection beviser kun scope; runtime verification, faktisk
feature-flag observation, pilot-start og product-pilot-start forbliver false.
Ingen command registration, remote write/push/PR/merge/release/deploy eller
production activation autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-016_RSI_SINGLE_TRIAL_SCOPE_PROJECTION.md`

## ADR-DC-017 — Inert DC-L16 pilot preflight requirements manifest

**Dato 13/09-2026. Status: foreslået til beslutning.**

Afleder et deterministisk requirements-manifest fra exact ADR-DC-016
single-trial scope. Manifestet fastlåser hvilke egenskaber en senere, separat
runtime-preflight skal bevise: feature flag off-observation, runtime-boundary,
native Windows isolation, trusted-Git closure, kill/revoke prearm, blokering af
network write, fravær af credentials, forbud mod unattended cadence, off-state
import-block samt exact source- og receipt-binding.

Krav er ikke observationer: `preflight_observed=false`,
`preflight_satisfied=false`, `pilot_start_authorized=false` og
`product_pilot_started=false` er obligatoriske. Ingen host-observer, feature-flag
reader, command registry, executor, network transport, publication eller
production activation tilføjes.

Fuldtekst: `docs/devcontrol/ADR-DC-017_RSI_PILOT_PREFLIGHT_REQUIREMENTS.md`

## ADR-DC-018 — Exact-source product integration inventory before surface selection

**Dato 14/09-2026. Status: foreslået til beslutning.**

Kortlægger tre eksisterende produktkandidater med exact Git blob-identitet:
Desktop Control Center, Android Control Center og backendens lokale route-host
mønster. Inventoryet dokumenterer eksisterende paired/Bearer og default-off
precedents, men vælger ingen operator surface, feature flag, route, observer
eller task registry.

Alle kandidater forbliver `selected=false`; `integration_ready`, runtime/preflight
claims, pilot-start og product-pilot-start forbliver false. Produktkilderne må
fortsat ikke importere `kaliv_dev_control`, og slicen ændrer ingen produktkode.
Ingen remote write/push/PR/merge/release/deploy eller production activation
autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-018_RSI_PILOT_PRODUCT_INTEGRATION_INVENTORY.md`

## ADR-DC-019 — Human-bound product integration selection requirements before DC-L16 runtime preflight

**Dato 14/09-2026. Status: foreslået til beslutning.**

Fastlåser kun requirements for en senere human-bound product-integration
selection. En senere selection skal være exact bundet til et verificeret positivt
ADR-DC-015 human pilot decision proof og exact ADR-DC-016 single-trial scope,
så operator surface, task, workspace-digest og local-commit policy ikke kan
udvides af model- eller produktlaget.

Kendte surfaces skal bindes til ADR-DC-018 exact-source inventory; en ukendt
surface kræver frisk exact-source inventory evidence. Feature flag, route,
runtime observer, task registry, workspace policy, review/authorization roles og
kill/revoke/cleanup er eksplicit påkrævede senere designvalg, men ingen af dem
vælges i denne slice.

`human_selection_recorded`, alle konkrete selection-state felter,
`integration_ready`, runtime/preflight claims, pilot-start og product-pilot-start
forbliver false. Ingen produktimport, command registration, remote write/push/PR/
merge/release/deploy eller production activation autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-019_RSI_PILOT_PRODUCT_INTEGRATION_SELECTION_REQUIREMENTS.md`

## ADR-DC-020 — Fail-closed product integration selection candidate before human recording

**Dato 14/09-2026. Status: foreslået til beslutning.**

Validerer en konkret product-integration candidate mod exact ADR-DC-016 scope,
ADR-DC-018 inventory og ADR-DC-019 requirements uden at registrere et
menneskeligt valg. Kandidatens surface skal være identisk med den signerede
operator surface og dens kind/path/blob skal matche pinned source identity.

Feature flag, route, runtime observer, task registry, workspace policy,
review/authorization roles, kill/revoke/cleanup og local-commit policy skal være
komplette, men proofet er kun en valideret kandidat. Unknown surfaces kræver
frisk exact-source inventory, og deserialisering revaliderer source binding.

`human_selection_recorded`, `integration_ready`, runtime/preflight claims,
pilot-start og product-pilot-start forbliver false. Ingen produktkode,
remote write/push/PR/merge/release/deploy eller production activation
autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-020_RSI_PILOT_PRODUCT_INTEGRATION_SELECTION_CANDIDATE.md`

## ADR-DC-021 — Human-signed exact product-integration selection before runtime preflight

**Dato 14/09-2026. Status: foreslået til beslutning.**

Indfører en separat Ed25519-signeret human selection over ét exact ADR-DC-020
candidate proof. De signerede bytes indlejrer hele candidate proofet og binder
dets SHA-256, selection maker, selection ID og canonical selection time, så
candidate/design/source rebinding kræver en ny menneskelig signatur.

Production accepterer ikke caller-valgt verifier og resolver kun en separat
host-admin-kontrolleret verification-only public-key keyring. Et verificeret
proof kan kun sætte `human_selection_recorded=true` og
`candidate_selection_verified=true`; `integration_ready`, runtime/preflight,
pilot-start, remote write/push/PR/merge/release/deploy og production activation
forbliver false.

Der oprettes ingen faktisk signed selection artifact og ingen product surface
vælges i denne slice.

Fuldtekst: `docs/devcontrol/ADR-DC-021_RSI_PILOT_PRODUCT_INTEGRATION_HUMAN_SELECTION.md`

## ADR-DC-022 — Exact-bound runtime-preflight evidence packet before host verification

**Dato 14/09-2026. Status: foreslået til beslutning.**

Binder et komplet sæt på tolv SHA-256 evidence-digests til exact ADR-DC-021
human-selection proof og exact ADR-DC-017 preflight requirements. Packetet
krydstjekker trial-scope, decision proof, repository, base/main SHA, operator
surface, selected task, workspace-root digest og local-commit policy, så et
evidence-set ikke kan rebinde til en anden pilot-scope.

`observation_set_complete=true` betyder kun, at alle tolv evidence-referencer er
til stede og exact-bound. Packetet læser ingen host-state og verificerer ikke de
refererede artifacts; `evidence_verified`, `preflight_observed`,
`preflight_satisfied`, pilot-start, local commit og alle remote/publication/
activation authorities forbliver false.

Fuldtekst: `docs/devcontrol/ADR-DC-022_RSI_PILOT_RUNTIME_PREFLIGHT_OBSERVATION_PACKET.md`

## ADR-DC-023 — Host-attested runtime-preflight proof over exact ADR-DC-022 evidence packet

**Dato 14/09-2026. Status: foreslået til beslutning.**

Gør exact ADR-DC-022 packetet til canonical input for en separat host-attesteret
Ed25519-verifikation. Attestationens signerede bytes indlejrer hele packetet og
dermed alle tolv individuelle evidence-digests, human-selection proof,
requirements og trial/workspace/source-bindinger. Production accepterer ikke
caller-valgt verifier og resolver kun en separat host-controlled verification-
only public-key keyring under elevated host operator.

Et cryptographically valid proof kan kun sætte `host_attestation_verified=true`,
`preflight_observed=true` og `preflight_satisfied` ud fra alle tolv signerede
resultater. Et gyldigt signeret failed preflight bevares som observed men ikke
satisfied. `integration_ready`, pilot-start, product-pilot-start, local commit,
remote write/push/PR/merge/release/deploy og production activation forbliver
false.

Fuldtekst: `docs/devcontrol/ADR-DC-023_RSI_PILOT_RUNTIME_PREFLIGHT_ATTESTATION.md`

## ADR-DC-024 — Human-signed one-shot pilot-start authorization after satisfied host preflight

**Dato 14/09-2026. Status: foreslået til beslutning.**

Indfører en separat, kortlivet Ed25519-signeret human authorization over ét exact
fully satisfied ADR-DC-023 host-attested preflight proof. Authorizationen
indlejrer hele proofet og binder ADR-DC-023 attestation, ADR-DC-022 packet,
ADR-DC-021 selection, candidate/requirements/trial-scope samt exact
repository/base/main/operator/task/workspace/local-commit scope. Start-authorizeren
skal være samme human actor som ADR-DC-021 selection og være forskellig fra
preflight-observer/attestor.

Production må ikke stole på et deserialiseret ADR-DC-023 proof alene. Før human
start-authority kan vurderes, skal den detached ADR-DC-023-signatur re-verificeres
frisk mod den host-controlled preflight-keyring, og proofets signatur-, signer-,
attestation- og packet-identitet skal matche den friske verification.

Authorization-vinduet er højst 15 minutter og binder en separat one-shot
`start_nonce_sha256`. Claimen autoriserer intet; først host-pinned detached
Ed25519-verifikation kan sætte `pilot_start_authorized=true`. Selv proofet holder
`one_shot_start_required=true`, `start_consumed=false`, `integration_ready=false`,
`product_pilot_started=false`, local commit, remote write/push/PR/merge/release/
deploy og production activation false. Replay-safe consumption/start-receipt er
en separat senere authority-boundary.

Fuldtekst: `docs/devcontrol/ADR-DC-024_RSI_PILOT_START_AUTHORIZATION.md`

## ADR-DC-025 — Host-local replay-safe one-shot pilot-start authorization consumption

**Dato 14/09-2026. Status: foreslået til beslutning.**

Consumer exact ADR-DC-024 authorization én gang i en canonical host-admin-kontrolleret
ledger. Før replay-state røres, re-verificerer production fresh hele upstream chain via
ADR-DC-024 production-boundaryen med både detached ADR-DC-023 og ADR-DC-024 signaturer.
Signed `start_nonce_sha256` er create-once replay key; en permanent lock publiceres før
final receipt, og expiry efter lock fejler lukket uden at genåbne authorizationen.

Et successful receipt kan kun bevise `start_consumed=true`,
`start_receipt_issued=true` og host-local replay commitment. Det bevarer
`pilot_start_authorized=true` som historisk provenance, men kræver samtidig
`task_execution_authorized=false`, `integration_ready=false`,
`product_pilot_started=false`, local commit samt alle remote/publication/activation
authorities false. Serialized reload genvinder ikke live transaction provenance, og
`global_replay_safe=false` er eksplicit.

Fuldtekst: `docs/devcontrol/ADR-DC-025_RSI_PILOT_START_CONSUMPTION_RECEIPT.md`

## ADR-DC-026 — Exact-bound requirements before one DC-L16 pilot execution admission

**Dato 14/09-2026. Status: foreslået til beslutning.**

Afleder et inert requirements-manifest fra ét exact ADR-DC-025 start-consumption
receipt. Manifestet binder receipt/proof/signature/nonce/ledger-identitet samt
repository, base/main SHA, trial, operator surface, selected task, workspace og
det menneskeligt signerede local-commit scope. Et durable/reloaded receipt må
beskrive requirements, men kan ikke genvinde live transaction authority.

Et senere admission-led skal derfor revalidere canonical host-ledger og fresh
ADR-DC-023/024 authority, kræve live consumption-receipt ved admission,
allowlisted exact task, canonical workspace, explicit enabled feature-flag
observation, native Windows isolation, trusted-Git closure, kill/revoke/restart
gates, network-write block, credentials absent, ingen unattended cadence/general
shell/model-defined commands, exact source/base/head + toolchain binding,
execution receipt og manual operator invocation.

Alle observations-, execution-, local/remote publication- og activation-authority
felter forbliver false. Authority er kun
`dc-l16-pilot-execution-admission-requirements-only`; der registreres ingen
kommando, udføres ingen task og startes ingen product pilot.

Fuldtekst: `docs/devcontrol/ADR-DC-026_RSI_PILOT_EXECUTION_ADMISSION_REQUIREMENTS.md`

## ADR-DC-027 — Exact-bound execution-admission observation packet before host verification

**Dato 14/09-2026. Status: foreslået til beslutning.**

Binder et komplet sæt på 21 SHA-256 evidence-referencer til ét exact ADR-DC-026
requirements-manifest og den samme ADR-DC-025 start-receipt lineage. Packetet
indlejrer requirements-manifestet, dets digest og `start_receipt_sha256`, så
evidence fra en anden trial, task, workspace eller consumption ikke kan rebinde.

`observation_set_complete=true` betyder kun, at alle 21 evidence-slots er til
stede og exact-bound. Packetet udfører ingen host-I/O og verificerer ikke de
refererede artifacts; derfor forbliver `evidence_verified=false`,
`execution_admission_observed=false`, `task_execution_authorized=false`,
`product_pilot_started=false` og alle local/remote publication/activation-
authorities false.

Næste separate boundary er host-kontrolleret verification/attestation over exact
ADR-DC-027 packet. Selv en senere green host-verification er ikke automatisk task
execution uden en særskilt execution-admission/executor boundary.

Fuldtekst: `docs/devcontrol/ADR-DC-027_RSI_PILOT_EXECUTION_ADMISSION_OBSERVATION.md`

## ADR-DC-028 — Host-attested execution-admission verification without task execution authority

**Dato 14/09-2026. Status: foreslået til beslutning.**

Verificerer ét exact ADR-DC-027 observation packet med en host-pinned Ed25519
verification-only trust-root. Det signerede claim indlejrer hele packetet, binder
`packet_sha256` og `start_receipt_sha256` og indeholder præcis ét boolsk resultat
for hvert af de 21 ADR-DC-026/027 checks.

Et cryptographically valid proof kan kun sætte `host_attestation_verified=true`,
`execution_admission_observed=true` og `execution_admission_satisfied=true` når
alle 21 signerede resultater er true. Et gyldigt signeret failed check forbliver
observed men unsatisfied.

Selv et fuldt grønt proof holder `task_execution_authorized=false`,
`integration_ready=false`, `product_pilot_started=false`, local commit og alle
remote/publication/activation authorities false. Production afviser caller-valgt
verifier og resolver kun canonical host-controlled verification state under
elevated host operator.

Næste separate led er explicit execution-admission/executor authority for præcis
den valgte task; ADR-DC-028 udfører ingen command eller pilot-task.

Fuldtekst: `docs/devcontrol/ADR-DC-028_RSI_PILOT_EXECUTION_ADMISSION_ATTESTATION.md`

## ADR-DC-029 — Exact task-execution admission requirements without execution authority

**Dato 14/09-2026. Status: foreslået til beslutning.**

Fastlåser requirements for en senere one-shot execution-admission over ét exact,
fully satisfied ADR-DC-028 host-attestation proof. Manifestet binder proof,
attestation, detached signature, packet/start-receipt lineage samt exact
repository/base/main, trial, operator surface, selected task og workspace.

Et senere authority-led skal bl.a. re-verificere ADR-DC-028 fresh, revalidere den
live ADR-DC-025 consumption, kræve en separat fresh human task-execution
authorization, one-shot execution nonce + canonical host-local replay-ledger,
exact task-registry entry, source/toolchain/workspace binding, feature flag,
isolation/trusted-Git, kill/revoke/restart, blocked network writes, absent
credentials, fixed command plan, bounded execution budget, manual invocation og
post-execution receipt.

Denne requirements-slice udsteder ingen admission. `task_execution_authorized=false`,
`task_execution_started=false`, local commit og alle remote/publication/activation
authorities forbliver false. Der registreres ingen command og kaldes ingen executor.

Fuldtekst: `docs/devcontrol/ADR-DC-029_RSI_PILOT_EXACT_TASK_EXECUTION_ADMISSION_REQUIREMENTS.md`

## ADR-DC-030 — Human-signed exact-task execution authorization without executor authority

**Dato 14/09-2026. Status: foreslået til beslutning.**

Indfører en separat, kortlivet Ed25519-signeret human authorization over ét exact
ADR-DC-029 requirements-manifest. Claimen binder hele requirements-manifestet og
dermed ADR-DC-028/027/026/025-lineagen samt exact repository/base/main, trial,
operator surface, selected task, workspace og human local-commit upper bound.
Execution-authorizeren skal være samme human actor som signerede ADR-DC-024
pilot-start authorization og være forskellig fra ADR-DC-028 host-attestoren.

Production kræver fresh host-pinned re-verifikation af den detached ADR-DC-028
attestation-signatur før den nye human-signatur vurderes. Authorization-vinduet
er højst 10 minutter og binder en separat execution nonce, som ikke må genbruge
pilot-start noncen.

Et verificeret proof kan kun sætte
`human_task_execution_authorization_verified=true` og
`one_shot_execution_required=true`; consumption, execution-admission,
task-execution/start, local commit og alle remote/publication/activation
authorities forbliver false. En senere separat host-local replay-safe
consume/admission-boundary skal fresh revalidere de resterende ADR-DC-029 gates
før task execution kan autoriseres.

Fuldtekst: `docs/devcontrol/ADR-DC-030_RSI_PILOT_EXACT_TASK_EXECUTION_HUMAN_AUTHORIZATION.md`

## ADR-DC-031 — Exact-task execution revalidation observation before host verification

**Dato 14/09-2026. Status: foreslået til beslutning.**

Binder et komplet sæt på 25 SHA-256 evidence-referencer til ét exact verificeret
ADR-DC-030 human execution-authorization proof og dermed ADR-DC-029/028/025-
lineagen, exact repository/base/main, trial, operator surface, selected task,
workspace og signed execution nonce.

Observationen skal ligge efter ADR-DC-030 verification og senest ved den signerede
authorization expiry. `fresh_human_task_execution_authorization_evidence_sha256`
skal matche exact ADR-DC-030 proof SHA-256, og
`one_shot_execution_nonce_evidence_sha256` skal matche den signerede execution
nonce. De øvrige slots er non-placeholder evidence-referencer for alle resterende
ADR-DC-029 fresh-revalidation gates.

`observation_set_complete=true` betyder kun, at alle 25 references er til stede
og exact-bound. Packetet udfører ingen host-I/O og verificerer ingen referenced
artifacts; derfor forbliver `evidence_verified=false`,
`task_execution_admission_observed=false`, `task_execution_authorized=false`,
`task_execution_started=false`, local commit og alle remote/publication/activation
authorities false.

Næste separate led er host-kontrolleret verification/attestation over exact
ADR-DC-031 packet. Replay-safe one-shot consumption/admission og actual executor
transaction forbliver senere separate boundaries.

Fuldtekst: `docs/devcontrol/ADR-DC-031_RSI_PILOT_EXACT_TASK_EXECUTION_REVALIDATION_OBSERVATION.md`
