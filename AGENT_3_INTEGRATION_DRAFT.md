# Kaliv Agent 3.0 — integrationsudkast

Status: eksperimentelt, feature-flagged og ikke koblet til produktionsklienterne.

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
- Separat entrypoint `worker/run_worker_agent3.py`.
- Agent v2 `/tools/chat` og normal `worker/run_worker.py` er urørte.

## Start lokalt

```powershell
$env:KALIV_AGENT3_ENABLED = "1"
$env:KALIV_TOOLS_ENABLED = "1"
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
Agent 3.0-routes, og den almindelige worker mounter ikke modulet.

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

## Test

```bash
PYTHONPATH=worker python3 tests/worker_agent3_integration.py
PYTHONPATH=worker python3 tests/worker_agent3_retry.py
PYTHONPATH=worker python3 tests/worker_agent3_planner.py
PYTHONPATH=worker python3 tests/worker_agent3_plan_store.py
cd backend && go test ./internal/httpapi/
```

Python-testene bruger fake modeller/gates og kræver hverken Ollama, GPU eller netværk.
De dækker routing, persistence, immutable confirmations, planner-injection, plan-TTL,
single-use og preview→run-binding. Go-testen beviser, at routes er fraværende uden
feature flag og kræver Bearer-token, når flaget er aktivt. Repository-CI samler alle
`worker_agent3_*.py`-tests automatisk op.

## Ikke leveret endnu

- Replanner, der kan ændre resterende read-steps efter et resultat uden at ændre godkendte writes.
- Android/desktop `TurnRouter`-integration.
- UI til plan-preview, run-timeline, downgrade-valg og Agent 3.0 confirmations.
- Agent 3.0 i den normale PyInstaller-worker; draften bruger separat entrypoint.
- Persistent memory, proactive inbox og scheduler.
- Sandbox executor/Windows-konto til tredjeparts-MCP og vilkårlige filtools.
