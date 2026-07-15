# Kaliv Agent 3.0 — integrationsudkast

Status: eksperimentelt, feature-flagged og ikke koblet til den normale chat-routing.

## Hvad denne branch leverer

- Persistent `AgentRun`/`AgentStep`-state-machine i SQLite.
- Én ren `TurnRouter`; retry må ikke skifte route eller droppe tools.
- Serverautoritativ retry: original besked, route-flags og valideret plan genbruges fra SQLite.
- Deterministisk policy for write/destructive/admin, privacy og proaktivitet.
- Immutable confirmation digest + udløbstid.
- Crashregel: et step fundet i `executing` genkøres aldrig blindt.
- Adapter til det eksisterende Agent v2 `REGISTRY` og `ToolGate`.
- V2-gaten forbliver load-bearing for whitelist, kill switch, argumentkontrol og audit.
- Lokal typed, plan-only LLM-planner med stramt JSON-format.
- Kortlivede, single-use `plan_id`-tokens mellem preview og run-start.
- Eksperimentel FastAPI under `/experimental/agent3`.
- Bearer-beskyttet backend-proxy under `/api/v1/experimental/agent3`.
- Dormant Agent 3.0-mount i den normale release-worker.
- Android- og desktop-transport med samme typed plan/run/confirmation-kontrakt.
- Isoleret Android plan/run-UI, som kun åbnes med et eksplicit intent-extra.
- Isoleret desktop plan/run-UI, som kun åbnes med `--agent3`.
- Agent v2 `/tools/chat` og de normale chatflows er urørte.

## Start worker og backend

Agent 3.0 kræver eksplicit opt-in på både worker og Go-backend:

```powershell
$env:KALIV_AGENT3_ENABLED = "1"
$env:KALIV_TOOLS_ENABLED = "1"
```

Den normale release-worker indeholder modulet, men monterer ingen Agent 3.0-routes eller
databaser uden flaget. Til Python-udvikling kan det separate entrypoint stadig bruges:

```powershell
python worker/run_worker_agent3.py
```

Workerens normale loopback-regel gælder stadig. Startes Go-backenden med samme feature
flag, kan API'et nås gennem den normale Bearer-beskyttede gateway:

```text
POST /api/v1/experimental/agent3/plan
POST /api/v1/experimental/agent3/plans/{plan_id}/start
GET  /api/v1/experimental/agent3/status
GET  /api/v1/experimental/agent3/runs
POST /api/v1/experimental/agent3/runs
GET  /api/v1/experimental/agent3/runs/{id}
GET  /api/v1/experimental/agent3/runs/{id}/events
POST /api/v1/experimental/agent3/runs/{id}/confirm
POST /api/v1/experimental/agent3/runs/{id}/resume
POST /api/v1/experimental/agent3/runs/{id}/cancel
```

Flaget skal være aktivt ved processtart. Når det er slukket, registrerer backenden ingen
Agent 3.0-routes, og workeren mounter ikke modulet.

## Planner- og run-flow

1. `POST /plan` kalder en lokal plan-only model.
2. Modellen må kun returnere `{steps:[{tool,args}], rationale}`.
3. Ukendte/deaktiverede tools og ekstra felter som `risk` eller `approved` afvises.
4. Registry-adapteren tilføjer risiko, sensitivitet, egress og menneskelig summary fra kode.
5. Den validerede plan gemmes server-side og returneres med et kortlivet `plan_id`.
6. `POST /plans/{plan_id}/start` tager ingen ny planpayload og bruger kun den gemte plan.
7. `plan_id` er single-use. Udløb eller genbrug afvises.
8. Read-steps kan køre; hvert write/destructive/admin-step parkerer på sit eget confirmation-kort.

Det oprindelige udvikler-endpoint `POST /runs` kan fortsat tage en eksplicit plan til
testformål, men produktflowet bør bruge plan-preview + `plan_id`.

En retry sender kun `retry_of_run_id`. Workerens run-store leverer den oprindelige
besked, mode, tools/RAG-flags og plan. Ændrede klientfelter eller en ny plan kan derfor
ikke ændre betydningen af en retry.

## Android-udkast

