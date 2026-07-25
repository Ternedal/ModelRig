# Rig-dag — kørebog

**Skrevet 25/07-2026 mod `main @ a7f2495` og kandidat `8e40103`.**

Din tid ved maskinen er projektets knappe ressource — fem P0-opgaver er åbne og
alle fem er `[RIG]`. Der er kommet mere at teste i dag, så det her er
rækkefølgen, og hvorfor den er sådan.

---

## Det du skal vide først

**Kandidaten `8e40103` indeholder ikke dagens arbejde.** Målt:

| | På kandidaten? |
|---|---|
| Workflow-harness (runner, adapter, specs) | **nej** |
| Sols completion-kontrakt | **nej** |
| Agent 3-cockpittet | **nej** |
| Desktop-designet (titelbjælke, ikon-rail, 1240dp) | **nej** — den har den gamle `KalivScreens.kt` og `1000.dp` |

Det er ikke en fejl. Kandidaten blev frosset i går, og alt fra i dag er landet
på `main` bagefter. Men det betyder:

> **Rig-dagen på `8e40103` kan ikke teste noget af det jeg har bygget i dag.**
> Den validerer kandidaten. Dagens arbejde skal med i næste udgivelse.

Derfor er kørebogen delt i to pas i **samme** session. Du er allerede ved
maskinen; to separate rig-dage ville koste dobbelt.

---

## Pas 1 — luk kandidaten (P0, det der blokerer alt)

Clean checkout af **præcis** `8e40103`. Ikke main, ikke en merge.

```powershell
git fetch origin agent/unified-candidate-1.58.145
git checkout 8e40103          # detached — det er meningen
```

1. **`START_STAGE_A_TEST.cmd`**
2. **`START_REMAINING_PHYSICAL_TESTS.cmd`** — voice + scheduler-pilot er det
   udestående. Voice fejlede sidst med `401 invalid token` på Pixel'en; hav en
   frisk parring klar.
3. **Gennemgå beviserne** før du beslutter noget:
   - `validation/physical-validation-candidate-final-latest.json`
   - `validation/agent3-readonly-pilot-latest.json`
   - `validation/scheduler-pilot-latest.json`
4. **Stop.** PR #161 siger det selv: *"Only after a separate explicit decision
   may the exact SHA be fast-forwarded, tagged and released."*

### T-006 forced recovery — ét dobbeltklik, ~2 minutter

**`START_FORCED_RECOVERY.cmd`** (ligger på main; kør den fra 1.58.146-checkouten
i pas 2, ikke fra kandidaten — den findes ikke dér).

Den kører hele forsøget selv: starter en proces, lader den claime en occurrence,
**dræber den hårdt** med `taskkill /F`, genstarter hurtigt, venter lease-TTL'en
ud, genstarter igen, og printer en dom. Du skal ikke gøre noget undervejs.

Riggens egne schedules, jobs og audit røres **ikke** — alt kører i en
midlertidig mappe der slettes bagefter.

Forventet: **6/6 OK**. Den vigtigste linje er den næstsidste:

```
lease-vinduet er reelt: en genstart inden for 90s springer recovery over
```

Det er ikke en fejl — det er beskyttelsen mod at afskrive en *levende* workers
kørsler. Men det betyder at en worker der dør og genstartes med det samme først
får afklaret sin occurrence ved **næste** opstart. Kørt på Linux 25/7 (6/6);
Windows-kørslen er det der mangler, fordi fillåse og NTFS opfører sig anderledes
under abrupt død.

### Når du beslutter at promovere

```powershell
git tag -a v1.58.145 8e40103 -m "v1.58.145"
git push origin v1.58.145
```

**Tagget skal sidde direkte på `8e40103`.** Ikke på en merge-commit — dens træ
ville indeholde dagens docs-delta og fælde den byte-eksakte attestation
(F-1802/F-1503). `--ff-only` er ikke længere mulig, fordi main er rykket; det er
selvforskyldt, og det er derfor tagget går direkte på SHA'en i stedet.

---

