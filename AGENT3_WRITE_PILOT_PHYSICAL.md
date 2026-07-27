# T-022 fysisk append-only write-pilot

**Status:** dormant operator-flow. Det gør den fysiske T-022-ceremoni reproducerbar, men det kan ikke selv godkende en write, observere en UI eller gøre en rapport grøn.

Start på Windows-riggen fra den eksakte kandidat:

```text
START_AGENT3_WRITE_PILOT_PHYSICAL.cmd
```

## Hvad wizard'en automatiserer

- fast-forward-only checkout af sin eksakte versionsbundne branch;
- ren candidate identity og konsistente version stamps;
- skjult `MODELRIG_TOKEN` og skjult fælles approval-secret;
- `KALIV_AGENT3_APPROVAL_REQUIRED=1` i både backend/worker-processerne;
- `KALIV_AGENT3_ENABLED=1`, tool-host aktiv og normal task-routing fortsat slået fra;
- frisk candidate-bound rig-validation med `eligible_for_write_pilot=true`;
- forberedelse af 20 uforudsigelige markers;
- read-only preflight før første preview;
- exact-head Android-build og `adb install -r`;
- åbning af desktop/Android Agent 3 developer-surfaces;
- enkeltvis binding af de 20 faktiske run-id'er;
- umiddelbar krydskontrol af hvert positivt run mod:
  - `notes.md`;
  - Agent 3 run/event ledger;
  - approval-use databasen;
  - ToolGate audit-databasen;
- append-only registrering af de syv negative cases;
- automatisk før/efter-tælling af note og approval-use;
- SHA-256 af de eksakte HTTP-response bodies;
- endelig forensic collector og kandidatbundet JSON-rapport.

## Hvad wizard'en **ikke** kan gøre

- den kan ikke trykke Approve eller Deny;
- den kan ikke se, hvad Android- eller desktop-UI'en viser;
- den kan ikke opfinde en HTTP-response, statuskode eller run-id;
- den kan ikke ændre en allerede registreret negativ observation;
- den kan ikke merge, pushe, tagge, release eller aktivere produktion;
- den kan ikke gøre normal Agent 3-routing til standard.

## Session og resume

En session gemmer kun ikke-hemmelig operator-state i:

```text
validation\agent3-write-pilot-operator-state.json
```

Manifest, preflight, negativ journal og slutrapport er kandidatbundne. Ved resume skal operatøren skrive den præcise phrase:

```text
FORTSÆT T-022 <pilot-id>
```

En ny kampagne kræver den præcise phrase:

```text
NY T-022 KAMPAGNE
```

Tidligere filer flyttes da til en tidsstemplet mappe under `validation\archive`; de slettes ikke.

Preflight må kun køre, mens alle 20 manifest-runs er ubundne og den negative journal endnu ikke findes. Efter første append genbruges den oprindelige immutable preflight, hvis dens SHA-256 og oprindelige manifest-digest matcher operator-state.

## 20 positive runs

For hvert ordinal viser wizard'en den komplette marker. Brug desktopens Agent 3 developer-surface til en server-authoritativ preview med præcis ét `note_append`-step og marker-strengen som hele `text`-argumentet.

Før godkendelse kræves:

```text
PREVIEWET T-022 01
```

Efter fysisk approval fra den parrede Android-enhed og synlig `completed` kræves:

```text
GODKENDT T-022 01
```

Run-id indtastes skjult og bindes til det rigtige ordinal. Wizard'en fortsætter først, når den kan bevise:

- run-state `completed`;
- præcis én `approval_consumed` med korrekt device/revision/action-binding;
- præcis én udført ToolGate-audit for markeren;
- præcis én markerlinje i `notes.md`;
- den fulde confirmation/approval/execution-eventkæde.

Et delvist eller inkonsistent run stopper sessionen sikkert. Det allerede bundne manifest bevares til undersøgelse; wizard'en omskriver ikke evidensen.

## Syv negative cases

Efter 20/20 positive runs initialiseres den hashkædede SQLite-journal. Cases køres i denne rækkefølge:

1. `deny`
2. `timeout`
3. `changed_args`
4. `stale_revision`
5. `replay`
6. `concurrent_approval`
7. `stop_retry_replan`

Hver case kræver begge præcise phrases:

```text
OBSERVERET T-022 <case>
KVITTERING T-022 <case>
```

Wizard'en åbner en separat response-fil i Notepad for hver HTTP-observation. Indsæt den **eksakte** response body, gem og luk. Statuskode og run-id registreres sammen med response-hash og før/efter-tællinger.

Forventet kontrakt:

| Case | HTTP-observationer | Note-delta | Approval-delta |
|---|---|---:|---:|
| `deny` | `200` | 0 | 0 |
| `timeout` | `409` | 0 | 0 |
| `changed_args` | `409` | 0 | 0 |
| `stale_revision` | `409` | 0 | 0 |
| `replay` | `409` | 0 | 0 |
| `concurrent_approval` | én `200`, én `409` | +1 | +1 |
| `stop_retry_replan` | mindst tre af `200/202/409` | 0 | 0 |

`replay` bruger positiv marker 1; `stop_retry_replan` bruger positiv marker 2. Det gør de eksisterende note-counts målbare og forhindrer en skjult ekstra append.

Hvis en faktisk response ikke matcher kontrakten, bliver den stadig sandfærdigt skrevet til journalen, og sessionen stopper rød. Den må ikke håndredigeres til den forventede værdi.

## Slutrapport

Når alle cases er færdige, kompileres journalen til:

```text
validation\agent3-write-pilot-negative.json
```

Derefter krydstjekker collectoren manifest, note, run-ledger, approval-use, audit og journal og skriver:

```text
validation\agent3-write-pilot-latest.json
```

Kun collectorens `success=true` og exitkode 0 er en grøn T-022-rapport. Rapporten indeholder altid:

```json
"production_activation": false
```

En grøn rapport beviser den eksakte fysiske session. Den merger eller promoverer stadig ikke kandidaten automatisk.
