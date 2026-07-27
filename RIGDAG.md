# RIGDAG.md — kørebog

**Skrevet ud fra hvad der faktisk står i koden**, ikke hvad jeg troede. Hvert
krav herunder er slået op i den gate der håndhæver det.

Kandidat: **`60f9b00`** (1.58.145, inkl. voice-fixet). Alle fire CI-gates grønne.

---

## Det du skal vide før du starter

**Seks beviser skal i hus**, alle bundet til kandidatens SHA:

```
preflight · agent3 · model_eval · voice · rag · scheduler_pilot
```

**De holder i 7 dage.** `--max-age-hours` er 168 som default, så du behøver ikke
klare det i én session. Men **alle seks skal bære samme `git_sha`** —
kampagnen sammenligner hvert bevis mod kandidaten
(`_expect_equal(..., "candidate.git_sha", ...)`). Ændres koden, dør de alle.

**Derfor er alt fra 25/7 ugyldigt.** Voice-fixet gav ny SHA. Det er prisen for
fejlen, ikke for noget du gjorde.

---

## Opsætning — én gang, i rækkefølge

### 1. Checkout det du vil validere

**[27/7 — kandidat-modellen er ovre.]** `agent/unified-candidate-1.58.145` blev
fast-forwardet ind i main, og main er siden gået 35+ commits videre. Checkout
`60f9b00` validerer nu gammel kode. Tag i stedet det tag du vil have beviser
for:

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
git fetch origin --tags
git checkout <tag>             # fx det seneste, se VERSION eller GitHub releases
git rev-parse --short HEAD     # skriv den ned; beviserne bindes til den
git status --porcelain         # SKAL være tom
```

"detached HEAD" er meningen. Er arbejdstræet ikke rent, kan beviset ikke
reproduceres — one-click'en i "Kør beviserne" blokerer på netop det.

### 2. Byg backenden fra checkouten

**Springes dette over, validerer du forkert kode.** 25/7 kørte riggen 1.58.141
mens kandidaten var 1.58.145.

```powershell
go build -C backend -trimpath -o modelrig-server.exe .\cmd\modelrig-server
```

### 3. Start riggen — med alle flag

```powershell
cd deploy
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:KALIV_SCHEDULER_API = "1"
$env:KALIV_SCHEDULER = "1"
$env:KALIV_SCHEDULER_APPROVAL_SECRET = "kaliv-pilot-approval-secret-2026-07-26-abcdef"
powershell -ExecutionPolicy Bypass -File .\run-windows.ps1
```

**Læs opstartslinjen: skal sige `1.58.145`.** Lad vinduet stå.

Om flagene:
- `PYTHONDONTWRITEBYTECODE` — `.pyc` i træet fælder freeze-gaten (F-1502)
- `KALIV_SCHEDULER_API` — uden den er `/api/v1/schedules` **404** (`server.go:87`)
- `KALIV_SCHEDULER_APPROVAL_SECRET` — **mindst 32 tegn**, ellers 503
  (`schedule_approvals.go:137`). Samme værdi i alle vinduer.

### 4. Hent et token — nyt vindue

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:KALIV_SCHEDULER_APPROVAL_SECRET = "kaliv-pilot-approval-secret-2026-07-26-abcdef"
$c = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/start"
$r = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/claim" `
     -ContentType "application/json" `
     -Body (@{ code = $c.code; device_name = "stage-a" } | ConvertTo-Json)
$env:MODELRIG_TOKEN = ([string]$r.token).Trim()
"$($env:MODELRIG_TOKEN.Length)"
```

**SKAL vise 64.** Et token er 32 bytes hex (`auth.NewToken`). Viser den noget
andet, så stop — alt autentificeret fejler derefter med **400**, ikke 401, fordi
headeren er malformet.

At sætte variablen her betyder at wizard'en **springer token-prompten over**.
Den prompt er `getpass` og tager ikke pålideligt imod indsæt i konsollen.

---

## Kør beviserne

**Alt i vinduet fra trin 4**, hvor token og hemmelighed er sat.

```powershell
.\START_STAGE_A_TEST.cmd
```

Den tager preflight, agent3, model_eval og rag automatisk. Forventet tid:
model_eval ~3 min, **RAG ~40 min** (10.000 chunks; embedding går ét HTTP-kald
ad gangen, GPU'en ligger på ~39% — det er kaldsmønsteret der er flaskehalsen,
ikke modellen).

### Workflow-baseline — projektets første completion rate

`START_STAGE_A_TEST.cmd` dækker den ikke. Den er aldrig kørt, så der findes
ikke et tal at sammenligne med endnu — det er hele pointen med at køre den.

