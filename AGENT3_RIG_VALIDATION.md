# Kaliv Agent 3.0 — validering på den fysiske rig

Status: **harness, promotions-gate og statusvisning er implementeret og CI-testet; fysisk rig-validering er endnu ikke udført.**

Denne procedure validerer den eksperimentelle Agent 3.0-sti gennem den rigtige
Bearer-beskyttede Go-gateway og den lokale Ollama-planner. Den normale Android-,
desktop- og Agent v2-chat-routing er fortsat urørt.

## To valideringslag

Der findes nu to kommandoer med forskellige formål:

- `scripts/agent3_rig_validation.py` beviser den konkrete agentadfærd.
- `scripts/agent3_rig_evidence.py` kører samme harness, binder rapporten til den
  aktuelle backend- og worker-version og kontrollerer rapporten med den samme
  fail-closed evaluator, som Agent 3.0-status bruger.

Til promotion-evidens skal `agent3_rig_evidence.py` anvendes. Den almindelige harness
forbliver nyttig til fejlsøgning, men en rapport uden versionsbinding kan ikke åbne et
promotionsniveau.

## Hvad harnessen beviser

Den underliggende harness gennemfører én samlet kæde:

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

Promotion-wrapperen tilføjer desuden:

15. Læsning af backend-versionen fra den beskyttede `/api/v1/status`.
16. Læsning af worker-versionen fra Agent 3.0-status.
17. Afvisning før testen, hvis backend- og worker-version ikke matcher.
18. Krav om en eksplicit navngivet lokal planner-model.
19. Atomisk versionsbinding af den persistente rapport.
20. Evaluering af freshness, versionsmatch, receipt-binding, events, single-use og cleanup.
21. Permanent `production_activation=false`, uanset rapportens resultat.

## Promotionsniveauer

### Ingen gyldig rapport

Agent 3.0 forbliver developer-only, og status viser konkrete blocker-reasons, eksempelvis:

- `report_path_not_configured`,
- `report_not_found`,
- `report_stale`,
- `validated_version_mismatch`,
- `memory_binding_not_proven`.

### Developer preview

En frisk standardrapport med `write_decision=deny` kan give:

```text
eligible_for_developer_preview=true
eligible_for_write_pilot=false
production_activation=false
```

Den beviser plan-, memory-, read-, confirmation-, single-use- og cleanup-kæden uden at
udføre et write.

### Write pilot

En separat rapport fra en eksplicit `--approve-write`-kørsel kan give:

```text
eligible_for_developer_preview=true
eligible_for_write_pilot=true
production_activation=false
```

Det niveau beviser også den godkendte append-only write-eventkæde. Det aktiverer fortsat
ikke normal chat-routing, automatiske writes eller produktion.

## Forudsætninger

Kør fra repository-roden på ModelRig-maskinen.

- Branchen `agent/agent3-integration-draft-v2` er checket ud.
- Go-backend og worker kører fra samme build/version.
- `KALIV_AGENT3_ENABLED=1` var sat ved processtart.
- `KALIV_TOOLS_ENABLED=1` var sat ved processtart.
- Ollama kører, og den valgte planner-model er installeret.
- Et gyldigt paired device-token er tilgængeligt i `MODELRIG_TOKEN`.
- Promotionsrapportens sti er kendt af worker-processen.

Eksempel før worker-start:

```powershell
$env:KALIV_AGENT3_ENABLED = "1"
$env:KALIV_TOOLS_ENABLED = "1"
$env:MODELRIG_TOKEN = "<paired device token>"
$env:KALIV_AGENT3_PLANNER_MODEL = "qwen3:8b"
$env:KALIV_AGENT3_VALIDATION_REPORT = Join-Path `
  (Get-Location) `
  "validation\agent3-rig-validation-latest.json"
```

Rapportfilen behøver ikke eksistere ved worker-start. Status viser `report_not_found`, indtil
evidence-wrapperen har skrevet filen. Evaluatoren læser filen ved hvert statuskald, så en
vellykket kørsel bliver synlig uden endnu en genstart, når stien allerede fandtes i miljøet.

Token skal ligge i miljøet og må ikke skrives direkte på kommandolinjen eller i rapporten.

## Sikker standardkørsel — developer-preview-evidens

Denne kørsel validerer confirmation-kæden, men udfører ikke `note_append`:

```powershell
python scripts/agent3_rig_evidence.py `
  --base-url http://127.0.0.1:8080 `
  --planner-model $env:KALIV_AGENT3_PLANNER_MODEL
