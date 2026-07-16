# Kaliv Agent 3.0 — reviewed read checkpoints

Status: **developer-only, feature-flagged og ikke koblet til normal chat-routing.**

Read review er en opt-in execution-policy for Agent 3.0. Et run kan stoppe efter et
vellykket read-step, før næste pending read udføres. Brugeren kan derefter gennemgå
resultatet, lave et serverbundet replan-preview eller fortsætte eksplicit.

## Sikkerhedsgrænse

- `review_reads` er `false` som standard.
- Flaget bindes til det serverlagrede single-use `plan_id`.
- Klienten kan ikke vise ét review-mode og starte et andet.
- Review-state gemmes separat i SQLite; eksisterende `AgentRun`-JSON migreres ikke.
- Et checkpoint indeholder det eksakte pending read-window og removable step-id'er.
- Completed prefix og en efterfølgende write/admin/destructive-tail er immutable.
- Replan-apply genbinder checkpointet til de nye replacement-step-id'er.
- En replan genoptager aldrig runnet automatisk.
- Resume er et særskilt, eksplicit API-kald.
- Write-confirmation sker fortsat separat og kan ikke erstattes af read review.

## Serverflow

### 1. Plan-preview med review

```json
{
  "message": "Kontrollér rigstatus og modeller, og skriv derefter en note",
  "mode": "rig",
  "review_reads": true
}
```

`POST /api/v1/experimental/agent3/plan` returnerer blandt andet:

```json
{
  "plan_id": "...",
  "review_reads": true,
  "executed": false
}
```

### 2. Start den viste single-use plan

```text
POST /api/v1/experimental/agent3/plans/{plan_id}/start
```

Efter første read kan svaret indeholde:

```json
{
  "review_reads": true,
  "read_review": {
    "enabled": true,
    "waiting": true,
    "window_start": 1,
    "window_end": 3,
    "removable_step_ids": ["...", "..."]
  }
}
```

Run-state kan fortsat være `running`; `read_review.waiting=true` er den autoritative
checkpoint-markør.

### 3A. Fortsæt uden replan

```text
POST /api/v1/experimental/agent3/runs/{run_id}/resume
```

Et reviewed run udfører højst ét nyt read, før det eventuelt stopper ved næste checkpoint.

### 3B. Lav reviewed replan-preview

```text
POST /api/v1/experimental/agent3/runs/{run_id}/replan-preview
```

Previewet er read-only og ændrer ikke runnet. Apply accepterer kun det serverlagrede token:

```text
POST /api/v1/experimental/agent3/replan-previews/{preview_id}/apply
```

Efter apply:

- checkpointet forbliver waiting,
- removable ids peger på de nye read-steps,
- write-tailen beholder ids og args,
- tokenet kan ikke genbruges,
- runnet fortsætter ikke automatisk.

### 4. Write-confirmation

Når alle reviewed reads er afsluttet, følger den eksisterende Agent 3.0-policy. Et
write/destructive/admin-step stopper i `waiting_confirmation` og kræver sit eget immutable
confirmation-kort.

## Desktop developer-skærm

```powershell
cd desktop
.\gradlew.bat :composeApp:run --args="--agent3-review"
```

Skærmen:

- starter med read review slået fra,
- viser det serverreturnerede preview-flag,
- starter kun den viste single-use plan,
- viser checkpointets completed tool, window og removable ids,
- udfører ikke resume, replan eller confirmation automatisk.

Den eksisterende `--agent3-replan`-skærm bruges til reviewed replan-preview/apply.

## Android developer-skærm

```powershell
adb shell am start -S `
  -n dk.ternedal.modelrig/.MainActivity `
  --ez dk.ternedal.modelrig.extra.AGENT3_REVIEW true
```

Skærmen genbruger den eksisterende rig-URL og paired device-token fra `TokenStore`.
Launcheren sender ikke dette extra; normal `AppUi()` er uændret.

## Persistens

Review-policy ligger som standard i:

```text
kaliv-agent3-read-reviews.db
```

Stien kan ændres med:

```text
KALIV_AGENT3_REVIEW_DB
```

Replan-journal og preview-tokens ligger fortsat i deres separate databaser. Et crash eller
en recovery-conflict må ikke omgå checkpoint, journal eller confirmation-policy.

## Testbeviser

De isolerede tests dækker blandt andet:

- pause efter præcis ét read,
- persistence gennem reload,
- eksplicit resume,
- ingen pause før immutable write-tail,
- default `review_reads=false`,
- retry genbruger original serverlagret review-policy,
- preview→single-use start binder flaget,
- unsupported runtime afviser flaget før modelkald,
- replan-apply genbinder replacement-id'er,
- tomt read-window rydder kun det stale checkpoint,
- write-confirmation består efter reviewed reads.

## Fortsat uden for scope

- normal chat/TurnRouter-integration,
- automatisk resume,
- unattended LLM-replan,
- automatisk write-godkendelse,
- produktion eller promotion gennem klienten.
