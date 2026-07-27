# T-022 fysisk append-only write-pilot

**Status:** dormant operator-wizard. Den hjælper med den fysiske kampagne, men
kan ikke selv se en skærm, godkende en write eller gøre evidens grøn uden de
faktiske Android-/Windows-handlinger.

Start på Windows-riggen fra repository-roden:

```text
START_AGENT3_WRITE_PILOT_PHYSICAL.cmd
```

Wizard'en fortsætter som standard en eksisterende kampagne. Brug kun `--reset`,
når hele den tidligere kampagne bevidst skal arkiveres; det kræver den eksakte
attestering `ARCHIVE T022`. Evidens slettes aldrig automatisk.

## Hvad wizard'en automatiserer

- checker exact branch, Git SHA, version, code fingerprint og ren working tree;
- konfigurerer de eksisterende lokale database- og notes-stier;
- spørger skjult efter `MODELRIG_TOKEN` og den fælles approval-secret;
- starter exact-head backend/worker og kører rig-validation;
- bygger og installerer exact-head Android-APK på præcis én ADB-enhed;
- forbereder de 20 uforudsigelige kandidatbundne markører;
- kører den eksisterende GET-only T-022-preflight;
- åbner Android- og desktop-Agent 3-surfaces;
- GET-verificerer hvert completed positivt run mod server, notes, approval-store
  og ToolGate-audit før manifestbinding;
- genoptager ved næste ubundne ordinal efter et sikkert stop;
- initialiserer negativjournalen **først efter 20/20 bindinger**, så journalen
  bindes til det endelige manifest;
- registrerer response body, status og run-id for de syv negative cases i den
  eksisterende hashkædede SQLite-journal;
- kompilerer negativ JSON direkte fra journalen;
- kører den eksisterende forensic collector over run/event-ledger, approval-use,
  audit og den faktiske `notes.md`.

## Hvad wizard'en ikke gør

Den sender ingen POST-, approval-, confirmation-, write-, retry-, cancel- eller
replan-request. De fysiske handlinger skal udføres af operatøren på de normale
klient-surfaces. Den kan heller ikke merge, pushe, tagge, release eller aktivere
produktion.

`operator-state.json` er kun resume-hjælp og er markeret `advisory_only=true`.
Det er manifestet, journalen og collectorens databaser, der er evidens.

## Før start

- riggen skal have Android Platform Tools (`adb`) på PATH;
- præcis én Android-enhed skal være tilsluttet og godkendt til USB-debugging;
- `KALIV_AGENT3_APPROVAL_SECRET` skal være den samme i backend og worker og være
  mindst 32 tegn;
- den parrede device-token skal være gyldig;
- databaser og `KALIV_TOOLS_DIR` skal pege på den candidate-stack, der faktisk
  køres;
- andre write/admin/destructive tools skal være deaktiveret. Preflighten blokerer
  ellers kampagnen og viser navnene.

Standardstier følger workerens egne defaults:

- data root: `%LOCALAPPDATA%\Kaliv`, medmindre `KALIV_DATA_DIR` er sat;
- Agent 3: `kaliv-agent3.db`;
- approval-use: `kaliv-agent3-approvals.db`;
- audit: `kaliv-audit.db`;
- notes: `%USERPROFILE%\Documents\Kaliv\notes.md`, medmindre
  `KALIV_TOOLS_DIR` er sat.

På en helt ren rig må wizard'en oprette den tomme kanoniske
`agent3_approval_uses`-tabel. En eksisterende approval-database ændres eller
nulstilles aldrig.

## Positive runs 1–20

For hvert run viser wizard'en den komplette marker. Brug markeren som hele
`note_append.text` — ingen tekst før eller efter.

Før approval kræves den eksakte frase:

```text
PREVIEW T022 01
```

Efter fysisk approval og completed run kræves:

```text
APPEND T022 01
```

Ordinalen ændres for hvert run. Før binding kontrolleres automatisk:

- run state er `completed`;
- route er `rig_tools_local`;
- præcis ét `note_append`-step med eksakt marker og `succeeded` state;
- eventkæden indeholder approval, confirmation, step execution og completion;
- markeren findes præcis én gang i `notes.md`;
- præcis én approval-use-række findes for run-id'et;
- præcis én executed ToolGate-audit findes for markeren.

Run-id indtastes skjult. Det gemmes i manifestet, fordi collectorens forensics
skal kunne sammenholde det med de lokale ledgers.

## Syv negative cases

Journalen oprettes først, når alle 20 positive run-id'er er bundet. Cases køres i
den eksisterende kontraktrækkefølge:

1. `deny`
2. `timeout`
3. `changed_args`
4. `stale_revision`
5. `replay`
6. `concurrent_approval`
7. `stop_retry_replan`

Hver case kræver først:

```text
START NEGATIVE <case-navn>
```

og afsluttes kun efter:

```text
DONE NEGATIVE <case-navn>
```

Wizard'en sender ikke de adversarial requests. Operatøren udfører dem og indsætter
HTTP-status, eksakt response body og involveret run-id. Response body kan enten
indsættes som én linje eller angives som `@C:\sti\response.json`.

Journalen registrerer før-/eftertal direkte fra `notes.md` og approval-use-
databasen. Den eksisterende recorder håndhæver blandt andet:

- denial: `[200]`, ingen append eller approval-use;
- timeout/changed args/stale revision/replay: `[409]`, ingen ny sideeffekt;
- concurrent approval: præcis én `200`, én `409`, note- og approval-delta præcis 1;
- stop/retry/replan: mindst tre `200`/`202`/`409`-observationer og ingen ny append.

## Resume og faser

Wizard'en kan køres igen efter Ctrl+C eller anden sikker fejl. Den genlæser exact
candidate, preflight, manifest og journal og fortsætter ved den første uafsluttede
enhed.

Faser kan køres separat:

```text
START_AGENT3_WRITE_PILOT_PHYSICAL.cmd --phase prepare
START_AGENT3_WRITE_PILOT_PHYSICAL.cmd --phase positive
START_AGENT3_WRITE_PILOT_PHYSICAL.cmd --phase negative
START_AGENT3_WRITE_PILOT_PHYSICAL.cmd --phase collect
```

`--phase prepare` udfører kun setup/preflight. `--phase positive` fortsætter de
20 positive runs. `--phase negative` kræver 20/20 bindinger. `--phase collect`
kræver et fuldt bundet manifest og en færdig negativjournal.

## Endelig dom

En grøn rapport kræver:

- 20/20 eksakte append-runs;
- én device-attribution på alle positive approvals;
- præcis én note- og audit-sideeffekt per positiv marker;
- 7/7 komplette negative cases;
- ingen skjulte positive-prefix retry/replan-runs;
- samme version, SHA, code fingerprint og rig-validation som ved preparation;
- samlet kampagnevindue højst 12 timer og friskhed højst 24 timer.

Rapporten skrives til:

```text
validation\agent3-write-pilot-latest.json
```

Selv en grøn rapport indeholder altid `production_activation=false`. Den fysiske
pilot promoverer ikke routing, merger ikke en PR og udgiver ikke en release.
