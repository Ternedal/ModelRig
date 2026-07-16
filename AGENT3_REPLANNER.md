# Kaliv Agent 3.0 — reviewed read replanner

Status: **developer-only, feature-flagged og ikke koblet til normal chat-routing.**

Replanneren kan ændre den resterende read-only del af en persistent Agent 3.0-plan,
uden at ændre færdige steps eller en efterfølgende write/admin/destructive-tail.

## Sikkerhedsmodel

Den eneste udskiftelige del er den sammenhængende række af `pending` read-steps, som
begynder ved `current_step`.

Følgende er altid immutable:

- completed, approved, executing og failed steps,
- alle steps før `current_step`,
- første write/destructive/admin-step og hele planen efter dette punkt,
- tool-argumenter i den immutable tail,
- route, egress og conversation-binding.

Replacement-steps skal:

- være klassificeret som `read` af det eksisterende V2 registry,
- være enabled i den eksisterende ToolGate,
- være friske og `pending`,
- bruge samme local/cloud-route og conversation-id,
- holde sig inden for `max_steps` og `max_replans`.

Cloud-runs kan kun replannes manuelt med en eksplicit `{tool,args}`-plan. Den lokale
LLM-replanner afviser cloud-runs før modelkald.

## Crash-recovery

Replans journalføres i en separat SQLite write-ahead journal:

1. `prepared` med digest før og efter revisionen,
2. det reviderede `AgentRun` gemmes,
3. journalen markeres `committed`.

Efter et crash sammenlignes den persistente run-digest med begge sider:

- matcher den før-siden, bliver revisionen `aborted`,
- matcher den efter-siden, bliver revisionen `committed`,
- matcher den ingen af delene, bliver den `conflict`.

En conflict genafspilles aldrig automatisk og blokerer `resume`, `confirm`, `cancel` og
nye replans, indtil den er undersøgt.

## Eksplicit manuel replan

```text
POST /api/v1/experimental/agent3/runs/{run_id}/replan
GET  /api/v1/experimental/agent3/runs/{run_id}/replans
```

Request:

```json
{
  "reason": "To reads kan erstattes af ét nyt statuskald",
  "plan": [
    {
      "tool": "rig_status",
      "args": {"detail": true}
    }
  ]
}
```

Klienten kan kun angive `tool` og `args`. Risk, sensitivity, egress og summary kommer fra
kode og det eksisterende registry. En tom `plan` fjerner det resterende pending
read-window, men kan ikke fjerne en efterfølgende side-effect-tail.

## Lokal LLM-preview

```text
POST /api/v1/experimental/agent3/runs/{run_id}/replan-preview
POST /api/v1/experimental/agent3/replan-previews/{preview_id}/apply
```

Preview-request:

```json
{
  "planner_model": "qwen3:8b"
}
```

Previewet:

- kalder kun en lokal planner-model,
- viser kun enabled read-tools i kataloget,
- inkluderer bounded completed observations som untrusted data,
- skjuler write-tailens args, results og confirmation-felter,
- returnerer rationale, prompt-SHA, read-window og det validerede read-forslag,
- eksekverer og journalfører intet.

Previewet gemmes som et kortlivet single-use-token bundet til:

- run-id og komplet run-digest,
- journalrevision og replan-count,
- removable step-id'er,
- immutable prefix- og tail-id'er,
- eksakte replacement-steps,
- planner-model og prompt-SHA.

Apply-endpointet accepterer kun `preview_id`. Det accepterer ingen ny plan eller nye
argumenter. Tokenet forbruges før apply; et stale, ændret eller genbrugt token afvises.
Apply kalder ikke modellen igen.

## Developer UI

### Android

```powershell
adb shell am start -S `
  -n dk.ternedal.modelrig/.MainActivity `
  --ez dk.ternedal.modelrig.extra.AGENT3_REPLAN true
```

Skærmen bruger den eksisterende rig-URL og device-token fra `TokenStore`.

### Desktop

```powershell
cd desktop
.\gradlew.bat :composeApp:run --args="--agent3-replan"
```

Begge skærme:

- viser rationale, read-window, immutable tail, prompt-SHA og replacement-steps,
- kræver to klik før apply,
- tillader ikke redigering af det reviewed forslag,
- genoptager ikke runnet automatisk efter revisionen.

## Databaser og miljøvariabler

```text
KALIV_AGENT3_REPLAN_DB
KALIV_AGENT3_MAX_REPLANS
KALIV_AGENT3_REPLAN_PREVIEW_DB
KALIV_AGENT3_REPLAN_PREVIEW_TTL
KALIV_AGENT3_REPLAN_OBSERVATION_CHARS
```

Standarder:

- journal: `kaliv-agent3-replans.db`,
- max replans: `3`,
- preview-store: `kaliv-agent3-replan-previews.db`,
- preview-TTL: `300` sekunder,
- completed observation-budget: `6000` tegn.

## Testdækning

Replanner-suiten beviser blandt andet:

- immutable completed-prefix og write-tail,
- write/admin/destructive replacement afvises,
- route- og conversation-binding,
- max steps/replans,
- prepared → abort/commit/conflict recovery,
- conflict blokerer run-progression,
- write-tool er fraværende i LLM-kataloget,
- write-argumenter lækker ikke til prompten,
- prompt-injection i tool-resultater behandles som data,
- cloud-preview stopper før modelkald,
- single-use, expiry, stale run/revision og tampering,
- Bearer/feature-flag på gateway-routes,
- desktop- og Android-kompilering.

## Bevidst manglende endnu

Orchestratoren pauser **ikke automatisk** efter hvert read-resultat. En replan kræver derfor
fortsat et run, som allerede har et completed prefix og et pending read-window.

Næste core-milepæl er et eksplicit, opt-in review-checkpoint efter et read-step, så runnet
kan stoppe, vise replan-previewet og først fortsætte efter review. Dette må ikke påvirke
eksisterende Agent v2 eller normale Agent 3.0-runs, hvor review-mode er slået fra.
