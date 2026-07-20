#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{relative}: expected exactly one replacement match, found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "DEVICE_TEST.md",
    '''## 1.4 Frys kandidaten først

**Gør:** før du overhovedet rører riggen, bekræft at det du er ved at validere er
én sammenhængende, CI-grøn kandidat — ikke en halv tilstand eller en commit hvis
CI fejlede. Evidensen er code-bound: validerer du én version og shipper den næste,
er beviset ugyldigt uden at du kører noget om. Denne tjekker det, uden at ændre
noget:

```cmd
python scripts\\freeze_check.py
# Gitless rig (ZIP): freeze_check kører selv i API-mode og skriver
# validation\\frozen-candidate.json — preflight og kampagnen arver den.
```

**Bør se:** `FROZEN` — ren working tree, ens versionsstempler, kandidaten er på
`origin/main`, og både `ci` og `codeql` verificeret GRØNNE på præcis denne
commit. **Uden `GITHUB_TOKEN`/`GH_TOKEN` er dommen IKKE FROSSET** (F-1005):
frysens pointe ER exact-head-beviset, så sæt tokenet
(`$env:GITHUB_TOKEN = "<token>"`) og kør igen.

**Fejler noget →** hver `FAIL` har en `->`-linje. De almindelige: ucommittede
ændringer (commit eller kassér dem), versionsdrift (kør `version_tool.py sync`),
eller rød CI (ret den før du validerer). Pointen: du bruger ikke rig-tid på at
validere en kandidat der flytter sig under dig.

Når kandidaten er `FROZEN`: stop med at shippe, og gå videre til preflight.

---''',
    '''## 1.4 Frys kandidaten først

Promotionen er todelt. Følg den autoritative
[`STAGED_PHYSICAL_PROMOTION.md`](STAGED_PHYSICAL_PROMOTION.md).

Før release bruger Stage A den eksplicitte exact-SHA-gate:

```powershell
$CandidateSha = "<CANDIDATE_SHA>"
python scripts\\candidate_freeze_check.py --expected-sha $CandidateSha
```

Den kræver ren kandidat, seneste `origin/main` som ancestor og grønne `ci`,
`agent3-diagnostics`, `agent3-full-diagnostics` og `codeql` på præcis SHA'en.
Den kan kun skrive `release_validation_pending=true` og
`production_activation=false`.

Kør ikke `freeze_check.py` på den upublicerede kandidat. Den eksisterende
release-freeze hører til Stage B, efter at samme SHA er fast-forwardet til
`main` og publiceret som release.

---''',
)

replace_once(
    "DEVICE_TEST.md",
    '''## 1.7 Kampagnen samlet — én kandidat, ét bevis

Den fulde fysiske kampagne (Agent 3, model-eval, lifecycle inkl.
reboot/rollback, voice, RAG) har sin egen kanoniske runbook:
[`PHYSICAL_VALIDATION_CAMPAIGN.md`](PHYSICAL_VALIDATION_CAMPAIGN.md) — kør
delene dér, og saml til sidst med `scripts/physical_validation_campaign.py`
(read-only aggregator: kræver samme VERSION, samme Git-SHA og samme worker
`code_sha256` på tværs af alle rapporter, ellers intet samlet bevis).

Rækkefølgen på dagen: **§1.4 frys → §1.5 preflight → kampagnens dele →
§1.6 scheduler-piloten → aggregatoren**.

**Hullet er lukket (19/7):** aggregatoren har nu et `scheduler_pilot`-slot.
Efter §1.6-piloten: kør `scripts/scheduler_pilot_report.py` med de to
schedule-id'er og en lille manual-observations-fil (se
`PHYSICAL_VALIDATION_CAMPAIGN.md` sektion 7) — så indgår T-019-beviset i
`--mode verify` på lige fod med de øvrige seks, bundet til samme kandidat.

---''',
    '''## 1.7 Kampagnen samlet — staged kandidat og release

Den autoritative rækkefølge står i
[`STAGED_PHYSICAL_PROMOTION.md`](STAGED_PHYSICAL_PROMOTION.md):

- Stage A samler preflight, Agent 3, model-eval, voice, RAG og scheduler-pilot
  med `physical_validation_candidate_campaign.py`, og tilføjer browserbeviset
  med `physical_validation_candidate_gate.py`.
- Stage B køres først efter exact-SHA fast-forward og release. Her tilføjes
  lifecycle/updater-beviset, hvorefter `physical_validation_campaign.py` og
  `physical_validation_final_gate.py` producerer det endelige otte-bevis.

Begge lag kræver samme VERSION, Git-SHA og worker `code_sha256`. En ny commit
mellem lagene ugyldiggør kandidatbeviset.

---''',
)

