# Rig-dagens friktion — 25-26/07-2026

Alt herunder kostede rigtig tid ved maskinen. Det står her for at det ikke gør
det igen. Rækkefølgen er den du ramte dem i.

---

## Det der faktisk blokerede

### 1. Stage A's containment-gate — 20 min

```
candidate 8e40103 does not contain current origin/main 608afed
```

Gaten er rigtig: den forhindrer at man promoverer en kandidat der ville rulle
mains commits tilbage. **Årsagen var mine otte pushes til main samme dag.** Jeg
havde skrevet i HANDOFF at rig-dagen var upåvirket, fordi jeg kun tjekkede
`freeze_check` — ikke denne gate.

**Fremover:** rør ikke main mens en frossen kandidat venter. Skal main
alligevel flyttes, så merge den ind i kandidaten *før* rig-dagen, ikke under.

### 2. Backend kørte 1.58.141, ikke kandidatens kode — 10 min

Riggen startede med en gammel binær. Beviserne ville have beskrevet forkert kode.

**Fremover:** byg backenden fra checkouten før riggen startes, og læs
versionslinjen ved opstart:

```powershell
go build -C backend -trimpath -o modelrig-server.exe .\cmd\modelrig-server
# opstartslinjen SKAL sige kandidatens version
```

### 3. Token-prompten — 45 min

To ting ramte samtidig:

- **`getpass` tog ikke imod indsæt.** Konsollen var i mark-mode ("Vælg" i
  titlen), og prompten ekkoer ingenting, så det var umuligt at se om noget
  landede.
- **Tokenet blev 287 tegn** i stedet for 64, fordi `Invoke-RestMethod`s
  objekt blev sat i variablen i stedet for `.token`-feltet. Alt autentificeret
  gav derefter **HTTP 400** — malformet header, ikke afvist token.

**Fremover:** sæt variablen før wizard'en startes, så prompten springes over:

```powershell
$c = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/start"
$r = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/claim" `
     -ContentType "application/json" `
     -Body (@{ code = $c.code; device_name = "stage-a" } | ConvertTo-Json)
$env:MODELRIG_TOKEN = ([string]$r.token).Trim()
"$($env:MODELRIG_TOKEN.Length)"   # SKAL vise 64
```

**Et ægte token er 32 bytes hex = præcis 64 tegn** (`auth.NewToken`). Er tallet
noget andet, så stop — alt derefter fejler med 400.

### 4. `KALIV_SCHEDULER_APPROVAL_SECRET` skal være ≥ 32 tegn — 40 min

Godkendelsen fejlede med 503 uanset at variablen var sat, fordi
`schedule_approvals.go:137` afviser kortere værdier:

```go
if len(secret) < 32 { return nil, errScheduleApprovalUnavailable }
```

Jeg foreslog en værdi på 14 tegn. **Den skal sættes ens i både backend-vinduet
og pilot-vinduet.**

### 5. Efterladt worker på port 8099 — 3 gange

Piloten starter sin egen worker og rydder ikke op når vinduet lukkes. Den
blokerer så sin egen næste kørsel med `Errno 10048`.

```powershell
Get-NetTCPConnection -LocalPort 8099 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

**Værd at rette i wizard'en:** en `finally` der dræber worker-processen.

---

## Ægte fejl fundet undervejs

### Voice-stop var brudt i produktionskoden — **RETTET**

Hver afbrudt voice-tur døde med
`RuntimeError: Unexpected message received: http.request`, og telefonen viste
*"forbindelsen lukkede før riggen var færdig"*.

`hardening.py`'s `replay_receive` returnerede `http.request` i det uendelige.
Harmløst for almindelige requests; fatalt for en `StreamingResponse`, hvor
Starlette parkerer på `receive()` og venter på `http.disconnect`.

Rettet i `60f9b00` med en test der er verificeret rød før og grøn efter.
**Voice kunne ikke have bestået uden dette fix** — det var ikke Pixel'en.

### Bytecode i træet blokerer freeze

`.pyc`-filer fra en kørende worker fælder freeze-gaten (F-1502).

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"   # sæt FØR alt andet
```

---

## Mine egne målefejl — tre af samme slags

Alle tre gav forkerte konklusioner, og to af dem sendte dig på gale ærinder:

1. **Importgraf fra `app.main`** i stedet for `run_worker.py` → *"70% af
   workeren er død"*. Rigtigt tal: 24%.
2. **Rute-probe via `app.main`** i stedet for `app.entrypoint` → *"kandidaten
   har mistet 15 ruter"*. Den havde mistet nul. Kandidatens egen wiring-test
   bestod 12/12 og modsagde mig direkte.
