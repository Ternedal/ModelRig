# Kaliv Agent 3.0 — Validation Center

Status: **developer-only, read-only og CI-kompileret på Android og desktop.**

Validation Center viser den redigerede promotionsvurdering fra:

```text
GET /api/v1/experimental/agent3/status
```

Skærmene producerer ikke evidens og kan ikke:

- vælge eller uploade en rapport,
- ændre `KALIV_AGENT3_VALIDATION_REPORT`,
- godkende et tool-step,
- åbne Agent 3.0 i normal chat-routing,
- aktivere produktion.

Begge klienter afviser statusresponsen som ugyldig, hvis enten topniveauet eller
`rig_validation` påstår `production_activation=true`.

## Forudsætninger

- Agent 3.0-worker-endpointet er startet med `KALIV_AGENT3_ENABLED=1`.
- Go-gatewayen kan nå worker-processen.
- Et gyldigt paired device-token er gemt i klienten eller sat i `MODELRIG_TOKEN`.
- Promotion-evidens produceres separat med `scripts/agent3_rig_evidence.py`.
- Worker-processen kender rapportstien gennem `KALIV_AGENT3_VALIDATION_REPORT`, hvis en
  konkret rapport skal vurderes.

Uden konfigureret rapport er skærmen stadig brugbar. Den viser blot den konkrete blocker,
for eksempel `report_path_not_configured`, `report_not_found` eller `report_stale`.

## Android

Validation Center er ikke en launcher-destination og åbnes kun med den eksplicitte
intent-extra:

```powershell
adb shell am start -S `
  -n dk.ternedal.modelrig/.MainActivity `
  --ez dk.ternedal.modelrig.extra.AGENT3_VALIDATION true
```

Android-klienten bruger den rig-URL og det device-token, som allerede ligger i
`TokenStore`. Skærmen foretager automatisk det første read-only statuskald og kan derefter
opdateres manuelt.

## Desktop

```powershell
cd desktop
.\gradlew.bat :composeApp:run --args="--agent3-validation"
```

Desktop-klienten læser standarder fra de eksisterende desktop-indstillinger og følgende
miljøvariabler:

```powershell
$env:MODELRIG_AGENT3_URL = "http://127.0.0.1:8080"
$env:MODELRIG_TOKEN = "<paired device token>"
```

URL og token kan ændres midlertidigt på developer-skærmen. Tokenfeltet vises maskeret og
værdien gemmes ikke af Validation Center.

## Det skærmen viser

### Promotionsniveau

- `Promotion blokeret`
- `Developer-preview dokumenteret`
- `Write-pilot dokumenteret`

### Versions- og freshness-binding

- aktuel worker-version,
- valideret version,
- planner-model,
- faktisk write-beslutning,
- rapportens alder og maksimale tilladte alder,
- rapportens SHA-256.

### Fail-closed gates

- rapport konfigureret,
- rapport fundet,
- struktur gyldig,
- rapport frisk,
- version matcher,
- produktion fortsat låst.

### Maskinelle beviser

- eksperimentel status,
- memory receipt-binding,
- read-eventkæde,
- confirmation før write,
- single-use plan,
- content-free cleanup,
- faktisk write-eksekvering.

`write_execution=false` er forventet i den sikre standardrapport, hvor confirmation bliver
afvist. Det blokerer write-pilot, men ikke developer-preview, når resten af beviskæden er
gyldig.

### Blockers og advarsler

Skærmene viser evaluatorens maskinlæsbare `reasons`, `write_pilot_reasons` og `warnings`
uden at forsøge at oversætte dem til en mere lempelig klientpolicy.

## Sikkerhedsgrænse

Validation Center har bevidst ingen POST-, PUT-, PATCH- eller DELETE-metoder. Transporten
har kun én offentlig operation: hent den Bearer-beskyttede status.

En grøn skærm er dokumentation for det niveau, rapporten beviser. Den er ikke en runtime-
feature flag, en godkendelse eller en produktionsaktivering.
