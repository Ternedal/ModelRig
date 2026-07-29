# T-022 fysisk append-only write-pilot

**Status:** dormant operator-wizard. Den udfører ikke selv en godkendelse, kan ikke se UI’et og aktiverer ikke produktion.

## Start

På den eksakte Windows-rig-candidate:

```bat
START_AGENT3_WRITE_PILOT.cmd
```

Wizard’en kræver:

- en ren checkout af `agent/t022-write-pilot-one-click`;
- version `1.58.146` med konsistente versionstempler;
- en frisk kandidatbundet `validation/agent3-rig-validation-latest.json`, som er eligible til write-piloten;
- `MODELRIG_TOKEN` og `KALIV_AGENT3_APPROVAL_SECRET`, indtastet skjult og aldrig skrevet til state;
- præcis én Android-enhed via ADB;
- de faktiske paths til Agent 3-ledger, approval-use-database, ToolGate-audit og `notes.md`.

## Hvad wizard’en gør

1. Verificerer exact branch, Git-SHA, version, ren working tree og worker-code-fingerprint.
2. Starter kandidatens backend/worker med Agent 3, tools og backend-issued approval aktivt.
3. Bygger og installerer exact-head Android APK.
4. Opretter et frisk kandidatbundet manifest med 20 uforudsigelige append-markører.
5. Kører den eksisterende live T-022-preflight.
6. Guider gennem 20 positive `note_append`-runs.
7. Verificerer hvert positivt run direkte mod:
   - Agent 3 run/event-ledger;
   - approval-use-database;
   - ToolGate-audit;
   - præcis én forekomst i `notes.md`.
8. Binder først run-id’et til manifestet, når hele den forensiske kæde består.
9. Initialiserer først den negative hashkædede journal, når alle 20 run-id’er er bundet. Dermed bindes journalen til det endelige manifest — ikke et halvfærdigt manifest.
10. Guider gennem syv negative cases:
    - `deny`;
    - `timeout`;
    - `changed_args`;
    - `stale_revision`;
    - `replay`;
    - `concurrent_approval`;
    - `stop_retry_replan`.
11. Hashbinder exact HTTP-status, response body og run-id i den append-only SQLite-journal.
12. Kører den eksisterende forensic collector og skriver den endelige rapport.

## Menneskelig attestering

Wizard’en kan ikke observere skærmen eller trykke Godkend. Derfor accepterer den ikke et almindeligt `ja` eller Enter som bevis.

Hvert positivt run kræver to præcise fraser:

```text
PREVIEW GODKENDT NN
APPEND BEKRÆFTET NN
```

Efter et afbrudt bind-step, hvor markøren allerede findes præcis én gang, kræves:

```text
GENOPTAG POSITIV NN
```

Hver negativ case kræver:

```text
NEGATIV CASE OBSERVERET <case-navn>
```

De præcise response bodies skal gemmes eller indsættes. Run-id’er indtastes skjult; positive run-id’er gemmes kun i det allerede definerede kandidatmanifest, og negative run-id’er bindes i den eksisterende evidence-journal.

## Sikker genoptagelse

State gemmes i:

```text
validation/agent3-write-pilot-operator-state.json
```

Ved afbrydelse:

- allerede bundne positive runs springes over;
- en positiv markør, som findes præcis én gang men endnu ikke er bundet, kræver recovery-attestering og fuld forensic genkontrol;
- en åben negativ case genoptages fra journalens eksisterende observationer;
- mere end én åben negativ case fejler lukket;
- candidate-SHA må ikke have ændret sig.

Tidligere evidens arkiveres under:

```text
validation/archive/t022-write-pilot-YYYYMMDD-HHMMSS/
```

## Output

- `validation/agent3-write-pilot-manifest.json`
- `validation/agent3-write-pilot-preflight.json`
- `validation/agent3-write-pilot-negative-journal.db`
- `validation/agent3-write-pilot-negative.json`
- `validation/agent3-write-pilot-latest.json`
- `validation/agent3-write-pilot-operator-state.json`
- exact response bodies under `validation/agent3-write-pilot-responses/`

En grøn rapport kræver fortsat den eksisterende strenge collector:

- 20/20 positive runs;
- præcis én append per positiv markør;
- 20 unikke single-use approvals fra én device-id;
- 7/7 negative cases;
- ingen ekstra eller fiktive run-id’er;
- frisk evidens inden for det tilladte tidsvindue;
- `production_activation=false`.

## Hårde grænser

Wizard’en:

- merger eller pusher ikke;
- opretter ikke tags eller releases;
- ændrer ikke normal chat-routing;
- kan ikke generere en approval-token;
- kan ikke trykke Godkend på Android;
- kan ikke opfinde response bodies, statuskoder eller run-id’er;
- kan ikke gøre en rød forensic rapport grøn;
- sætter aldrig `production_activation=true`.