3. **Afkortet PowerShell-visning** læst som komplet liste → *"den godkendte plan
   mangler"*. Den var der sandsynligvis.

**Fællesnævneren: mål mod det der faktisk kører, og når en måling modsiger en
bestået test, er målingen den mistænkte.** Skrevet ind som lektie 21, 21b og 21c
i HANDOFF.

---

## Status efter to dage

**Bevist på hardware:**

| | |
|---|---|
| T-006 forced recovery | 6/6 på Windows |
| Rig preflight | bestået, kode-identitet bundet |
| Agent 3 fysisk | 9/9 — inkl. afvist skrivning muterer intet, single-use replay nægtes |
| Model-eval | 30/30 exact + 30/30 discipline |
| RAG | recall@5 = 1.0 ved både 1.000 og 10.000 chunks |
| Scheduler-pilot | 3 af 4 — read-plan, revocation, crash/restart/recovery |

**Mangler:** voice (blokeret af fejlen, nu rettet) og scheduler-pilotens
write-godkendelse.

**Vigtigt:** kandidaten har ny SHA (`60f9b00`) efter voice-fixet, så **alle
beviser skal køres igen**. Det er prisen for fejlen, ikke for noget du gjorde.

---

## RAG-tallet, som beslutningsgrundlag

| Skala | recall@5 | query p95 |
|---|---|---|
| 1.000 chunks | 1.0 | 575 ms |
| 10.000 chunks | 1.0 | **3.697 ms** |

Genfindingen holder perfekt. Latenstiden stiger 6,4× for 10× data — sublineært,
så indekset kollapser ikke, men 3,7 s fordobler omtrent tiden til første token.
Ingest af 10.000 chunks tog **over 35 minutter** ved 39% GPU-udnyttelse; embedding
går ét HTTP-kald ad gangen uden batching, så flaskehalsen er kaldsmønsteret, ikke
modellen.

ROADMAP siger Qdrant kun aktiveres ved **målt** behov. Det her er målingen.

---

## Hvad der er strukturelt rettet efter 27/07 — fire af punkterne ovenfor kan ikke gentage sig

Loggen findes for at friktionen ikke gør det igen. Fire af posterne er nu fanget
*før* noget kører, af preflighten i `scripts/workflow_baseline_one_click.py`.
Den kører intet, skriver intet og rører ingen port — og hver blokering bærer
rettelsen i beskeden frem for i en gate-tabel man skal huske at slå op.

| Friktion ovenfor | Hvad der nu fanger den |
|---|---|
| **2.** Backend kørte forkert version | rent arbejdstræ kræves, og SHA'en skrives i kvitteringen |
| **3.** Token-prompten — 45 min | `MODELRIG_TOKEN` skal være sat og være 64 hex, ellers blokeres der med `auth.NewToken = 32 bytes hex` i beskeden |
| **5.** Efterladt worker på 8099 | workeren skal svare på `/healthz`, og beskeden nævner at `run-windows.ps1` dræber den i sin `finally` |
| Bytecode i træet blokerer freeze | `PYTHONDONTWRITEBYTECODE=1` kræves, og enhver `.pyc` i `worker/` blokerer med en copy/paste-klar oprydning |

Preflighten er selv testet uden rig: `tests/workflow_baseline_one_click.py`
driver hver check ind i sin fejltilstand og kræver at beskeden nævner
rettelsen. Bytecode-checket er en sabotage-cyklus — plant en `.pyc`, kræv rødt,
fjern den, kræv grønt.

**To ting er rettet i kode frem for i preflight:**

- `scripts/start-stage-a-validation-stack.ps1` hardkodede `MODELRIG_HOST=127.0.0.1`,
  som telefonen ikke kan nå. Den kan nu overstyres, og den valgte adresse
  skrives ud med en advarsel ved loopback — så en unåelig backend fejler
  synligt i stedet for at ligne at appen holdt op med at virke.
- `schedule_runner_impl.py` sagde `(levende worker)` når lease'en var optaget.
  Det følger ikke: hver proces får et frisk `owner_id`, så en worker der døde og
  genstartede kan ikke generobre sin egen lease. Beskeden hævdede en tilstand
  den ikke havde observeret, og nævner nu begge muligheder.

**Stadig ikke løst:** punkt 1 (containment-gaten) er ikke et værktøjsproblem —
det er reglen om ikke at røre main mens en frossen kandidat venter. Den regel
er i øvrigt mindre relevant nu, fordi kandidat-modellen er ovre: kandidaten
blev fast-forwardet ind i main 27/7, og `RIGDAG.md` §1 er rettet derefter.
