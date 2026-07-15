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
/api/v1/experimental/agent3/status
/api/v1/experimental/agent3/runs
/api/v1/experimental/agent3/runs/{id}
/api/v1/experimental/agent3/runs/{id}/events
/api/v1/experimental/agent3/runs/{id}/confirm
/api/v1/experimental/agent3/runs/{id}/resume
/api/v1/experimental/agent3/runs/{id}/cancel
```

Flaget skal være aktivt ved processtart. Når det er slukket, registrerer backenden ingen
Agent 3.0-routes, og den almindelige worker mounter ikke modulet.

## API-status

Dette udkast har bevidst **ingen LLM-planlægger endnu**. Første `POST` til
`/experimental/agent3/runs` kræver en eksplicit plan med `{tool,args}`. Serveren
ignorerer enhver klientpåstand om risiko og sensitivitet; begge dele slås op i kode
gennem V2-registry-adapteren.

En retry sender kun `retry_of_run_id`. Workerens run-store leverer den oprindelige
besked, mode, tools/RAG-flags og plan. Ændrede klientfelter eller en ny plan kan derfor
ikke ændre betydningen af en retry.

Det næste trin er en typed planner, som kun kan aflevere toolnavne og argumenter til
samme validator. Den må ikke selv sætte risiko, godkendelsesbehov eller cloud-egress.

## Sikkerhedsinvarianter

1. Hvert write/destructive/admin-step får sin egen godkendelse.
2. Godkendelsen er bundet til step-id, tool, args, risiko, sensitivitet, egress og origin.
3. Ændres payloaden, afvises godkendelsen.
4. Timeout er afvisning.
5. Tool-kill-switch kan stadig afvise mellem kort og eksekvering.
6. Private read-resultater til cloud kræver særskilt samtykke.
7. Proaktive runs er read-only.
8. Et muligt side-effect fundet i `executing` efter crash genkøres ikke automatisk.
9. Retry genbruger den serverlagrede plan og route; klienten kan ikke nedgradere den.
10. Remote adgang går gennem backendens eksisterende Bearer-middleware.

## Test

```bash
PYTHONPATH=worker python3 tests/worker_agent3_integration.py
PYTHONPATH=worker python3 tests/worker_agent3_retry.py
cd backend && go test ./internal/httpapi/
```

Python-testene bruger en fake V2-gate og kræver hverken Ollama, GPU eller netværk.
Go-testen beviser, at routes er fraværende uden feature flag og kræver Bearer-token,
når flaget er aktivt. Repository-CI samler automatisk begge `worker_agent3_*.py`-tests op.

## Ikke leveret endnu

- LLM-baseret typed planner/replanner.
- Android/desktop `TurnRouter`-integration.
- UI til run-timeline, downgrade-valg og Agent 3.0 confirmations.
- Agent 3.0 i den normale PyInstaller-worker; draften bruger separat entrypoint.
- Persistent memory, proactive inbox og scheduler.
- Sandbox executor/Windows-konto til tredjeparts-MCP og vilkårlige filtools.