replace_once(
    "PHYSICAL_VALIDATION_CAMPAIGN.md",
    '''Denne runbook samler de syv fysiske **Prove**-opgaver T-004, T-005, T-006,
T-007, T-040, T-043 og T-019. De enkelte harnesses har fortsat deres egne
detaljerede
runbooks; denne kampagne sørger for, at deres rapporter faktisk beskriver den
samme version, Git-commit og worker-kode.
''',
    '''Denne runbook samler de syv fysiske **Prove**-opgaver T-004, T-005, T-006,
T-007, T-040, T-043 og T-019. De enkelte harnesses har fortsat deres egne
detaljerede
runbooks; denne kampagne sørger for, at deres rapporter faktisk beskriver den
samme version, Git-commit og worker-kode.

> **Scope:** Dette er Stage B's fulde releasekampagne. En upubliceret kandidat
> starter i [`STAGED_PHYSICAL_PROMOTION.md`](STAGED_PHYSICAL_PROMOTION.md), hvor
> seks ikke-releasebundne beviser og T-032-browserbeviset samles først. T-006
> lifecycle kan først bevises, når samme SHA er publiceret som en nyere release.
''',
)

replace_once(
    "PHYSICAL_VALIDATION_CAMPAIGN.md",
    '''## 0. Frys kandidat og opret kampagnechecklisten

Fra repositoryets rod:

```powershell
python scripts\\freeze_check.py

**Riggen er gitless** (kilderne ankommer som ZIP): freeze_check opdager det
selv og kører i API-mode — den slår den publicerede release `v{VERSION}` op,
verificerer at sha'en er på main og at ci+codeql var grønne på præcis den, og
skriver ved FROZEN `validation\\frozen-candidate.json`. Preflight og
aggregatoren læser den fil i stedet for git — kæden er eksplicit:
freeze-gaten fældede dommen, resten arver den. Det ene der IKKE kan
verificeres uden git er working-tree-renhed; det navngives som note
(trust-ankeret er den officielt hentede, urørte ZIP) i stedet for at grønnes.
python scripts\\physical_validation_campaign.py `
  --mode prepare `
  --report validation\\physical-validation-campaign-latest.json
```

`prepare` passer kun, når kandidaten er coherent, working tree er rent, og alle
rapporter der allerede findes matcher kandidaten. Manglende fremtidige rapporter
vises som `missing`, men gør ikke prepare-gaten rød. En eksisterende stale eller
mismatched rapport gør gaten rød og skal flyttes/slettes eller køres igen.

Rapportens `commands`-felt indeholder den autoritative rækkefølge og de
forventede rolling paths.
''',
    '''## 0. Frys den publicerede release og opret releasechecklisten

Denne sektion er Stage B. Kør først Stage A i `STAGED_PHYSICAL_PROMOTION.md`,
og fortsæt kun efter exact-SHA fast-forward, tag og offentlig release.

```powershell
python scripts\\freeze_check.py
python scripts\\physical_validation_campaign.py `
  --mode prepare `
  --report validation\\physical-validation-campaign-latest.json
```

`freeze_check.py` kræver, at HEAD er præcis det publicerede `v{VERSION}`-tag,
at releasen ikke er draft, at SHA'en er på `origin/main`, og at exact-head
`ci` samt `codeql` er grønne. På en gitless release-ZIP verificerer den det
lokale træ mod release-committen og skriver `validation\\frozen-candidate.json`.

`prepare` accepterer manglende fremtidige rapporter, men stale, røde eller
candidate-mismatched rapporter blokerer.
''',
)

replace_once(
    "PHYSICAL_VALIDATION_CAMPAIGN.md",
    "## 4. T-006 — reboot, supervisor, updater og rollback\n",
    '''## 4. T-006 — reboot, supervisor, updater og rollback

> **Kun Stage B:** updaterens gyldige update kræver, at kandidaten er den
> nyeste offentlige release og har en højere semver end den kørende rig. Kør
> aldrig denne del mod en upubliceret branch eller ved manuel binærkopiering.
''',
)

replace_once(
    "AGENT3_RIG_VALIDATION.md",
    "- `main` eller det konkrete release-tag, der skal valideres, er checket ud.",
    "- Den exact-SHA pre-release-kandidat fra `STAGED_PHYSICAL_PROMOTION.md` Stage A eller det konkrete publicerede release-tag fra Stage B er checket ud.",
)

result = subprocess.run(
    [sys.executable, "scripts/version_tool.py", "set", "1.58.141"],
    cwd=ROOT,
    check=False,
)
if result.returncode != 0:
    raise SystemExit(result.returncode)
