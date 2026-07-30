# Agent 3 normal task-UI — fysisk validering (T-021)

Denne validering er den sidste ikke-CI-del af T-021. Den binder den normale
read-only taskflade på **Android og Windows desktop** til den samme frosne
candidate, den samme readiness/pilot-evidens og ét live read-only run.

Harnessen ændrer ingen featureflag, starter ingen generic Agent 3-run, bekræfter
ingen writes og gemmer aldrig device-token, prompt, run-id eller råt modelsvar.

## Hvad rapporten beviser

`scripts/agent3_task_ui_validation.py` kræver samtidig:

- exact servervalg `agent3_readonly` med fallback `agent2`;
- frisk 20/20 read-only pilot og matchende fysisk rig-validation;
- preview uden execution, kun `rig_tools_local`, lokale idempotente read-steps;
- capability receipt uden blockers og med `production_activation=false`;
- single-use start, task-scoped polling og terminalt `completed` run;
- ingen confirmation-events;
- fysisk Android-observation af surface, årsag, plan/review, tool-status, Stop,
  fallback, receipts, replans, outcome og normal Agent 2-chat;
- samme fysiske observationsmatrix på Windows desktop;
- ét kompakt, repository-lokalt og SHA-256-bundet artifact pr. klient.

CI kan teste parseren og en lokal fixture-server, men kan ikke udfylde de fysiske
observationer. Eksempelfilen er derfor bevidst rød.

## Forudsætninger

1. Brug en **ny frossen candidate**, der faktisk indeholder T-021-stakken. Den
   tidligere frosne candidate må ikke omskrives eller forsynes med efterfølgende
   klientbevis.
2. Kør fra den præcise rene candidate-checkout eller den attesterede, urørte
   release-ZIP på riggen.
3. Backend og worker kører med `KALIV_AGENT3_ENABLED=1`.
4. `KALIV_AGENT3_TASK_UI=1` og `KALIV_AGENT3_PILOT_REPORT` peger på den friske,
   candidate-bundne 20/20-pilotrapport.
5. Android-buildet og desktop-buildet er bygget fra samme candidate.
6. Et paired device-token ligger kun i miljøvariablen `MODELRIG_TOKEN`.

Kontrollér candidate før fysisk test:

```powershell
git status --short
git rev-parse HEAD
Get-Content VERSION
python scripts\freeze_check.py
```

## 1. Opret observationsfil og artifact-mappe

```powershell
Copy-Item `
  eval\agent3_task_ui_observations.example.json `
  validation\agent3-task-ui-observations.json

New-Item -ItemType Directory `
  validation\agent3-task-ui-evidence `
  -Force | Out-Null
```

Artifactet kan være en kort tekstlog, screenshot-samling eller komprimeret
skærmoptagelse. Det skal være en almindelig ikke-tom fil på højst 32 MiB. Brug
ikke symlinks. Gem eksempelvis:

```text
validation/agent3-task-ui-evidence/android.txt
validation/agent3-task-ui-evidence/desktop.txt
```

## 2. Android — `Kaliv Opgaver`

Åbn long-press-genvejen **Opgaver** på den installerede Android-candidate.
Observer og dokumentér:

1. `Agent 3 read-only` og serverårsagen `agent3_readonly_selected` er synlige.
2. En opgave giver et plan-preview, og ingen tool-status ændres før **Start**.
3. Planens read-only felter, receipt og evidensbinding er synlige.
4. Efter Start er tool-status, events/replans og terminalt outcome synlige.
5. Start en plan med mindst to read-steps, så Stop kan observeres.
6. Når runnet er aktivt, fjern pilotrapporten **midlertidigt fra dens konfigurerede
   path ved rename**; redigér aldrig rapportens bytes. Opdatér routing i klienten.
7. Klienten viser Agent 2-fallback, men det persistede run og **Stop** forbliver
   synlige. Stop skal ende i `cancelled`.
8. Gendan pilotrapporten til præcis samme path og verificér dens SHA-256.
9. Åbn normal chat via fallback og gennemfør én almindelig Agent 2 round-trip.
10. Kontrollér, at skærmen ikke indeholder write-, confirmation-, retry- eller
    generic Agent 3-kontroller.

Gem et kompakt artifact med de observerede trin og terminalstater.

## 3. Windows desktop — `--tasks`

Start den præcise desktop-candidate med:

```powershell
.\Kaliv.exe --tasks
```

Gentag samme observationsmatrix som på Android. Knappen **Normal chat** skal
skifte til den eksisterende almindelige desktop-app, også hvis et developer-flag
ved en fejl blev kombineret med `--tasks`.

## 4. Udfyld og hash artifacts

Udfyld begge `candidate`-objekter med candidate-version, Git-SHA og workerens
`code_sha256`. Sæt kun et check til `true`, når det faktisk er observeret.

Beregn artifact-hashes:

```powershell
(Get-FileHash `
  validation\agent3-task-ui-evidence\android.txt `
  -Algorithm SHA256).Hash.ToLowerInvariant()

(Get-FileHash `
  validation\agent3-task-ui-evidence\desktop.txt `
  -Algorithm SHA256).Hash.ToLowerInvariant()
```

Indsæt hashene i observationsfilen og sæt `observed_at` til en timezone-aware
ISO-8601-tid. Observationerne må højst være 24 timer gamle, når produceren køres.

## 5. Kør live probe og producer rapporten

```powershell
$env:MODELRIG_TOKEN = "<paired device token>"

python scripts\agent3_task_ui_validation.py `
  --base-url http://127.0.0.1:8080 `
  --manual-observations validation\agent3-task-ui-observations.json `
  --report validation\agent3-task-ui-validation-latest.json
```

Live-proben kører én almindelig read-only task via de samme readiness-, preview-,
start- og statusruter som klienterne. Ved en mislykket probe forsøger harnessen
best-effort at annullere det task-scoped run.

Exit codes:

- `0`: live-probe og begge fysiske klientobservationer er grønne;
- `1`: der er skrevet en rød rapport med redacted fejltype og fejlbesked.

## 6. Review

Før rapporten må indgå som permanent evidens, kontrollér:

- candidate version, Git-SHA og code fingerprint matcher den installerede build;
- readiness-bindingens pilot-SHA, candidate-SHA og rig-validation-SHA er udfyldt;
- preview har `executed=false` og kun lokale idempotente reads;
- start/status-receipt er identisk med preview-receipt;
- runnet er `completed`, alle steps er `succeeded`, og ingen confirmation-event
  findes;
- Android og desktop har alle 13 checks `true`;
- begge artifact-hashes matcher de lokale filer;
- `gate.passed=true`, `production_activation=false` og
  `normal_chat_route_unchanged=true`.

Den rullende rapport og de rå artifacts forbliver lokale. Kun en dateret,
manuelt reviewet rapport må eventuelt committes.