Svar først på om riggen overhovedet er klar. Det tager sekunder, kører intet og
rører ingen port:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:MODELRIG_TOKEN = "<64 hex>"
python scripts\workflow_baseline_one_click.py --check --model hermes3:8b
```

Preflight blokerer på de seks ting der plejer at koste en formiddag, og hver
besked bærer rettelsen: `.pyc` i træet, beskidt arbejdstræ, token der ikke er 64
hex, worker der ikke svarer (med `run-windows.ps1`-fælden nævnt), 401 fra et
token fra før en genstart, og en model Ollama ikke har hentet.

Siger den at riggen er klar:

```powershell
python scripts\workflow_baseline_one_click.py --model hermes3:8b
```

14 workflows. Kvitteringen lander i `validation\workflow-baseline-latest.json`
med `completion_rate`, transcripts i `validation\workflow-run-latest.json`.
Fejler ét workflow, kan det gentages alene med `--only W-05` uden at køre
sættet om.

Specen er i forvejen tjekket: `tests/workflow_spec_contract.py` holder de 14
internt konsistente, så en tastefejl i et forventet værktøjsnavn ikke opdages
her men i CI.

### Voice — det manuelle pausepunkt

Fem Pixel-trials. **Kriterierne er eksakte** (`_manual_trial_passes`):

```
recognized          = true
playback_stopped    = true
stale_audio_resumed = false
ui_terminal_state   = "cancelled" ELLER "idle"     ← ikke "stopped", ikke "error"
stop_latency_ms     = et tal mellem 0 og 30000     ← ikke null
```

De fem triggere:

| Trial | Handling |
|---|---|
| `manual-01` | stop-tryk under **første** lydstykke |
| `manual-02` | stop-tryk **mellem** to lydstykker |
| `manual-03` | begynd at tale under første lydstykke |
| `manual-04` | begynd at tale mellem to lydstykker |
| `manual-05` | afbryd netværket midt i afspilningen |

Brug samme spørgsmål hver gang, så stykkerne er lige lange. Noget rent
forklarende uden værktøjer eller RAG:

> *"Forklar hvordan en forbrændingsmotor virker, trin for trin."*

**Skriv hvad der faktisk sker.** Filen er evidens, ikke en formular. Resumer
gammel lyd, så skriv `true` — det er netop det, øvelsen findes for at fange.

**Efter dine fem trials kører den selv fire automatiserede cancellation-probes**
plus 40 gennemløb (20 fraser × 2). Alle fire probes skal afbryde rent, rydde op
og efterlade workeren sund. **Det er den sti voice-fejlen sad i** — de ville have
fældet dig 25/7 uanset hvad du gjorde med telefonen.

---

## Scheduler-piloten — kør den separat

Stage A's egen scheduler-del kræver at du indsætter schedule-id'er og
recovery-linjer manuelt. **Den selvstændige pilot gør det samme automatisk og
skriver til samme rapportfil** (`validation/scheduler-pilot-latest.json`), som er
den kampagnen læser.

```powershell
.\START_SCHEDULER_PILOT.cmd
```

Den starter sin egen worker og dræber den hårdt for at bevise recovery.

**Beder den om port 8099:**

```powershell
Get-NetTCPConnection -LocalPort 8099 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

Piloten rydder ikke op efter sig selv, så en afbrudt kørsel blokerer den næste.
Backenden lytter på 8080 og røres ikke.

**Én manuel handling:** opret præcis denne plan i appen og tryk Godkend.

```
note_append · {"text":"pilot"} · every:60 · max_runs=2 · ttl_days=1
```

Du skal ikke kopiere noget tilbage.

**Tjek af planer skal bruge `Format-Table`** — PowerShell afkorter
standardvisningen med `...`, og det ligner en tom liste:

```powershell
(Invoke-RestMethod -Uri "http://127.0.0.1:8099/schedules").schedules |
  Format-Table schedule_id, tool, cadence
```

---

## Til sidst

Når alle seks ligger i `validation\`, kører du `verify`. Den er grøn kun når
hvert bevis er **present, fresh, candidate-bound og green** — og
`min-model-exact` er 1.0, så model_eval skal være 30/30 præcis.

### Promovering

```powershell
git tag -a v1.58.145 60f9b00 -m "v1.58.145"
git push origin v1.58.145
```

**Tagget skal sidde direkte på `60f9b00`.** Aldrig på en merge-commit — dens træ
ville afvige fra det validerede og fælde den byte-eksakte attestation
(F-1802/F-1503).

### Derefter

1. Skær `1.58.146` fra main med desktop-designet og workflow-harnessen
2. Overvej `v1.0.0` — 1.0 har konsistent betydet *"apparatet er bevist på
   hardware"*, og det er præcis hvad rig-dagen afgør
3. Merge #157, #13, så #5/#7/#9
4. **Rør ikke #163** — 8.671 linjer computer-use på den frosne kandidat
5. **Rør ikke #135** før T-019 er kørt — den ændrer den kode piloten måler

---

## Hvis noget stopper

| Symptom | Årsag |
|---|---|
| `does not contain current origin/main` | main er rykket; kandidaten skal merges op **før** rig-dagen |
| Alt autentificeret giver **400** | tokenet er ikke 64 tegn |
| `/api/v1/schedules` giver **404** | `KALIV_SCHEDULER_API=1` mangler |
| `approve` giver **503** | hemmeligheden er under 32 tegn, eller ikke ens i begge vinduer |
| `NOT FROZEN — bytecode` | `.pyc` i træet; sæt `PYTHONDONTWRITEBYTECODE=1` og ryd |
| `Errno 10048` på 8099 | efterladt worker fra en afbrudt pilot |
| Konsollen tager ikke imod tastetryk | mark-mode; titlen siger "Vælg" — tryk **Esc** |
