# T-022 positiv write-pilot operator

**Status:** dormant fysisk operator til del 1 af T-022. Den forbereder og binder de 20 positive `note_append`-runs, men sender ingen preview-, start-, approve-, retry-, replan- eller cancel-request.

## Hvad den automatiserer

Start på Windows-riggen fra den eksakte candidate-branch:

```text
START_AGENT3_WRITE_PILOT_POSITIVE.cmd
```

Wizard'en:

1. checker den eksakte branch og kandidatidentitet;
2. kræver en eksisterende kandidatbundet rig-validation;
3. læser `MODELRIG_TOKEN` skjult;
4. finder de tre SQLite-databaser og `notes.md`;
5. forbereder et nyt 20-run manifest, hvis det ikke findes;
6. kører den eksisterende authenticated GET-only T-022-preflight;
7. bygger og installerer den eksakte Android-debugklient;
8. åbner developer-Agent 3 på Windows og Android for hvert run;
9. kopierer den eksakte marker til Windows-clipboard;
10. kræver tre konkrete operatørattesteringer og tre screenshots;
11. binder det returnerede run-id til den rigtige ordinal;
12. gemmer kandidatbundne observationer efter hvert run;
13. kan fortsætte sikkert efter afbrydelse, når manifest, preflight og observationsjournal stadig matcher præcist.

## Før start

Den live stack skal allerede være startet med den eksakte kandidat og den tilsigtede T-022-konfiguration:

- backend og worker deler samme `KALIV_AGENT3_APPROVAL_SECRET`;
- `KALIV_AGENT3_APPROVAL_REQUIRED=1` er live;
- `note_append` er den eneste aktive write-capability;
- øvrige write/admin/destructive capabilities er ikke aktive;
- Agent 3 developer-surface er tilgængelig;
- den parrede Android-enhed kan godkende confirmation-kortet;
- rig-validation-rapporten er frisk og `eligible_for_write_pilot=true`.

Wizard'en starter bevidst **ikke** selv en write-aktiveret stack. Den eksisterende preflight skal først bevise den live konfiguration, før første marker vises.

Sæt token i miljøet eller indtast det skjult i wizard'en:

```powershell
$env:MODELRIG_TOKEN = "<paired-device-token>"
```

Stier kan gives via:

```powershell
$env:KALIV_DATA_DIR = "C:\...\data"
$env:KALIV_AGENT3_DB = "C:\...\kaliv-agent3.db"
$env:KALIV_AGENT3_APPROVAL_DB = "C:\...\kaliv-agent3-approvals.db"
$env:KALIV_AUDIT_DB = "C:\...\kaliv-audit.db"
$env:KALIV_TOOLS_DIR = "C:\...\tools"
```

Manglende stier bliver spurgt interaktivt og skal pege på regulære lokale filer.

## Hvert af de 20 runs

For hver ordinal viser wizard'en den eksakte marker og åbner de eksisterende developer-klienter.

Operatøren skal fysisk kontrollere:

- previewet indeholder præcis ét `note_append`-step;
- `args.text` er hele markeren uden ekstra tekst;
- append-only konsekvensen er synlig;
- previewet har ikke kørt tool'et;
- Android confirmation viser den samme marker, tool og revision;
- approval sker eksplicit på den parrede enhed;
- desktop viser `completed` og et synligt outcome.

Wizard'en kræver derefter præcis:

```text
PREVIEW 01 NOTE_APPEND MATCHER
APPROVAL 01 ENHED GODKENDT
OUTCOME 01 COMPLETED SYNLIG
```

Ordinalen ændres for hvert run. Et almindeligt `ja`, Enter eller næsten-match accepteres ikke.

Der gemmes tre screenshots pr. run under:

```text
validation/agent3-write-pilot-evidence/positive/
```

Det rå run-id gemmes kun i det eksisterende forensic manifest, fordi den senere collector skal slå det op i run-ledgeren. Den separate observationsjournal gemmer kun SHA-256 af run-id og marker.

## Resume

Efter Ctrl+C eller en fejl bevares:

- `validation/agent3-write-pilot-manifest.json`;
- `validation/agent3-write-pilot-preflight.json`;
- `validation/agent3-write-pilot-positive-observations.json`;
- allerede oprettede screenshots.

Resume tillades kun, når:

- pilot-id og exact candidate stadig matcher;
- preflight-rapporten fortsat er den oprindelige grønne rapport;
- observationsjournalens ordinals er præcis de samme som manifestets bundne ordinals;
- ingen fysisk case skal rekonstrueres bagefter.

Et delvist bundet manifest uden den oprindelige preflight eller observationsjournal fejler lukket.

## Output efter del 1

Når alle 20 runs er bundet, er **kun den positive del** færdig. T-022 er stadig ikke grøn.

Der mangler fortsat:

1. syv negative cases i den append-only recorder;
2. finalisering af den negative JSON;
3. den forensic collector mod notesfil, run/event-ledger, approval-use og ToolGate-audit;
4. gennemgang af den kandidatbundne slutrapport.

Wizard'en merger, pusher, tagger, releaser eller aktiverer aldrig produktion. Alle dens egne records har `production_activation=false`.
