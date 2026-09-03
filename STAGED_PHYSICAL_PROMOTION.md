# Staged physical promotion — 2.0.13

Denne fil er den autoritative rækkefølge for fysisk promotion af ModelRig
`2.0.13`. Kandidaten ligger på `physical-proof/2.0.13`; den eksakte SHA skal
altid læses fra den fetch'ede `origin/physical-proof/2.0.13`, matches mod lokal
HEAD og bevises med `candidate_freeze_check.py`. Den må aldrig gættes eller
kopieres fra ældre evidens.

## Ufravigelige grænser

- Stage A kører mod én upubliceret, kvalificeret kandidat-SHA.
- Samme SHA bruges senere til fast-forward, tag `v2.0.13` og release.
- Efter fysisk evidens er begyndt, er squash, rebase, mergecommit, amend og
  enhver anden SHA-ændring forbudt.
- Enhver bevægelse af kandidatbranch eller `origin/main` kræver ny freeze og ny
  evidens.
- Alle receipts og rapporter skal bevare `production_activation=false`.
- Ingen launcher i dette flow merger, pusher, tagger, releaser eller aktiverer.

## Stage A — upubliceret kandidat

### A0. Lås checkouten

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
git fetch origin
git switch physical-proof/2.0.13
git pull --ff-only origin physical-proof/2.0.13
$CandidateSha = (git rev-parse HEAD).Trim()
$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.13).Trim()
if ($CandidateSha.Length -ne 40) { throw "Ugyldig kandidat-SHA" }
if ($CandidateSha -ne $RemoteCandidateSha) { throw "Lokal candidate matcher ikke origin/physical-proof/2.0.13: local=$CandidateSha remote=$RemoteCandidateSha" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "2.0.13") { throw "Forkert version" }
python scripts/candidate_freeze_check.py --expected-sha $CandidateSha
if ($LASTEXITCODE -ne 0) { throw "Candidate er ikke frozen paa exact SHA $CandidateSha" }
```

`origin/physical-proof/2.0.13`, lokal exact HEAD og den grønne
`candidate_freeze_check.py` skal alle pege på samme kandidat-SHA. Stop ved
enhver forskel. Historiske freeze-PR'er og tidligere 2.0.13-heads er ikke
SHA-authority.

### A1. Opret en frisk freeze-receipt

Sæt `GH_TOKEN` eller `GITHUB_TOKEN`, og kør den anbefalede launcher:

```text
START_STAGE_A_TEST.cmd
```

Manuel fallback:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Prepare `
  -ExpectedSha $CandidateSha
```

`Prepare` kører `candidate_freeze_check.py` og
`physical_validation_candidate_campaign.py --mode prepare`. Freeze-kontrollen
kræver exact HEAD, ren tree, versionsparitet, current `origin/main` som ancestor
og grønne `ci`, `codeql`, `agent3-diagnostics` og
`agent3-full-diagnostics` på præcis SHA'en.

En freeze-receipt er ikke permanent tilladelse. Hver consumer refetcher
`origin/main`; fetch-fejl eller en flyttet main-anchor afviser receipt'en og
kræver komplet re-freeze.

### A2. Saml de seks kandidatbeviser

1. T-004 preflight — `PHYSICAL_VALIDATION_CAMPAIGN.md`.
2. T-005 Agent 3 appliance-validation — `AGENT3_RIG_VALIDATION.md`.
3. T-007 lokal model-eval.
4. T-040 voice-baseline inklusive Pixel-matrix.
5. T-043 RAG 1k/10k-baseline.
6. T-019 scheduler-pilot.

Kør derefter:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Verify `
  -ExpectedSha $CandidateSha `
  -MaxAgeHours 168 `
  -MinModelExact 1.0