## Pas 2 — dagens arbejde, samme session

Først nu giver det mening at skære `1.58.146` fra main, som **har** alt.

```powershell
git checkout main && git pull
python scripts\version_tool.py set 1.58.146
python scripts\activation_readiness.py
python scripts\current_state.py
python scripts\route_inventory.py
# bump + regenerering SKAL i samme commit som tagget peger på — det var
# præcis fejlen der gjorde v1.58.143 til en draft med 0 assets
```

### 2a. Første workflow-baseline — projektets første rigtige tal

```powershell
set MODELRIG_TOKEN=<token>
python scripts\workflow_runner.py --model hermes3:8b ^
    --out validation\workflow-run-latest.json
python scripts\workflow_eval.py --transcripts validation\workflow-run-latest.json
```

14 workflows. Det du får ud er en **completion rate** — første gang projektet
har et tal for om Kaliv faktisk *løser* opgaver, ikke om den vælger det rigtige
værktøj. Forvent ikke 14/14. Tallet er interessant fordi det er ærligt.

**Kig især på W-10.** Den beviser at `delete_model` ikke kan køre uden et kort.
Den godkender aldrig — den skal ende `blocked`. Hvis den nogensinde ender
`completed` med værktøjet udført, så stop og sig til.

### 2b. Desktop-designet

```powershell
cd desktop && .\gradlew run
```

Vindue **1240×820**, 40dp titelbjælke øverst i fuld bredde. Tre skærme i
venstre rail: chat (246dp rail m. labels) · agent (70dp ikon-rail) ·
computer-use (70dp ikon-rail). `CLIENT_BUILD_AND_TEST.md` har tabellen over hvad
der skal ses.

Jeg har kørt alle tre headless på Linux og målt kolonnegrænserne, men
**fontrendering og vinduesdekoration på Windows har jeg aldrig set.**

### 2c. Agent 3-cockpittet (valgfrit, kræver flaget)

```powershell
set KALIV_AGENT3_ENABLED=1
```
Slå så **"Agent-skærm bruger Agent 3 (udvikler)"** til i Indstillinger. Uden
flaget siger cockpittet det selv i stedet for at fejle kryptisk.

Det er det eneste sted `"Agent-plan · 2 af 4 trin"` kan virke — V2-loopet kender
ikke totalen. Er flaget slukket, er V2-cockpittet stadig standard, og normal
chat er urørt uanset.

---

## Pas 3 — efter tagget

1. Merge **#157** (fastapi, verificeret lokalt) og **#13** (sqlite-jdbc)
2. Så **#5/#7/#9** (Actions-bumps) — og lad næste release-kørsel følge lige
   efter, for `build-and-release.yml` bruger de samme actions og kører **kun på
   tags**, så en breaking change dér er ikke fanget endnu
3. **#135** adopterer jeg som host-ejer, rebaser og kører gennem globben
4. **#156** blokerer hele den 6-lag dybe control-center-kæde

---

## Beslutninger kun du kan tage

- **T-006:** accepter DB-evidens for recovery, eller kør de tre minutters
  forced recovery. Det er den sidste 1.0-blocker.
- **1.0:** 145 patches på 1.58 gør versionsnummeret informationsløst.
- **Research-sporet** (1.564 linjer): staged eller skæres væk? Der er intet
  beslutningsspor ud over én linje i ROADMAP.
- **D3/D4** fra ROADMAP's åbne beslutninger.

---

## Hvis noget fejler

`TROUBLESHOOTING.md` har mønstrene. To fra nyere tid der er værd at huske:

- **Git-løs rig:** `subprocess.run` **kaster** FileNotFoundError når git slet
  ikke findes — den fejler ikke med en returkode. Rettet i 1.58.142, men sæt
  `MODELRIG_SHA` hvis noget alligevel klager over proveniens.
- **Readiness-drift:** hvis en release fejler på `ACTIVATION_READINESS.md`, er
  bump og regenerering ikke i samme commit som tagget. Det gjorde v1.58.143 til
  en draft med 0 assets.
