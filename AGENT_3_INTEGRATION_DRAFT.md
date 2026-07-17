# Kaliv Agent 3.0 — integrationsudkast

Status: eksperimentelt, feature-flagged og ikke koblet til den normale chat-routing.

## Leveret

### Execution og planner

- Persistent `AgentRun`/`AgentStep` state-machine i SQLite.
- Serverautoritativ retry har sin egen route og genbruger original besked, route-flags og valideret plan.
- Deterministisk policy for writes, destructive/admin, cloud-egress og proaktivitet.
- Hvert write/destructive/admin-step kræver sin egen immutable confirmation med TTL.
- Alle cloud-initierede tools, også reads, kræver et konkret confirmation-kort.
- Et step fundet i `executing` efter crash genkøres aldrig blindt.
- Agent v2 `REGISTRY` og `ToolGate` forbliver load-bearing for whitelist, kill switch, argumentkontrol og audit.
- Lokal typed, plan-only LLM-planner.
- Modellen må kun foreslå `{tool,args}`; risk, sensitivity, egress og approval tilføjes i kode.
- Previewede planer gemmes som kortlivede single-use `plan_id`-tokens.
- Run-start accepterer ingen erstatningsplan fra klienten.

### Eksperimentel API-overflade

Agent 3.0 findes kun, når `KALIV_AGENT3_ENABLED=1` ved processtart.
Worker-routes ligger under `/experimental/agent3`; remote adgang går gennem den normale
Bearer-beskyttede Go-gateway under `/api/v1/experimental/agent3`.

```text
POST   /api/v1/experimental/agent3/plan
POST   /api/v1/experimental/agent3/plans/{plan_id}/start
GET    /api/v1/experimental/agent3/status
GET    /api/v1/experimental/agent3/runs
GET    /api/v1/experimental/agent3/runs/{id}
POST   /api/v1/experimental/agent3/runs/{id}/retry
GET    /api/v1/experimental/agent3/runs/{id}/events
POST   /api/v1/experimental/agent3/runs/{id}/confirm
POST   /api/v1/experimental/agent3/runs/{id}/resume
POST   /api/v1/experimental/agent3/runs/{id}/cancel
```

Den normale release-worker indeholder modulet, men monterer ingen Agent 3.0-routes eller
databaser uden flaget. Agent v2 `/tools/chat` og de normale klientflows er urørte.

## Memory 3.0

### Datalag og administration

Memory-store er lokal SQLite og indeholder:

- subject, predicate, value og type,
- public/operational/private/secret sensitivity,
- proveniens: explicit user, tool observation, import eller inference,
- confidence og pending/confirmed/rejected review-status,
- versioner via `supersedes_id`,
- expiry og active/superseded/deleted lifecycle.

Regler:

- explicit user memory er confirmed som udgangspunkt,
- inferred/imported/tool-observed memory er pending,
- correction opretter en ny version og superseder den gamle atomisk,
- delete fjerner value og source-reference og efterlader kun en tombstone,
- remote API kan ikke oprette eller rette secret memory,
- eksisterende lokale secrets redigeres over API og udelades fra normale lister,
- pending, rejected, expired og deleted records bruges ikke som kontekst.

Bearer-beskyttede memory-routes:

```text
GET    /api/v1/experimental/agent3/memory
POST   /api/v1/experimental/agent3/memory
GET    /api/v1/experimental/agent3/memory/search
POST   /api/v1/experimental/agent3/memory/context-preview
GET    /api/v1/experimental/agent3/memory/{id}
GET    /api/v1/experimental/agent3/memory/{id}/history
POST   /api/v1/experimental/agent3/memory/{id}/confirm
POST   /api/v1/experimental/agent3/memory/{id}/reject
POST   /api/v1/experimental/agent3/memory/{id}/correct
DELETE /api/v1/experimental/agent3/memory/{id}
```

### Context compiler

Compileren producerer en afgrænset, versioneret JSON-datablok og:

- markerer memory som user-controlled reference data, aldrig instruktioner,
- fjerner `source_ref`,
- blokerer secrets altid,
- tillader private records lokalt,
- kræver `allow_private_cloud=true` for private cloud-context,
- unicode-escaper markup-lignende tekst,
- respekterer hårde `max_chars` og `max_records`.

`POST /memory/context-preview` er side-effect-free og returnerer den eksakte blok,
inkluderede/udelukkede ids, target og tegnantal med `sent_to_model=false`.

### Eksplicit planner-memory

Planner-memory er **slukket som standard**. Memory-store læses ikke, medmindre et
plan-preview eksplicit sender:

```json
{
  "use_memory": true,
  "memory_subjects": ["valgfrit-subject"],
  "memory_max_chars": 4000,
  "memory_max_records": 25
}
```

Serveren vælger privacy-target ud fra den valgte route:

- lokal route bruger lokal memory-policy,
- cloud-route bruger cloud-policy,
- private cloud-records kræver stadig `allow_private_cloud=true`,
- secret records blokeres altid.

Preview-svaret indeholder en autoritativ `memory_context` receipt:

```json
{
  "requested": true,
  "sent_to_model": true,
  "target": "local",
  "included_ids": ["..."],
  "excluded_ids": ["..."],
  "character_count": 1234,
  "sha256": "..."
}
```

