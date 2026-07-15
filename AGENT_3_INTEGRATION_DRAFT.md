# Kaliv Agent 3.0 — integrationsudkast

Status: eksperimentelt, feature-flagged og ikke koblet til den normale chat-routing.

## Hvad denne branch leverer

- Persistent `AgentRun`/`AgentStep`-state-machine i SQLite.
- Én ren `TurnRouter`; retry må ikke skifte route eller droppe tools.
- Serverautoritativ retry: original besked, route-flags og valideret plan genbruges fra SQLite.
- Deterministisk policy for write/destructive/admin, cloud-egress og proaktivitet.
- Cloud-initierede read-tools kræver også et konkret godkendelseskort.
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
- Read-only end-to-end smoke-klient gennem den rigtige Bearer-gateway.
- Memory 3.0-datalag med proveniens, review-status, versioner, expiry og tombstones.
- Eksplicit memory-management API; ingen automatisk modelhukommelse.
- Memory-context compiler med hårdt budget og eksplicit lokal/cloud-policy.
- Context-preview API, som viser den eksakte blok uden at sende den til en model.
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
POST   /api/v1/experimental/agent3/plan
POST   /api/v1/experimental/agent3/plans/{plan_id}/start
GET    /api/v1/experimental/agent3/status
GET    /api/v1/experimental/agent3/runs
POST   /api/v1/experimental/agent3/runs
GET    /api/v1/experimental/agent3/runs/{id}
GET    /api/v1/experimental/agent3/runs/{id}/events
POST   /api/v1/experimental/agent3/runs/{id}/confirm
POST   /api/v1/experimental/agent3/runs/{id}/resume
POST   /api/v1/experimental/agent3/runs/{id}/cancel
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
8. Lokale read-steps kan køre direkte.
9. Write/destructive/admin og alle cloud-initierede tool-kald parkerer på hvert sit confirmation-kort.

Det oprindelige udvikler-endpoint `POST /runs` kan fortsat tage en eksplicit plan til
testformål, men produktflowet bør bruge plan-preview + `plan_id`.

En retry sender kun `retry_of_run_id`. Workerens run-store leverer den oprindelige
besked, mode, tools/RAG-flags og plan. Ændrede klientfelter eller en ny plan kan derfor
ikke ændre betydningen af en retry.

## Memory 3.0

Memory 3.0 er fortsat **eksplicit og administrativt**. Ingen chat, planner eller agent
læser endnu automatisk memory-tabellen.

Datalaget gemmer:

- `subject`, `predicate`, `value` og type,
- sensitivitet: public, operational, private eller secret,
- proveniens: explicit user, tool observation, import eller inference,
- confidence og review-status,
- versioner via `supersedes_id`,
- expiry og lifecycle-status.

Regler:

- eksplicit brugerdata er confirmed som udgangspunkt,
- inferred/imported/tool-observed data er pending,
- correction opretter en ny version og superseder den gamle atomisk,
- delete fjerner value og source-reference og efterlader kun en tombstone,
- secret records kan ikke oprettes eller rettes via remote API,
- eksisterende lokale secrets redigeres over API og udelades fra normale lister,
- pending, rejected, expired og deleted records bruges ikke som kontekst.

### Context-preview

`POST /memory/context-preview` er side-effect-free og returnerer:

- exact context text,
- inkluderede og udelukkede memory-id'er,
- tegnantal og target,
- `sent_to_model: false`.

Compileren:

- markerer memory som user-controlled reference data, aldrig instruktioner,
- fjerner `source_ref`,
- blokerer secrets altid,
- tillader private records lokalt,
- kræver eksplicit `allow_private_cloud` for private cloud-preview,
- unicode-escaper markup-lignende tekst,
- respekterer hårdt `max_chars` og `max_records`.

Preview betyder ikke consent til fremtidig afsendelse. Den automatiske modelintegration
skal senere have en særskilt, eksplicit policy og UI-kontrakt.

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
- godkende eller afvise et step,
- opdatere eller annullere et run.

Der er ingen launcher-knap, deep-link eller automatisk chat-routing til Agent 3.0 endnu.
Memory-management er heller ikke føjet til klient-UI'et endnu.

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

Skærmen har samme preview/start/run/confirm/cancel-kontrakt som Android. Memory-
management er endnu ikke koblet på desktop-UI'et.

