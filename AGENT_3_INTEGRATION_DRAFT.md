# Kaliv Agent 3.0 — integrationsudkast

Status: eksperimentelt, feature-flagged og ikke koblet til produktionsklienterne.

## Hvad denne branch leverer

- Persistent `AgentRun`/`AgentStep`-state-machine i SQLite.
- Én ren `TurnRouter`; retry må ikke skifte route eller droppe tools.
- Deterministisk policy for write/destructive/admin, privacy og proaktivitet.
- Immutable confirmation digest + udløbstid.
- Crashregel: et step fundet i `executing` genkøres aldrig blindt.
- Adapter til det eksisterende Agent v2 `REGISTRY` og `ToolGate`.
- V2-gaten forbliver load-bearing for whitelist, kill switch, argumentkontrol og audit.
- Eksperimentel FastAPI under `/experimental/agent3`.
- Separat entrypoint `worker/run_worker_agent3.py`.
- Agent v2 `/tools/chat` og normal `worker/run_worker.py` er urørte.

## Start lokalt

```powershell
$env:KALIV_AGENT3_ENABLED = "1"
$env:KALIV_TOOLS_ENABLED = "1"
python worker/run_worker_agent3.py
```

Workerens normale loopback-regel gælder stadig.

## API-status

Dette udkast har bevidst **ingen LLM-planlægger endnu**. `POST /experimental/agent3/runs`
kræver en eksplicit plan med `{tool,args}`. Serveren ignorerer enhver klientpåstand om
risiko og sensitivitet; begge dele slås op i kode gennem V2-registry-adapteren.

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

## Test

```bash
PYTHONPATH=worker python3 tests/worker_agent3_integration.py
```

Testen bruger en fake V2-gate og kræver hverken Ollama, GPU eller netværk.

## Ikke leveret endnu

- LLM-baseret typed planner/replanner.
- Backend proxy under `/api/v1/agent3/*`.
- Android/desktop `TurnRouter`-integration.
- UI til run-timeline, downgrade-valg og Agent 3.0 confirmations.
- Persistent memory, proactive inbox og scheduler.
- Sandbox executor/Windows-konto til tredjeparts-MCP og vilkårlige filtools.