```

`Verify` kræver den faste allowlist `preflight`, `agent3`, `model_eval`,
`voice`, `rag` og `scheduler_pilot` frisk, grøn og kandidatbundet.

### A3. Interaktivt browserbevis og kandidatgate

Vælg én på forhånd godkendt offentlig HTTPS/443-URL:

```powershell
$Url = "https://DEN-EKSAKTE-GODKENDTE-URL/"
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Complete `
  -ExpectedSha $CandidateSha `
  -Url $Url `
  -MaxAgeHours 168 `
  -MinModelExact 1.0
```

`Complete` genkører freeze og de seks beviser, kalder den interaktive
`run-browser-peer-public-validation.ps1` og afslutter med
`physical_validation_candidate_gate.py`.

Kræv i `validation/physical-validation-candidate-final-latest.json`:

```text
gate.passed=true
candidate_ready_for_fast_forward=true
release_validation_pending=true
release_complete=false
all_physical_evidence_complete=false
production_activation=false
summary.total=7
```

Stop her. Stage A udfører ingen repository- eller releaseoperationer.

## Beslutningspunkt

Kun efter en særskilt eksplicit beslutning må `main` fast-forwardes til præcis
Stage A-SHA'en, samme SHA tagges som `v2.0.13`, og det komplette signerede
release-sæt publiceres. Ændres SHA'en, er Stage A ugyldig.

## Stage B — publiceret 2.0.13

Følg den operative autoritet i `STAGE_B_UPDATER_EVIDENCE.md`.

Kildereleasen for appliance-transitionen er den signerede `2.0.12`, og målet er
`2.0.13`. Target-updaterens checksum og provenance verificeres før swap som den
aktuelle bootstrap-grænse. Server, supervisor og worker må ikke kopieres
manuelt; deres transition skal ske gennem updateren.

Versionsbumpet ændrer ikke automatisk #401's claim. Et særskilt automatisk
signed-release-to-signed-release self-update-bevis må kun hævdes, hvis #401's
egen gate faktisk er gennemført. Det blokerer ikke promotion af 2.0.13, medmindre
den authority ændres særskilt.

Stage B skal dokumentere:

1. normal update fra 2.0.12 til 2.0.13;
2. reboot på 2.0.13;
3. backend supervisor-restart;
4. worker supervisor-restart;
5. ugyldig update afvist før swap eller sund rollback til 2.0.13;
6. interruption/recovery uden manglende live executables;
7. bevarede data, credentials og schedules.

Følgende bypasses er forbudt:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

`ROLLBACK FAILED`, `manual_recovery`, en stående `update-transaction.json`,
manglende updater-markører eller hashdrift blokerer.

### Én fail-closed Stage B-indgang

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Launcheren kører i denne rækkefølge:

1. `freeze_check.py`;
2. `appliance_lifecycle_updater_chain.py`;
3. `physical_validation_campaign.py --mode verify`;
4. `physical_validation_final_gate.py`;
5. `stage_b_physical_gate.py`.

Kræv i `validation/stage-b-physical-final-latest.json`:

```text
schema=kaliv-stage-b-physical-final/v1
gate.passed=true
release_freeze_complete=true
updater_chain_complete=true
physical_campaign_complete=true
browser_peer_physical_complete=true
all_physical_evidence_complete=true
production_activation=false
summary.total=8
```

Kun denne schema-distinkte kvittering kan indgå i en senere separat
aktiveringsbeslutning. Den aktiverer stadig intet af sig selv.

## task_ui-beviset (T-021) — fulde krav

Verify-kampagnens ottende bevis kræver mere end telefonens flow; alle dele er
obligatoriske og fælder tavst hvis de mangler:

1. **To klienter:** task-UI-flowet observeres på BÅDE Android-appen og
   Windows-desktop-appen (`Kaliv-windows-x64-<version>.jar` fra releasen,
   verificeret mod `SHA256SUMS.txt`). Flow pr. klient: én Agent 3-opgave med
   tools til (surface, server-begrundelse, plan-review uden eksekvering,
   tool-status, Stop med terminal-tilstand, receipts) samt én normal chat-tur
   uden tools (`normal_chat_round_trip`).
2. **Evidensnote pr. klient** under `validation/agent3-task-ui-evidence/`
   (1 byte – 1 MB, repository-relativ, ingen symlinks) og notens SHA-256 i
   observationsfilens `evidence_sha256` — skabelonens `FILL_ME_64_HEX` fælder.
3. **Maskinproben** kører automatisk under valideringen og kræver et parret
   `MODELRIG_TOKEN` mod den kørende 2.0.13-backend.
4. Kandidat-triplen i observationsfilen skal matche den friske
   `frozen-candidate.json` — kør `freeze_check.py` FØR filen udfyldes.

## Efter Stage B-kæden: bring appliancen frem før verify

Interruption-trialet efterlader BY DESIGN kilden gendannet. Kør derfor den
normale opdatering (`modelrig-updater-windows-x64.exe -dir <appliance>`) efter
kæden, og verificér `healthz` = target-versionen, FØR kampagne-verify — ellers
fælder lifecycle på kørende version ≠ kandidat.


## Agent 4 (a4-25f) i kampagnen — de fysiske trin

Kampagnens Agent 4-kvalifikation stopper fail-closed, hvis operatørtrinnene
springes over; de er obligatoriske og kommer i denne rækkefølge:

1. **APK'en skal installeres på Pixel-enheden FØR parringstrinnet** —
   kampagnen bygger/bruger `app-a425f.apk` (pakken `dk.ternedal.modelrig.a425f`,
   separat fra hoved-appen) men kan ikke installere den for dig. Overfør og
   installér den, når stien vises.
2. **Par appen mod den viste server-URL** (`http://<LAN>:18080` — den
   isolerede A4-stack, ikke appliancens :8080) med engangskoden på skærmen.
   Tryk FØRST Enter, når appen viser parret.
