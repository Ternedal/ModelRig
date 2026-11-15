# RIGDAG_SIMPEL — ModelRig 2.0.20

> **Release-forberedelse, ikke fysisk godkendelse:** `v2.0.20` er endnu ikke tagget eller publiceret, og `physical-proof/2.0.20` findes først efter publicering. Kør ikke promotion eller tagging ud fra denne vejledning; kræv ny exact-head- og rig-evidens for v2.0.20.

> **v2.0.20 følger D3-rækkefølgen fra 2.0.19** (Anders, 8/11-2026, #2275 6726564262) og Anders' gate for medier: han tester fysisk, når billede og video er med i en release (9/11-2026, #2275 6751908309).
> - **Det kræves før tag og publicering:** grøn exact-head CI på RC-SHA'en og Anders' særskilte release-go. RC-SHA'en er `main` efter merge af bump-PR'en (`release/kaliv-v2.0.20-prep-20261114`), ikke denne gren via fast-forward. Lige efter mergen står `main` stille, til Anders har kørt `verify-repository-authority.ps1` (#2390, fund 5). Proceduren står i #2275.
> - **Hvad denne vejledning så er:** Stage A/B nedenfor er **ikke** en forudsætning for tagget `v2.0.20`. Den er den fysiske validering, der kører **efter** publicering, og medietesten (#2390) kører på samme SHA.
> - **Det gælder stadig:** ingen launcher aktiverer produktion (`production_activation=false`), og der skabes intet release uden Anders' go.

Dette er den korte operatorindgang. Den autoritative rækkefølge og alle
fail-closed grænser står i `STAGED_PHYSICAL_PROMOTION.md`; Stage B-detaljerne
står i `STAGE_B_UPDATER_EVIDENCE.md`.

## Kandidat

- version: `2.0.20`;
- kandidat: den publicerede RC-SHA, den commit tagget `v2.0.20` peger på;
- branch: `physical-proof/2.0.20`, oprettet efter publicering på RC-SHA'en; den gren Stage A-operatoren kræver;
- freeze: `candidate_freeze_check.py` grøn på exact SHA;
- exact SHA: læses fra den fetch'ede `origin/physical-proof/2.0.20`, matches mod tagget og må aldrig gættes eller kopieres fra ældre evidens;
- produktion: ikke aktiveret.

Evidens fra 2.0.12 eller fra en tidligere ugyldiggjort 2.0.13-head må ikke
genbruges.

## Blok 0 — lås checkouten

Kør først, når `v2.0.20` er publiceret og verificeret, og
`physical-proof/2.0.20` findes på origin (#2275).

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
git fetch origin
git fetch --force origin tag v2.0.20
$RcSha = (git rev-parse "v2.0.20^{commit}").Trim()
if ($RcSha.Length -ne 40) { throw "v2.0.20 er ikke tagget paa origin" }
git switch physical-proof/2.0.20
git pull --ff-only origin physical-proof/2.0.20
$CandidateSha = (git rev-parse HEAD).Trim()
$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.20).Trim()
if ($CandidateSha -ne $RemoteCandidateSha) { throw "Lokal candidate matcher ikke origin/physical-proof/2.0.20: local=$CandidateSha remote=$RemoteCandidateSha" }
if ($CandidateSha -ne $RcSha) { throw "physical-proof/2.0.20 peger ikke paa den publicerede v2.0.20: branch=$CandidateSha tag=$RcSha" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "2.0.20") { throw "Forkert version" }
python scripts/candidate_freeze_check.py --expected-sha $CandidateSha
if ($LASTEXITCODE -ne 0) { throw "Candidate er ikke frozen paa exact SHA $CandidateSha" }
```

`v2.0.20`, `origin/physical-proof/2.0.20` og den grønne
`candidate_freeze_check.py` er den aktuelle kandidat-authority. Release-prep-grenen
`release/kaliv-v2.0.20-prep-20261114`, historiske freeze-PR'er eller ældre
2.0.13-heads må ikke bruges som SHA-reference.

Freeze-kontrollen og operatoren kræver, at den aktuelle `origin/main` er
indeholdt i kandidaten. Efter publicering holder det kun, så længe `main` står
på RC-SHA'en.

> **Freeze-vinduet er ophævet 12/11-2026 (Anders, #2275-kommentar 6816274261).**
> Reglen om, at intet merges til `main` fra tagget, til Stage A er grøn, gælder
> ikke længere. Anders tester ikke fysisk, før billede og video er i en release
> (#2275-kommentar 6751908309), og de lå i de PR'er, reglen holdt ude. Når `main`
> har flyttet sig fra RC-SHA'en, kan Stage A ikke køres på `v2.0.20`; næste
> release tagges og valideres på sin egen SHA.

Er `main` flyttet, stopper kontrollen. Den må ikke omgås; stop og rapportér i
#2275.

Fra første fysiske bevis til promotion eller abandonment må branchen ikke
pushes, rebases, force-pushes, merges, amendes eller redigeres. Enhver head-
ændring ugyldiggør alle receipts og rapporter.

## Blok 1 — Stage A

Dobbeltklik:

```text
START_STAGE_A_TEST.cmd
```

Ved trin 4/8 forsøger wizarden først selv at minte et device-token mod
`127.0.0.1:8080` via loopback pairing. Hvis backenden er konfigureret med
`MODELRIG_ADMIN_KEY`, sendes den process-lokale nøgle som `X-Admin-Key`; værdien
vises eller gemmes ikke af wizarden.

Hvis auto-mint fejler, bruger du wizardens skjulte token-prompt. Har du mintet
et token manuelt i en separat PowerShell, kopierer du kun tokenværdien og
indsætter den direkte i den allerede kørende wizard. `$env:MODELRIG_TOKEN` i
et andet PowerShell-vindue kan ikke ændre en allerede kørende wizard.

Wizard'en samler og genoptager de seks kandidatbeviser samt det interaktive
browserbevis. De menneskelige handlinger er fortsat de fysiske observationer:
voice-fraser, Pixel-matrix, den afgrænsede approval, scheduler-timing og det ene
offentlige browserkald.

Kræv til sidst:

```text
candidate_ready_for_fast_forward=true
release_validation_pending=true
release_complete=false
all_physical_evidence_complete=false
production_activation=false
summary.total=7
```

Feltnavnene er gate-værktøjets. Under D3 betyder
`candidate_ready_for_fast_forward=true` kun, at kandidatgaten er grøn på
RC-SHA'en; der fast-forwardes intet.

Stage A merger, tagger, releaser og aktiverer intet.

## Beslutningspunkt

Under D3 ligger beslutningspunktet før Stage A: Anders' særskilte release-go på
grøn exact-head CI på RC-SHA'en. Først derefter tagges `v2.0.20` og publiceres
som et komplet signeret release-sæt. Et rødt fysisk resultat ændrer ikke den
publicerede release af sig selv; det rapporteres i #2275, og den videre
handling er Anders' beslutning.

## Blok 2 — Stage B

**Før Stage B: start recovery-soak-prøvetagningen** (V1 gate 9, #2390). Vinduet
skal række hen over Stage B's reboot, backend- og worker-genstart og
afbrydelse. Startes den først bagefter, kræver gate 9 en hel ny Stage B. Kør
smoke-trinet og start prøvetagningen efter
`docs/KALIV_RECOVERY_SOAK_QUALIFICATION.md` §0 og §1
(`scripts\kaliv_recovery_soak_collector.py`), og lad den køre videre under
Stage B. Collectoren sender kun GET til loopback og starter, stopper eller
aktiverer intet.

Kildereleasen er den signerede 2.0.12; target er 2.0.20. Target-updaterens
checksum og provenance verificeres som den autoritative bootstrap-grænse, før
server, supervisor og worker må flyttes gennem updateren. Stage B-runbooken er
autoritet for den præcise updater-/self-update-semantik; der må ikke håndkopieres
binaries som genvej.

Dobbeltklik:

```text
START_STAGE_B_TEST.cmd
```

Efter evidensindsamlingen køres:

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Kræv:

```text
schema=kaliv-stage-b-physical-final/v1
status=complete
gate.passed=true
release_freeze_complete=true
updater_chain_complete=true
strict_evidence_complete=true
physical_campaign_complete=true
browser_peer_physical_complete=true
all_physical_evidence_complete=true
production_activation=false
summary.total=9
```

Det særskilte automatiske signed-release-to-signed-release self-update-bevis
forbliver under #401 og må ikke antages ud fra versionsbumpet alene. Det
blokerer ikke promotion af 2.0.20, medmindre #401's authority ændres særskilt.

## Stopregler

Stop ved første afvigelse og gem den rå log. Brug aldrig:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

Et grønt fysisk resultat aktiverer ikke Agent 3, DevControl eller andre
dormante capabilities. Aktivering er altid en separat beslutning.
