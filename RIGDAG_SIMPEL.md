# RIGDAG_SIMPEL — ModelRig 2.0.12

Dette er den korte operatorindgang. Den autoritative rækkefølge og alle
fail-closed grænser står i `STAGED_PHYSICAL_PROMOTION.md`; Stage B-detaljerne
står i `STAGE_B_UPDATER_EVIDENCE.md`.

## Kandidat

- version: `2.0.12`;
- branch: `physical-proof/2.0.12`;
- freeze: `candidate_freeze_check.py` grøn på exact SHA;
- exact SHA: læses fra den fetch'ede `origin/physical-proof/2.0.12` og må aldrig gættes eller kopieres fra ældre evidens;
- produktion: ikke aktiveret.

Evidens fra 2.0.10 eller fra en tidligere ugyldiggjort 2.0.12-head må ikke
genbruges.

## Blok 0 — lås checkouten

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
git fetch origin
git switch physical-proof/2.0.12
git pull --ff-only origin physical-proof/2.0.12
$CandidateSha = (git rev-parse HEAD).Trim()
$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.12).Trim()
if ($CandidateSha -ne $RemoteCandidateSha) { throw "Lokal candidate matcher ikke origin/physical-proof/2.0.12: local=$CandidateSha remote=$RemoteCandidateSha" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "2.0.12") { throw "Forkert version" }
python scripts/candidate_freeze_check.py --expected-sha $CandidateSha
if ($LASTEXITCODE -ne 0) { throw "Candidate er ikke frozen paa exact SHA $CandidateSha" }
```

`origin/physical-proof/2.0.12` og den grønne `candidate_freeze_check.py` er den
aktuelle kandidat-authority. Historiske freeze-PR'er eller ældre 2.0.12-heads
må ikke bruges som SHA-reference.

Fra første fysiske bevis til promotion eller abandonment må branchen ikke
pushes, rebases, force-pushes, merges, amendes eller redigeres. Enhver head-
ændring ugyldiggør alle receipts og rapporter.

## Blok 1 — Stage A

Dobbeltklik:

```text
START_STAGE_A_TEST.cmd
```

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

Stage A merger, tagger, releaser og aktiverer intet.

## Beslutningspunkt

Kun efter en særskilt eksplicit beslutning må præcis Stage A-SHA'en
fast-forwardes til `main`, tagges `v2.0.12` og publiceres som et komplet
signeret release-sæt.

## Blok 2 — Stage B

Kildereleasen er 2.0.10; target er 2.0.12. Fordi den gamle updater er fra
før self-update-support, installeres 2.0.12-updateren én gang som verificeret
bootstrap. Server, supervisor og worker må kun flyttes gennem updateren.

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
gate.passed=true
release_freeze_complete=true
updater_chain_complete=true
physical_campaign_complete=true
browser_peer_physical_complete=true
all_physical_evidence_complete=true
production_activation=false
summary.total=8
```

Det automatiske signed-release-to-signed-release self-update-bevis er deferred
til #401 og kræver en senere signeret target-version. Det blokerer ikke
promotion af 2.0.12.

## Stopregler

Stop ved første afvigelse og gem den rå log. Brug aldrig:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

Et grønt fysisk resultat aktiverer ikke Agent 3, DevControl eller andre
dormante capabilities. Aktivering er altid en separat beslutning.