3. `DeviceInfo`-trinnet venter derefter på Pixel-receiptet
   (`a4-25f-device-info.json`) fra den parrede app; udebliver det, er
   parringen ikke lykkedes — kør trinnet igen frem for at fortsætte.
4. Genkørsler af fixturen kræver `-Agent4ReplaceFixture` (fra 2.0.13) eller
   arkivering af `modelrig-a4-25f-evidence`-mappen først — fixturen nægter
   ærligt at overskrive eksisterende evidens.

## T-023 i kampagnen — operatørens rolle

T-023 kan ikke se UI'en og auto-godkender intet: hver case kræver de to
præcise operatørfraser og et kandidatbundet screenshot, når wizarden beder om
dem. Stop/fallback-proben tåler planner-varians (op til tre plan-forsøg fra
2.0.13); selve eksekverings-kontrakterne er uændret strikse.




## T-033 kræver en ANDEN Windows-bruger — vid det før kampagnen

T-033 er det fysiske bevis for DPAPI-beskyttet backup/restore af Agent 3's
hukommelse. Pointen med prøven er, at en anden Windows-konto (en anden SID)
IKKE kan læse det, den første konto har beskyttet — så den kan ikke køres
færdig fra én bruger.

Kampagnen gør det i tre trin og pauser selv mellem dem:

1. `prepare` kører automatisk som operatøren (samme-bruger backup/restore og
   plaintext-scan). Kampagnen stopper med gult og printer den præcise
   kommando til trin 2.
2. `probe` kører **som en anden lokal Windows-konto** mod en staging-bundle i
   `C:\Users\Public`. Nemmest fra samme skrivebord, uden at logge ud:

       runas /user:<ANDEN-BRUGER> "python \"C:\Users\admin\Desktop\ModelRig-git\scripts\proof_t033_current.py\" probe --campaign-id <ID>"

   Campaign-id'et står i kampagnens output. Kontoen skal findes på forhånd —
   en almindelig lokal standardbruger rækker, den behøver ikke admin.
