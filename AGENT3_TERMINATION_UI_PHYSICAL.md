# Kaliv Agent 3 — fysisk T-023 termination UI-validering

Status: **softwareflowet er CI-grønt; den fysiske Android/Windows-observation mangler fortsat.**

Denne runbook beskriver den eneste kørsel, der må producere
`validation/agent3-termination-ui-physical-latest.json` som grøn.

## Start

På Windows-riggen:

1. Tilslut præcis én Android-enhed med USB-debugging godkendt.
2. Sørg for, at `adb`, Git, Python, PowerShell, Go, Java/Gradle og Ollama er tilgængelige.
3. Dobbeltklik:

```text
START_AGENT3_TERMINATION_UI_PHYSICAL.cmd
```

Wizard'en skifter kun til den versionbundne branch
`agent/t023-termination-physical-operator`, kræver ren working tree og fast-forward
mod `origin`, starter exact-head kandidatstacken og producerer frisk readiness.

## Hvad wizard'en gør automatisk

- kontrollerer VERSION, Git-SHA, worker-fingerprint og ren working tree;
- arkiverer tidligere rolling T-023-filer før en ny kampagne;
- starter eller genstarter backend/worker med de kandidatbundne rapportstier;
- kører frisk Agent 3 rig-validation og read-only pilot, hvis serveren ikke vælger
  `agent3_readonly`;
- kræver `production_activation=false` og uændret normal chat-route;
- bygger exact-head Android APK og installerer den med `adb install -r`;
- åbner Android `Kaliv Opgaver` eller developer Agent 3 via eksplicit intent-extra;
- åbner desktop med `--tasks` eller `--agent3`;
- tager Android- og Windows-screenshot til den prædefinerede evidence-path;
- SHA-256-binder artifacts og rå run-id uden at gemme run-id'et;
- kører den uafhængige T-023-validator og derefter den additive kandidatkampagne.

## Hvad wizard'en bevidst ikke kan gøre

Den kan ikke se eller forstå UI'en på dine vegne. Den sætter derfor ikke en case
til bestået alene fordi et vindue kunne åbnes.

Hver fysisk case kræver to nøjagtige operatørfraser:

```text
OBSERVERET <platform> <case>
KVITTERING <platform> <case>
```

Eksempel:

```text
OBSERVERET android non_interruptible
KVITTERING android non_interruptible
```

Forkert eller manglende frase stopper sikkert, og den delvist udfyldte røde
observationsfil bevares.

Wizard'en kan heller ikke:

- merge, pushe eller ændre en PR;
- tagge eller publicere en release;
- aktivere produktion;
- opfinde en runtime termination-handle;
- gøre en manglende fysisk case grøn;
- genbruge samme run-id mellem cases.

## Fysiske cases

Kandidaten kræver på både Android og Windows:

### `non_interruptible`

Surface: normal `Kaliv Opgaver`.

Brug en capability med `termination=none`. Mens tool-steppet er `executing`, skal
UI'en vise:

- separat Plan, Model stream og Aktivt tool;
- `Stop plan`, men ingen løs/bare `Stop`;
- plan-effekt `prevent_future_steps_active_tool_continues`;
- ingen tool-handle og ingen direkte tool-kontrol;
- fortsat polling efter plan-stop;
- en sand terminal tool-tilstand.

### `cooperative_declaration`

Surface: developer Agent 3.

Brug en capability med `termination=cooperative`. Kvitteringen afgør, om den
konkrete runtime faktisk har en bound handle. Wizard'en tillader derfor både:

- ingen handle og ingen direkte kontrol; eller
- en konkret handle med `available`/`pending` request-state og målt cleanup på
  højst 5000 ms.

Det er ikke tilladt at markere en handle alene fordi capability-descriptoren siger
`cooperative`.

### `late_completion`

Surface: normal `Kaliv Opgaver`.

Brug en `termination=none` capability, stop planen mens tool-steppet kører, og
vent til UI'en viser præcis:

```text
completed_after_cancel
```

Det er hele formålet med casen: klienten må ikke omskrive en sen completion til
`cancelled` eller stoppe polling, blot fordi planen allerede er terminal.

### `runtime_bound`

Denne case findes kun, hvis den eksakte capability-inventory indeholder mindst én
`termination=runtime` capability.

I så fald er en konkret bound handle, direkte tool-kontrol og cleanup på højst
5000 ms obligatorisk. Hvis kandidaten ikke har en runtime-capability, bliver
casen slet ikke oprettet; den må ikke simuleres.

## Screenshot og receipt

Efter du har stoppet planen og ventet på sluttilstanden:

1. Placér appen på den endelige kvittering.
2. Tryk Enter i wizard'en; screenshot tages automatisk.
3. Attestér `OBSERVERET ...`.
4. Indsæt run-id skjult. Kun SHA-256 gemmes.
5. Vælg tool fra kandidatens faktiske termination-inventory.
6. Indtast den synlige `reason`, tool-state og eventuel handle/cleanup.
7. Attestér `KVITTERING ...`.

Artifacts gemmes under:

```text
validation/agent3-termination-ui-evidence/android/
validation/agent3-termination-ui-evidence/windows/
```

## Resultater

Observationsarket:

```text
validation/agent3-termination-ui-observations.json
```

T-023-rapporten:

```text
validation/agent3-termination-ui-physical-latest.json
```

Additiv kandidatkampagne:

```text
validation/physical-validation-termination-candidate-latest.json
```

En grøn T-023-rapport kræver alle Android- og Windows-cases inden for samme
12-timers observationsvindue og højst 24 timer gamle. Kandidatkampagnen kan stadig
være blokeret af andre manglende eller stale base-beviser; det ændrer ikke
T-023-resultatet og bliver vist særskilt.

## Sikker stop og genstart

Ved Ctrl+C, forkert attestering, manglende ADB-enhed eller anden fejl stopper
wizard'en med non-zero exitkode. Delvis observationsfil og allerede tagne artifacts
bevares, men en ny kørsel arkiverer rolling T-023-resultaterne og starter en ny
kandidatbundet kampagne.

Ingen grøn status må kopieres manuelt fra en ældre kandidat. VERSION, Git-SHA,
worker-fingerprint, capability-inventory, observationer og artifacts genvalideres
uafhængigt ved hver verify-kørsel.
