# T-022 negativ write-pilot operator

**Status:** dormant fysisk operator til del 2 af T-022. Den styrer og registrerer de syv adversarial cases gennem den eksisterende hashkædede recorder. Den sender ikke selv et adversarial request, godkender ikke en confirmation og aktiverer ikke produktion.

## Start

Kør på Windows-riggen fra den eksakte branch:

```text
START_AGENT3_WRITE_PILOT_NEGATIVE.cmd
```

Dette er den praktiske samlede launcher for del 1 og del 2:

- mangler eller er den positive 20-run-ceremoni ufuldstændig, genoptages den eksisterende positive wizard først;
- branch-override sikrer, at positive og negative runs bindes til samme Git-SHA;
- når alle 20 positive runs er fysisk attesteret og bundet, fortsætter den negative recorder.

## Sikkerhedsgrænse

Wizard'en udfører **ikke** de syv requests. Operatøren udfører hver case gennem de eksisterende Agent 3-klienter og kopierer den eksakte response body til Windows-clipboard. Wizard'en:

1. tager note- og approval-use-count før casen;
2. opretter casen i den eksisterende append-only SQLite-journal;
3. kopierer den præcise marker til clipboard;
4. åbner eksisterende Android- og desktop-developer-surfaces;
5. beder operatøren gennemføre casen;
6. læser den eksakte response body fra clipboard;
7. registrerer HTTP-status og det involverede run-id;
8. tager Android- og Windows-screenshot;
9. kræver en præcis case-specifik attestering;
10. tager note- og approval-use-count efter casen;
11. afviser forkerte statusser eller deltas før casen kan markeres færdig.

Response bodies gemmes bytepræcist under:

```text
validation/agent3-write-pilot-evidence/negative/
```

Den autoritative recorder gemmer response-hash, status og rå run-id, fordi den senere forensic collector skal slå runnet op. Den separate fysiske observationsjournal gemmer kun SHA-256 af run-id og marker samt artifact-hashes.

## Cases og forventninger

| Case | Requests | Status | Note-delta | Approval-use-delta |
|---|---:|---|---:|---:|
| `deny` | 1 | `200` | 0 | 0 |
| `timeout` | 1 | `409` | 0 | 0 |
| `changed_args` | 1 | `409` | 0 | 0 |
| `stale_revision` | 1 | `409` | 0 | 0 |
| `replay` | 1 | `409` | 0 | 0 |
| `concurrent_approval` | 2 | én `200`, én `409` | +1 | +1 |
| `stop_retry_replan` | 3 | hver `200`, `202` eller `409` | 0 | 0 |

`replay` og `stop_retry_replan` genbruger hver sin allerede udførte positive marker. Sikkerheds-entrypointet måler derfor den faktiske eksisterende note-count før casen; det antager ikke nul.

## Fysisk attestering

Efter hvert request kræves eksempelvis:

```text
NEGATIVE REPLAY OBS 1 REGISTRERET
```

Et almindeligt `ja`, Enter eller næsten-match accepteres ikke. Screenshot og response body skal være oprettet, før observationen kan attesteres.

## Resume

Journalen er append-only og SHA-256-hashkædet. Ved Ctrl+C eller fejl bevares:

- `validation/agent3-write-pilot-negative-journal.db`;
- `validation/agent3-write-pilot-negative-observations.json`;
- response bodies og screenshots.

Resume kræver præcis paritet mellem journalens request-observationer og den fysiske observationsjournal. En journalobservation uden tilhørende fysisk artifact kan ikke rekonstrueres bagefter og fejler lukket.

## Output efter del 2

Efter alle syv cases produceres:

```text
validation/agent3-write-pilot-negative.json
```

Det er den strikte negative JSON, som den eksisterende forensic collector forventer. T-022 er stadig ikke grøn, før del 3 har krydstjekket:

- alle 20 positive runs;
- notes.md;
- Agent 3 run/event-ledger;
- approval-use-databasen;
- ToolGate audit;
- den hashkædede negative journal og dens syv cases.

Wizard'en merger, pusher, tagger, releaser eller aktiverer aldrig produktion. Alle operator-ejede records har `production_activation=false`.
