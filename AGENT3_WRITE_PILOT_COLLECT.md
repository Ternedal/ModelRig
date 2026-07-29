# T-022 samlet write-pilot og forensic collect

**Status:** dormant fysisk operator til del 3 af T-022. Den er den praktiske top-level launcher for hele kampagnen: 20 positive `note_append`-runs, syv adversarial cases og den eksisterende read-only forensic collector.

## Start

Kør på Windows-riggen fra den eksakte collector-branch:

```text
START_AGENT3_WRITE_PILOT.cmd
```

Launcherens kandidat er fastlåst til:

```text
agent/t022-write-pilot-collector
```

Wizard'en skifter selv til branchen, fast-forward-puller den og kræver en ren working tree samt exact `origin/<branch>`-head. Positive og negative fysiske records skal derfor være skabt på samme endelige Git-SHA som collector-koden.

## Samlet rækkefølge

1. exact candidate kontrolleres på Windows-riggen;
2. en eksisterende rolling `agent3-write-pilot-latest.json` arkiveres, så en gammel grøn rapport ikke kan overleve en ny fejlet kampagne;
3. del 1 genoptages eller køres: 20 fysiske positive `note_append`-runs;
4. del 2 genoptages eller køres: syv hashkædede negative cases;
5. positive sidecar, manifest, preflight og alle 60 positive screenshots genvalideres;
6. negative sidecar, journal, response bodies og alle negative screenshots genvalideres;
7. den eksisterende forensic collector tager konsistente SQLite-snapshots;
8. `notes.md`, run/event-ledger, approval-use og ToolGate audit krydstjekkes;
9. en grøn eller rød rolling rapport skrives atomisk.

## Ingen ny write-mekanisme

Collector-operatoren:

- sender ingen preview-, start-, approve-, retry-, replan-, stop- eller cancel-request;
- implementerer ingen HTTP-write-transport;
- godkender ingen confirmation;
- ændrer ikke den eksisterende evidensdommer;
- genbruger de eksisterende fysiske operatorer og `collect_report(...)`;
- merger, pusher, tagger eller releaser ikke;
- aktiverer ikke produktion.

## Artifact-kontrol før forensic collect

Hvert artifact skal:

- være en regulær fil under den forventede `validation/agent3-write-pilot-evidence/...`-mappe;
- have en relativ sti uden `..`;
- ikke være eller gå gennem et symlink;
- have præcis den byte-count, sidecaren angiver;
- have præcis den SHA-256, sidecaren angiver.

Positive sidecar skal desuden bevise:

- præcis ordinals `1..20`;
- marker- og run-id-hash mod det bundne manifest;
- fysisk preview-, approval- og outcome-attestering;
- exact candidate og grøn GET-only preflight;
- Android- og Windows-device attribution;
- `production_activation=false`.

Negative sidecar skal desuden bevise:

- præcis de syv kontrakt-cases;
- samme pilot-id og exact candidate;
- journalens case-id-, marker-, status-, run-id- og response-hashes;
- korrekt før/efter note- og approval-use-count;
- præcis forventet status/delta for hver case;
- strict negative JSON og journalens final hash;
- `production_activation=false`.

## Forensic collector

Efter sidecar-kontrollen kaldes den eksisterende collector med:

```text
validation/agent3-write-pilot-manifest.json
validation/agent3-write-pilot-negative.json
validation/agent3-write-pilot-negative-journal.db
validation/agent3-rig-validation-latest.json
```

samt de live paths til:

- Agent 3 run-databasen;
- approval-use-databasen;
- ToolGate audit-databasen;
- `notes.md`.

Collector opretter transactionally consistent SQLite-snapshots, så WAL-state er med, og validerer blandt andet:

- præcis 20 completed positive runs;
- præcis ét lokalt `note_append`-step pr. positiv marker;
- fuld eventkæde i korrekt rækkefølge;
- én consumed approval og én executed ToolGate-audit pr. positiv marker;
- marker forekommer præcis én gang i `notes.md`;
- alle syv negative cases har de krævede statusser og ingen uønskede sideeffekter;
- candidate/version/code-fingerprint og rig-validation matcher;
- rapporten har `production_activation=false`.

## Output

Rolling rapport:

```text
validation/agent3-write-pilot-latest.json
```

Tidligere rolling rapporter arkiveres under:

```text
validation/archive/agent3-write-pilot-report-<timestamp>-<sha>/
```

En **grøn** rapport betyder kun, at den fysiske T-022-evidens og de lokale ledgers matcher collectorens kontrakt. Det er ikke en merge-, release- eller produktionsbeslutning.

En **rød** rapport gemmes også og viser de konkrete blockers. Hvis collector fejler før rapporten kan dannes, efterlades ingen gammel rolling grøn rapport.

## Stadig udestående efter del 3

Del 4 er en separat dormant CI/final-gate, som skal validere den færdige rapports schema, friskhed, exact-head-binding og ikke-aktivering uden at kunne fremstille fysisk evidens. Før den er leveret og den virkelige kampagne er kørt, er T-022 ikke afsluttet.