3. Kør `START_PROOF_CAMPAIGN.cmd` igen fra ejer-sessionen; `collect` sker
   automatisk, kræver den eksakte operatørfrase, og kører den uafhængige gate.

Findes der ingen anden konto på riggen, skal den oprettes FØR kampagnen
startes — ellers står T-033 rød, og `physical_campaign_complete` kan ikke
blive sand.

## Agent 4 i 2.0.13: brug den kandidatbundne APK

CI bygger en a425f-APK pr. push til proof-branchen (workflow `a425f-apk`,
artefakt `kaliv-a425f-apk-<exact-sha>`). Brug DEN til kampagnen — ikke en
APK fra en tidligere æra, selv om `Prepare` accepterer den: evidensens
`apk_sha256` skal svare til kandidaten.

    gh run download <run-id> -n kaliv-a425f-apk-<exact-sha> -D $env:TEMP\a425f-<kort-sha>

`Prepare` installerer den selv over adb, når `-ApkPath` peger på filen.

## T-023: kør ALTID gennem proof-wrapperen

`scripts/proof_t023_current.py` er den eneste rigtige indgang under en
kampagne. Den overskriver wizardens `ensure_candidate` og pinner DEN
AKTUELLE checkout.

Kører man `agent3_termination_ui_physical_one_click.py` direkte, gør
wizarden det, den er bygget til uden for kampagnen: skifter til
`agent/t023-termination-physical-operator` og binder evidensen til den
branchs egen kandidat (observeret 30/08: version 1.58.146). Evidensen er
så bundet til en helt anden æra og ubrugelig for kampagnen — og checkouten
skal manuelt tilbage til proof-branchen bagefter.

Task-UI-flaget kommer ikke fra wrapperens miljø: worker-cmd'en bygges med
en eksplicit env-blok, så flaget rejser som `-EnableTaskUi` fra wizardens
`start_stack`-kald (jf. kontraktgaten `workflow_agent3_t023_task_ui_enable`).

## A4-25f: den fulde kvalifikationskæde og aktiveringstrappen

Rækkefølgen er ikke valgfri — hvert trin skriver den kvittering, det næste
kræver, og to af dem blev først opdaget ved at drive kæden igennem 30/08:

1. `Prepare` (med `-Replace`, eller arkivér `modelrig-a4-25f-evidence` først)
   — bygger fixture, isoleret stack på `:18080`, installerer APK'en over adb
   og viser en engangs-parringskode.
2. **Par a425f-appen på enheden** mod den viste server-URL. Uden dette
   fejler `DeviceInfo` med "Pixel-receipt blev ikke tilgængelig".
3. `DeviceInfo` → `Grant` → `RunMatrix`.
4. **`agent4_a4_25f_cursor_matrix.ps1` — FØR `Stop`.** Den kræver
   `matrix_complete` i state og en installeret app; `Stop` afinstallerer
   appen og nulstiller state, så efter `Stop` er trinnet umuligt uden en
   helt ny gennemkørsel.
5. `Stop` — rydder processer, firewall-regel, isoleret APK og backend-store,
   men bevarer evidensfilerne.
6. `agent4_a4_25f_cleanup_verify.ps1` — et SELVSTÆNDIGT trin, som skriver
   `a4-25f-cleanup.json`. `Stop` skriver den ikke.
7. `agent4_a4_25f_finalize_evidence.py` — auditerer hele kæden og skriver
   kvalifikationskvitteringen.

Kæden kræver adb hele vejen. Kablet USB er den stabile vej; trådløs
fejlfinding falder ud, når telefonens skærm slukker, og skal så parres og
forbindes igen med de to porte enheden selv viser.

### Aktiveringstrappen efter grøn kvalifikation

`finalize_evidence` skriver `human_go_recorded: false` og
`human_go_authorized: false` med vilje. Derfra:

1. **Menneskelig GO:** `agent4_a4_25f_record_decision.py --decision GO
   --reviewer <navn> --reason <begrundelse>`. Scriptet siger det selv: en GO
   accepterer kun den fysiske kvalifikationskampagne — den autoriserer
   aldrig production activation.
2. **Aktivér operator-læsefladen:** `KALIV_AGENT4_OPERATOR_API=1` i
   appliancens env. Default-off, og kun den eksakte streng `"1"` tæller.
   Mounten er additiv, GET-only og komponerer ingen scheduler, kø eller
   baggrundstråd.
3. **Production activation** er et selvstændigt, senere skridt med egen
   bevisrunde bag aktiverings-flip-værnet.


## Task-UI-beviset: hvor operatøren finder de tretten krav

`scripts/agent3_task_ui_validation.py` kræver tretten observationer pr.
klient. De ligger IKKE i chat-panelet, men på den dedikerede
operatør-skærm `Agent3TaskScreen` ("Kaliv Opgaver"), som bruger sin egen
`Agent3ReadonlyTaskClient` mod task-fladen.

**Sådan åbnes den.** Fra chattens ⋮-menu → **Opgaver** (vises med parret rig
i rig-mode). Alternativt via dyb-link eller Intent:

    adb shell am start -n dk.ternedal.modelrig/.MainActivity -a android.intent.action.VIEW -d "kaliv://tasks"

(`-n` er nødvendigt: manifestet registrerer kun `kaliv://pair` som dyb-link;
`tasks`, `schedules` og `persons` løses via launcher-genvejene og
Intent-extras, ikke via en intent-filter.)

Chattens Agent-række i Kapaciteter er noget andet: den er KUN klikbar når
riggen er parret, mode er `rig`, OG der står tekst i skrivefeltet — agenten
planlægger for en besked, ikke for ingenting. Med tomt felt sker der intet,
og undertitlen forklarer det ikke (kendt UX-hul; ændringen venter på at
Kapaciteters golden-screenshots kan genskabes).

**Hvor kravene ses på skærmen:**

| Krav | Hvor |
|---|---|
| `selected_surface_visible` | Topkortets overskrift: "Agent 3 read-only valgt af serveren" (grøn) eller "Agent 2 fallback" (gul), plus `Aktiv surface`-rækken |
| `server_reason_visible` | Linjen under overskriften: serverens `reason` ordret, fx `agent3_readonly_selected`; `readiness_unavailable` hvis readiness ikke kunne hentes |
| `fallback_visible` | `Fallback`-rækken i topkortet, og overskriftens gule tilstand når fladen ER faldet tilbage |
| `replans_visible` | `Replans`-rækken (og `Retry-events` ved siden af) |
| `plan_review_visible` | `Lav plan-preview` → plan-kortet med de foreslåede trin |
| `preview_did_not_execute` | Preview'et alene ændrer intet; `Start` er et separat, serverbundet klik |
| `no_write_controls` | Feltets hjælpetekst: kun lokale, idempotente read-tools kan godkendes af serveren; write-trin kan ikke startes |
| `tool_status_visible` | Trin-status i kørselskortet efter start |
| `stop_visible` | `Stop` på plan-kortet — serverautoriseret, ikke en klient-annullering |
| `stop_after_fallback` | Stop forbliver på skærmen i fallback-tilstand: pollingen stopper først når serverens kvittering siger det, aldrig fordi HTTP-kaldet blev afbrudt |
| `receipts_visible` | `ReceiptCard` — vises både for preview og for kørselssnapshot |
| `terminal_outcome_visible` | Kørselssnapshottets terminal-tilstand |
| `normal_chat_round_trip` | Noten nederst: normal chat er urørt — bekræftes ved én almindelig besked i chatten uden tools |

Krydserne sættes i `validation/agent3-task-ui-observations.json` og må kun
sættes for det, der ER set. Efter redigering køres
`scripts/agent3_task_ui_validation.py` med en frisk device-token; den
binder observationerne til kandidatens sha og hasher evidensfilerne.