```

Forventet slutlinje:

```text
PASS: version-bound Agent 3.0 evidence produced (eligible_for=developer-preview, production_activation=false)
```

Den lokale rapport skrives som standard til:

```text
validation/agent3-rig-validation-latest.json
```

Denne flydende fil er git-ignoreret, fordi den indeholder hostnavn og lokale run-/memory-id'er.
Den indeholder ikke token, memoryværdi eller den konkrete write-marker.

## Eksplicit write-pilot-evidens

Kør først standardtesten og gennemgå plan, confirmation-summary, events og rapport.
Derefter kan append-only write-stien bevises særskilt:

```powershell
python scripts/agent3_rig_evidence.py `
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
PASS: version-bound Agent 3.0 evidence produced (eligible_for=write-pilot, production_activation=false)
```

## Se den redigerede promotionsstatus

Status går gennem den eksisterende Bearer-gateway:

```powershell
$headers = @{ Authorization = "Bearer $env:MODELRIG_TOKEN" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8080/api/v1/experimental/agent3/status" `
  -Headers $headers
```

Svaret indeholder blandt andet:

```json
{
  "worker_version": "<current version>",
  "production_activation": false,
  "rig_validation": {
    "configured": true,
    "fresh": true,
    "version_match": true,
    "eligible_for_developer_preview": true,
    "eligible_for_write_pilot": false,
    "production_activation": false,
    "proofs": {
      "status": true,
      "memory_binding": true,
      "read_path": true,
      "confirmation_path": true,
      "write_execution": false,
      "single_use": true,
      "cleanup": true
    }
  }
}
```

Statusassessmenten returnerer ikke hostnavn, base-URL, memory-id'er, run-id'er, step-id'er,
source references eller validation-marker.

## Freshness og versionsbinding

Standardgrænsen er syv døgn:

```powershell
$env:KALIV_AGENT3_VALIDATION_MAX_AGE_HOURS = "168"
```

Tilladte værdier er større end nul og højst 720 timer. Ugyldig konfiguration fejler lukket.

En softwareopdatering ændrer backend-/worker-versionen. En tidligere rapport bliver dermed
`validated_version_mismatch` og kan ikke genbruges til den nye build. Der skal køres en ny
fysisk validering på den opdaterede rig.

Evaluatoren accepterer kun en eksplicit konfigureret almindelig fil. Den afviser blandt andet:

- symlinks,
- manglende, tomme eller for store rapporter,
- ugyldig JSON,
- fremtidige eller for gamle timestamps,
- forskellige backend-/worker-versioner,
- manglende planner-model,
- uoverensstemmelse mellem erklæret og faktisk write-decision,
- manipuleret receipt-SHA eller inkluderede memory-id'er.

## Pass-kriterier

En promotion-grade kørsel tæller kun som bestået, når rapporten blandt andet har:

```json
{
  "schema": "kaliv-agent3-rig-validation/v1",
  "success": true,
  "target": {
    "modelrig_version": "<current version>",
    "worker_version": "<current version>",
    "planner_model": "<explicit local model>",
    "write_decision": "deny"
  },
  "cleanup": {
    "deleted": true,
    "content_erased": true,
    "source_ref_erased": true
  }
}
```

Derudover skal følgende være opfyldt:

- backend- og worker-version matcher før kørsel,
- memory receipt har `requested=true`, `sent_to_model=true` og `target=local`,
- receiptens SHA og inkluderede ids matcher den eksakte context-preview-blok,
- read-planen indeholder kun `rig_status` med `risk=read`,
- write-planen indeholder kun `note_append` med `risk=write`,
- write-run stopper i `waiting_confirmation`,
- standardkørslen ender `cancelled` med step-state `denied`,
- standardkørslen indeholder ingen `step_started` eller `step_succeeded` for write-run,
- write-pilot-kørslen har den fulde approved/start/succeeded/completed-eventkæde,
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
må aldrig være til stede; CI-testene kontrollerer netop denne redaktion.

## CI-kontrakt

Følgende tests kører uden Ollama, GPU eller netværk:

- `tests/worker_agent3_rig_validation_cli.py` beviser den underliggende harness.
- `tests/worker_agent3_validation_gate.py` beviser fail-closed promotionsreglerne.
- `tests/worker_agent3_validation_status.py` beviser read-only status og permanent
  `production_activation=false`.
- `tests/worker_agent3_rig_evidence.py` beviser backend-/worker-versionbinding og de to
  promotionsniveauer.

CI beviser kontrakten, wrapperen og evaluatorens regler. Den beviser **ikke** GPU/Ollama-,
service-, Tailscale- eller on-device-adfærd på Anders' fysiske rig. Den del er først
dokumenteret, når en ægte, dateret rapport fra ovenstående procedure findes.

## Stadig uden for scope

Denne validering åbner ikke:

- Agent 3.0 i normal chat-routing,
- automatisk memory retrieval,
- automatisk cloud fallback,
- unattended write-godkendelse,
- proactive scheduler,
- tredjeparts-MCP eller vilkårlige filtools,
- automatisk promotion eller produktionsaktivering.