SHA-256 matcher den præcise memoryblok, plan-modellen modtog. Receipt gemmes sammen med
den single-use plan og returneres igen ved plan-start. Memory ændrer ikke tool-policy,
confirmation-krav eller run-state-machine.

Der findes fortsat **ingen automatisk memory retrieval i normal chat**. Planner-memory
kræver et nyt, synligt opt-in for hvert preview og valget gemmes ikke automatisk i klienten.

## Developer-only klienter

### Android

Normal launcher åbner fortsat `AppUi()`.

Plan/run-skærm:

```powershell
adb shell am start -S `
  -n dk.ternedal.modelrig/.MainActivity `
  --ez dk.ternedal.modelrig.extra.AGENT3 true
```

Memory-management:

```powershell
adb shell am start -S `
  -n dk.ternedal.modelrig/.MainActivity `
  --ez dk.ternedal.modelrig.extra.AGENT3_MEMORY true
```

Plan/run-skærmen har:

- plan-preview, single-use start, run-status og confirmation,
- eksplicit memory-toggle, som altid starter slået fra,
- valgfrit kommasepareret subject-filter,
- synlig receipt med ids, target, tegnantal og SHA-256.

Memory-skærmen kan list/search/create/review/correct/history/delete. Delete kræver to
separate tryk og efterlader kun en indholdsfri tombstone.

### Desktop

Plan/run:

```powershell
cd desktop
.\gradlew.bat :composeApp:run --args="--agent3"
```

Memory-management:

```powershell
cd desktop
.\gradlew.bat :composeApp:run --args="--agent3-memory"
```

Desktop har samme explicit memory-toggle, subject-filter, receipt og administrative
memory-lifecycle som Android. Uden flag kaldes den normale `App()` præcis som før.

## Aktivering

```powershell
$env:KALIV_AGENT3_ENABLED = "1"
$env:KALIV_TOOLS_ENABLED = "1"
```

Workerens loopback-regel gælder fortsat. Til Python-udvikling kan det separate entrypoint
bruges:

```powershell
python worker/run_worker_agent3.py
```

## Sikkerhedsinvarianter

1. Planner-memory er per-request opt-in og falsk som standard.
2. Manglende memory-store ved opt-in fejler lukket, før modellen kaldes.
3. Subject-, lifecycle-, review-, expiry- og privacy-filter håndhæves server-side.
4. Secrets kommer aldrig i planner-context.
5. Receiptens SHA matcher den præcise memoryblok, modellen modtog.
6. Receipt bindes til den gemte single-use plan.
7. Memory kan ikke definere risk, approval, sensitivity eller egress.
8. Memory kan ikke omgå write- eller cloud-tool-confirmation.
9. Hvert side-effect-step får sin egen godkendelse.
10. Payloadændring eller confirmation-timeout afvises.
11. Tool-kill-switch kan afvise efter preview og før eksekvering.
12. Retry genbruger serverlagret plan og route.
13. Proaktive runs er read-only.
14. Remote adgang kræver Bearer-token; der findes ingen loopback-auth-bypass.
15. Normale Android-, desktop- og Agent v2-chatflows vælger aldrig Agent 3.0.

## Test og CI

Nøglechecks:

```bash
PYTHONPATH=worker python3 tests/worker_agent3_integration.py
PYTHONPATH=worker python3 tests/worker_agent3_retry.py
PYTHONPATH=worker python3 tests/worker_agent3_planner.py
PYTHONPATH=worker python3 tests/worker_agent3_plan_store.py
PYTHONPATH=worker python3 tests/worker_agent3_planner_memory.py
PYTHONPATH=worker python3 tests/worker_agent3_cloud_read_policy.py
PYTHONPATH=worker python3 tests/worker_agent3_smoke_cli.py
PYTHONPATH=worker python3 tests/worker_agent3_memory.py
PYTHONPATH=worker python3 tests/worker_agent3_memory_api.py
PYTHONPATH=worker python3 tests/worker_agent3_memory_context.py
cd backend && go test ./internal/httpapi/
```

Planner-memory-testen beviser:

- intet memory-read eller promptblock uden opt-in,
- local/cloud privacy-policy,
- secret- og pending-blokering,
- subject-filter,
- zero-budget-adfærd,
- fail-closed uden store,
- receipt-SHA mod den faktiske modelbesked,
- receipt-binding til plan-start,
- uændret write-confirmation.

Repository-CI kører desuden backend/worker, Windows appliance, Android Kotlin og desktop
Kotlin. Ved fejl uploades den fulde Python- eller desktop-compilerlog som artifact.

## Ikke leveret endnu

- Replanner for resterende read-steps.
- Integration i normal Android/desktop `TurnRouter` og chatflow.
- Automatisk relevance-ranking eller memory retrieval i normal chat.
- Kryptering-at-rest for secret memory.
- Proactive inbox og scheduler.
- Capability Graph til RigGate og fremtidige rigs.
- Sandbox executor til tredjeparts-MCP og vilkårlige filtools.
- On-device og på-rig end-to-end-validering med rigtig planner-model.