## Read-only på-rig smoke

Smoke-scriptet går gennem den rigtige Go-gateway og bruger kun `rig_status`:

```powershell
$env:MODELRIG_TOKEN = "<paired device token>"
python scripts/agent3_smoke.py --base-url http://127.0.0.1:8080
```

Det validerer:

1. Bearer-beskyttet Agent 3.0-status,
2. lokal read-only plan,
3. single-use plan-start,
4. completed persistent run,
5. run-created/step-started/step-succeeded/run-completed events.

## Sikkerhedsinvarianter

1. Hvert write/destructive/admin-step får sin egen godkendelse.
2. Alle cloud-initierede tools, også reads, får et konkret godkendelseskort.
3. Godkendelsen er bundet til step-id, tool, args, risiko, sensitivitet, egress og origin.
4. Ændres payloaden, afvises godkendelsen.
5. Timeout er afvisning.
6. Tool-kill-switch kan stadig afvise mellem preview, kort og eksekvering.
7. Private read-resultater til cloud kræver både cloud-consent og per-call confirmation.
8. Secrets må aldrig sendes til cloud.
9. Proaktive runs er read-only.
10. Et muligt side-effect fundet i `executing` efter crash genkøres ikke automatisk.
11. Retry genbruger den serverlagrede plan og route; klienten kan ikke nedgradere den.
12. Remote adgang går gennem backendens eksisterende Bearer-middleware.
13. Planner-output kan ikke definere risiko, godkendelse, sensitivitet eller egress.
14. En vist plan kan kun startes gennem dens uændrede single-use `plan_id`.
15. Agent 3.0 er fraværende fra API-overfladen, når feature flaget er slukket.
16. De normale Android- og desktop-chatflows vælger aldrig Agent 3.0 i denne draft.
17. Memory sendes ikke automatisk til nogen model.
18. Context-preview er gennemsigtigt, budgetteret og eksplicit markeret som ikke-afsendt.

## Test

```bash
PYTHONPATH=worker python3 tests/worker_agent3_integration.py
PYTHONPATH=worker python3 tests/worker_agent3_retry.py
PYTHONPATH=worker python3 tests/worker_agent3_planner.py
PYTHONPATH=worker python3 tests/worker_agent3_plan_store.py
PYTHONPATH=worker python3 tests/worker_agent3_entrypoint.py
PYTHONPATH=worker python3 tests/worker_agent3_cloud_read_policy.py
PYTHONPATH=worker python3 tests/worker_agent3_smoke_cli.py
PYTHONPATH=worker python3 tests/worker_agent3_memory.py
PYTHONPATH=worker python3 tests/worker_agent3_memory_api.py
PYTHONPATH=worker python3 tests/worker_agent3_memory_context.py
cd backend && go test ./internal/httpapi/
```

Python-testene bruger fake modeller/gates og kræver hverken Ollama, GPU eller netværk.
De dækker routing, persistence, immutable confirmations, planner-injection, plan-TTL,
single-use, preview→run-binding, feature-flag mounting, cloud-read policy, smoke-flow,
memory-lifecycle, secret-redaction og context-preview.

Repository-CI kører desuden:

- fuld backend- og worker-suite,
- Windows appliance-tests,
- Android Kotlin-kompilering,
- desktop Kotlin-kompilering.

CI uploader den fulde Python- eller desktop-compilerlog som artifact ved fejl, så den
første traceback/kompileringsfejl ikke forsvinder i GitHubs afkortede logvisning.

## Ikke leveret endnu

- Replanner, der kan ændre resterende read-steps efter et resultat uden at ændre godkendte writes.
- Integration i det normale Android/desktop `TurnRouter`- og chatflow.
- Produkt-UX for eksplicit downgrade-valg, run-timeline og Agent 3.0 som almindelig chatmode.
- Automatisk, policy-styret memory-retrieval og prompt-integration.
- Memory-management UI på Android og desktop.
- Kryptering-at-rest for secret memory.
- Proactive inbox og scheduler.
- Capability Graph til RigGate og fremtidige rigs.
- Sandbox executor/Windows-konto til tredjeparts-MCP og vilkårlige filtools.
- On-device og på-rig end-to-end-validering af planner → plan-id → confirmation → tool-resultat.
