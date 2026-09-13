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

Gør request-reservation til én authenticated host-local transaction med en
caller-uafhængig Ed25519 trust-root. Public consume-pathen accepterer ikke
verifier/keyring, observation, clock eller authority-paths; den resolver selv en
fast host-admin-kontrolleret RSI request-keyring og fejler lukket, hvis trust-
rooten mangler, er malformed, wrong-domain eller unsafe. Host-control valideres
platform-specifikt: POSIX kræver root ownership og ikke-writable directory-chain,
og Windows kræver native owner/DACL-evidence uden write/control grants til
almindelige eller brede principals. Det tidligere non-underscored reservation-
compatibility-modul er fjernet, så production trust-root ikke kan omgås gennem
forwarded functions eller compatibility-module traversal. Den eksplicit private
underscore-testseam er ikke en public authority-kontrakt; beslutningen påstår
ikke isolation mod vilkårligt kompromitteret same-process Python-kode.

Caller-ejede signed value-objekter og den host-resolved verifier kopieres til
exact-type canonical snapshots før authority-brug. Den caller-leverede
`TrustedGitRuntime` skal være exact type og verificeres mod den signed/pinned
runtime-identitet fra `CandidateSnapshotReceipt`; hele runtime-treeet kopieres
derefter create-once til en transaction-private staging-root og bruges som den
eneste execution-path for preflight og post-marker `main`-observation.

Den irreversible create-once request-marker bevares som permanent host-local
replay-marker efter succes. Både replay-marker og final receipt beholder deres
**oprindelige descriptors/handles og fil-identiteter fra selve O_CREAT|O_EXCL
publicationen** gennem provenance-registration. Registration må claim'e netop
disse originaler; et byte-identisk inode-swap før registration fejler derfor
lukket i stedet for at blive den nye baseline. Live provenance binder desuden
exact receipt-identitet, originating PID, canonical receipt-SHA og exact bytes.
Unlink/replacement/tamper invaliderer provenance, og byte-identisk recreate kan
ikke genoplive et gammelt receipt.

Durable ledger-bytes er fortsat kun replay/recovery-state og kan ikke reloades
som authenticated authority. Replay-scope er eksplicit host-local
(`host_replay_guard_committed=true`, `global_replay_safe=false`). Persistent
frozen `main`, campaign-start, pilot, publication og activation forbliver
separate authority-gates.

Fuldtekst: `docs/devcontrol/ADR-DC-009_RSI_PHYSICAL_REQUEST_RESERVATION_BOUNDARY.md`

## ADR-DC-010 — Authenticated one-shot admission før DC-L15 physical campaign

**Dato 13/09-2026. Status: foreslået til beslutning.**

Gør den live transaction-authenticated host-reservation plus en separat
human-signeret exact runner-pin til en smal, host-local one-shot campaign-start
admission. Caller-ejede authority-inputs snapshot'es til exact lokale value
objects, og callerens exact-type `TrustedGitRuntime` kopieres til en
transaction-private staged runtime før trusted Git reads. Current `main` +
runner-bytes re-verificeres omkring create-once locken.

Admission-locken forbliver permanent som host-local replay marker. Final
read-back skal være byte-identisk med den committed payload, og live provenance
bindes til exact objekt-identitet, originating PID, canonical SHA samt de exact
current bytes i både final admission og replay marker. Mutation, fork eller
marker-drift failer derfor lukket. Runner-budgettet er højst 16.000.000 bytes
inden for den allerede hardened stable-read boundary.

Admission kan kun give `campaign_start_authorized=true` for én manuel fysisk
kampagne. Den kører ingen probes og giver ikke frozen-main, physical-complete,
pilot, merge, publication, release, deploy eller activation authority.

Fuldtekst: `docs/devcontrol/ADR-DC-010_RSI_PHYSICAL_CAMPAIGN_ADMISSION_BOUNDARY.md`
