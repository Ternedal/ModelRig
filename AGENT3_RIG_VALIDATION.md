# Kaliv Agent 3.0 — validering på den fysiske rig

Status: **harness implementeret og CI-testet; fysisk rig-validering er endnu ikke udført.**

Denne procedure validerer den eksperimentelle Agent 3.0-sti gennem den rigtige
Bearer-beskyttede Go-gateway og den lokale Ollama-planner. Den normale Android-,
desktop- og Agent v2-chat-routing er fortsat urørt.

## Hvad harnessen beviser

`python scripts/agent3_rig_validation.py` gennemfører én samlet kæde:

1. Agent 3.0-status gennem Go-backendens Bearer-gateway.
2. Oprettelse af en unik, midlertidig operational memory.
3. Side-effect-free context-preview for præcis denne memory.
4. Lokal Ollama-plan med eksplicit `use_memory=true`.
5. Verifikation af receipt-id'er, target, tegnantal og SHA-256.
6. Start af den eksakte single-use read-plan og eksekvering af `rig_status`.
7. Verifikation af persistent run og eventrækken:
   `run_created → policy_decision → step_started → step_succeeded → run_completed`.
8. Ny single-use write-plan med præcis ét `note_append`-step.
9. Verifikation af, at write-planen stopper i `waiting_confirmation`, før tool-start.
10. Standardmæssig afvisning af write-kortet, så der ikke skrives på riggen.
11. Verifikation af `confirmation_denied` og fravær af `step_started`/`step_succeeded`.
12. Verifikation af, at den forbrugte plan ikke kan startes igen.
13. Sletning af test-memoryens indhold og proveniens til en content-free tombstone.
14. Lokal JSON-rapport uden Bearer-token eller memoryværdi.

## Forudsætninger

Kør fra repository-roden på ModelRig-maskinen.

- Branchen `agent/agent3-integration-draft-v2` er checket ud.
- Go-backend og worker kører.
- `KALIV_AGENT3_ENABLED=1` var sat ved processtart.
- `KALIV_TOOLS_ENABLED=1` var sat ved processtart.
- Ollama kører, og den valgte planner-model er installeret.
- Et gyldigt paired device-token er tilgængeligt i `MODELRIG_TOKEN`.

Eksempel:

```powershell
$env:KALIV_AGENT3_ENABLED = "1"
$env:KALIV_TOOLS_ENABLED = "1"
$env:MODELRIG_TOKEN = "<paired device token>"
$env:KALIV_AGENT3_PLANNER_MODEL = "qwen3:8b"
```

Token skal ligge i miljøet og må ikke skrives direkte på kommandolinjen eller i rapporten.

## Sikker standardkørsel — write afvises

Denne kørsel validerer confirmation-kæden, men udfører ikke `note_append`:

```powershell
python scripts/agent3_rig_validation.py `
  --base-url http://127.0.0.1:8080 `
  --planner-model $env:KALIV_AGENT3_PLANNER_MODEL
```

Forventet slutlinje:

```text
PASS: Agent 3.0 memory/planner/plan/confirmation/audit validation completed (write denied safely)
```

Den lokale rapport skrives som standard til:

```text
validation/agent3-rig-validation-latest.json
```

Denne flydende fil er git-ignoreret, fordi den indeholder hostnavn og lokale run-/memory-id'er.
Den indeholder ikke token, memoryværdi eller den konkrete write-marker.

## Eksplicit write-validering

Kør først standardtesten og gennemgå plan, confirmation-summary og rapport.
Derefter kan append-only write-stien bevises særskilt:

```powershell
python scripts/agent3_rig_validation.py `
  --base-url http://127.0.0.1:8080 `
  --planner-model $env:KALIV_AGENT3_PLANNER_MODEL `
  --approve-write
```

Denne variant godkender præcis ét `note_append` med en unik validation-marker.
Harnessen nægter at godkende, hvis planneren ændrer teksten, tilføjer andre steps eller
vælger et andet tool. `note_append` kan kun append'e til den faste Kaliv-notefil; den kan
ikke overskrive, slette eller vælge en modelstyret sti.

Forventet slutlinje:

```text
PASS: Agent 3.0 memory/planner/plan/confirmation/audit validation completed (write approved)
```

## Pass-kriterier

En kørsel tæller kun som bestået, når rapporten har:

```json
{
  "schema": "kaliv-agent3-rig-validation/v1",
  "success": true,
  "cleanup": {
    "deleted": true,
    "content_erased": true,
    "source_ref_erased": true
  }
}
```

Derudover skal følgende være opfyldt:

- memory receipt har `requested=true`, `sent_to_model=true` og `target=local`,
- receiptens SHA matcher den eksakte context-preview-blok,
- read-planen indeholder kun `rig_status` med `risk=read`,
- write-planen indeholder kun `note_append` med `risk=write`,
- write-run stopper i `waiting_confirmation`,
- standardkørslen ender `cancelled` med step-state `denied`,
- standardkørslen indeholder ingen `step_started` eller `step_succeeded` for write-run,
- replay af den forbrugte write-plan returnerer HTTP 409,
- den midlertidige memory ender som en indholdsfri tombstone.

## Gem gennemgået evidens

Efter en fysisk rig-kørsel skal den flydende rapport gennemgås og kopieres til en dateret
fil, før den eventuelt committes:

```powershell
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
Copy-Item `
  validation/agent3-rig-validation-latest.json `
  "validation/agent3-rig-validation-$stamp.json"
```

Før commit skal hostnavn og øvrige lokale identifiers vurderes. Bearer-token og memorytekst
må aldrig være til stede; harness-testen i CI kontrollerer netop denne redaktion.

## CI-kontrakt

`tests/worker_agent3_rig_validation_cli.py` bruger en lokal fake gateway og beviser:

- fuld standard-deny-kæde uden netværk eller Ollama,
- receipt-binding mellem preview og plan-start,
- eventrækkefølge før og efter confirmation,
- ingen write-eksekvering efter deny,
- HTTP 409 ved genbrug af plan-id,
- content-free memory-cleanup,
- fravær af token, memoryværdi og konkret marker i rapporten.

CI beviser kontrakten og harnessen. Den beviser **ikke** GPU/Ollama-, service-, Tailscale-
eller on-device-adfærd på Anders' fysiske rig. Den del er først dokumenteret, når en ægte,
dateret rapport fra ovenstående procedure findes.

## Stadig uden for scope

Denne validering åbner ikke:

- Agent 3.0 i normal chat-routing,
- automatisk memory retrieval,
- automatisk cloud fallback,
- unattended write-godkendelse,
- proactive scheduler,
- tredjeparts-MCP eller vilkårlige filtools.