Androids normale launcher åbner fortsat `AppUi()` uden ændringer. Agent 3.0-skærmen kan
kun åbnes eksplicit fra ADB gennem den eksisterende `MainActivity`:

```powershell
adb shell am start -S `
  -n dk.ternedal.modelrig/.MainActivity `
  --ez dk.ternedal.modelrig.extra.AGENT3 true
```

Skærmen kan:

- lave plan-preview,
- vise route, rationale, args, risiko, sensitivitet og egress,
- starte den viste single-use plan,
- vise run- og step-status,
- godkende eller afvise et write-step,
- opdatere eller annullere et run.

Der er ingen launcher-knap, deep-link eller automatisk chat-routing til Agent 3.0 endnu.

## Desktop-udkast

Desktop-entrypointet vælger kun Agent 3.0-skærmen med `--agent3`:

```powershell
cd desktop
.\gradlew.bat :composeApp:run --args="--agent3"
```

Uden flaget kaldes den eksisterende `App()` præcis som før. Udviklerskærmen genbruger
som udgangspunkt desktop-databasens `localUrl` og `deviceToken`, med følgende env-
overrides:

```text
MODELRIG_AGENT3_URL
MODELRIG_LOCAL_URL
MODELRIG_TOKEN
```

Skærmen har samme preview/start/run/confirm/cancel-kontrakt som Android.

## Sikkerhedsinvarianter

1. Hvert write/destructive/admin-step får sin egen godkendelse.
2. Godkendelsen er bundet til step-id, tool, args, risiko, sensitivitet, egress og origin.
3. Ændres payloaden, afvises godkendelsen.
4. Timeout er afvisning.
5. Tool-kill-switch kan stadig afvise mellem preview, kort og eksekvering.
6. Private read-resultater til cloud kræver særskilt samtykke.
7. Proaktive runs er read-only.
8. Et muligt side-effect fundet i `executing` efter crash genkøres ikke automatisk.
9. Retry genbruger den serverlagrede plan og route; klienten kan ikke nedgradere den.
10. Remote adgang går gennem backendens eksisterende Bearer-middleware.
11. Planner-output kan ikke definere risiko, godkendelse, sensitivitet eller egress.
12. En vist plan kan kun startes gennem dens uændrede single-use `plan_id`.
13. Agent 3.0 er fraværende fra API-overfladen, når feature flaget er slukket.
14. De normale Android- og desktop-chatflows vælger aldrig Agent 3.0 i denne draft.

## Test

```bash
PYTHONPATH=worker python3 tests/worker_agent3_integration.py
PYTHONPATH=worker python3 tests/worker_agent3_retry.py
PYTHONPATH=worker python3 tests/worker_agent3_planner.py
PYTHONPATH=worker python3 tests/worker_agent3_plan_store.py
PYTHONPATH=worker python3 tests/worker_agent3_entrypoint.py
cd backend && go test ./internal/httpapi/
```

Python-testene bruger fake modeller/gates og kræver hverken Ollama, GPU eller netværk.
De dækker routing, persistence, immutable confirmations, planner-injection, plan-TTL,
single-use, preview→run-binding og feature-flag mounting. Go-testen beviser, at routes
er fraværende uden feature flag og kræver Bearer-token, når flaget er aktivt.

Repository-CI kører desuden:

- fuld backend- og worker-suite,
- Windows appliance-tests,
- Android Kotlin-kompilering,
- desktop Kotlin-kompilering.

CI uploader nu den fulde Python- eller desktop-compilerlog som artifact ved fejl, så den
første traceback/kompileringsfejl ikke forsvinder i GitHubs afkortede logvisning.

## Ikke leveret endnu

- Replanner, der kan ændre resterende read-steps efter et resultat uden at ændre godkendte writes.
- Integration i det normale Android/desktop `TurnRouter`- og chatflow.
- Produkt-UX for eksplicit downgrade-valg, run-timeline og Agent 3.0 som almindelig chatmode.
- Persistent memory med proveniens, rettelse og sletning.
- Proactive inbox og scheduler.
- Capability Graph til RigGate og fremtidige rigs.
- Sandbox executor/Windows-konto til tredjeparts-MCP og vilkårlige filtools.
- On-device og på-rig end-to-end-validering af planner → plan-id → confirmation → tool-resultat.
