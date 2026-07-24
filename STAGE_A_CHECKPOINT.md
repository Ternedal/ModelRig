# Stage A checkpoint — gem resultater uden at fortsætte den manuelle test

`SAVE_STAGE_A_RESULTS.cmd` er den sikre afslutning, når en fysisk Stage A-kørsel
skal stoppes, men de allerede indsamlede resultater skal bevares og opsummeres.

Launcheren:

- starter ikke backend, worker, Pixel-test eller scheduler;
- opretter ikke tokens og ændrer ikke firewall eller netværksbinding;
- genberegner den autoritative kandidatkampagne i `prepare`-mode;
- skelner mellem `passed`, `failed` og `pending`;
- gemmer `validation/stage-a-checkpoint-latest.json`;
- holder altid `promotion_ready=false`, `release_complete=false` og
  `production_activation=false`.

## Brug

Dobbeltklik:

```text
SAVE_STAGE_A_RESULTS.cmd
```

Et checkpoint er gyldigt, når kandidat-checkoutet og de eksisterende rapporter er
konsistente og ingen proof har status `fail`. Manglende manuelle proofs er tilladt
i checkpointet og vises som `pending`; de tæller aldrig som bestået.

## Rapporten

Kontrollér især:

```text
schema = kaliv-stage-a-checkpoint/v1
checkpoint.valid = true
checkpoint.automatic_evidence_complete = true|false
checkpoint.manual_evidence_pending = [...]
checkpoint.ready_for_stage_a_verify = true|false
gate.promotion_ready = false
gate.production_activation = false
```

Hvis den lokale 20-filers voice-formatkontrol findes og matcher samme kandidat,
bindes dens hash og status ind som supplerende evidens. Det gør ikke selve voice-
proofet grønt; Pixel stop/barge-in og den komplette voice-baseline mangler stadig,
indtil de er gennemført korrekt.

## Hvad checkpointet ikke gør

Checkpointet kan ikke:

- merge eller pushe;
- tagge eller udgive en release;
- aktivere produktion;
- godkende scheduler-planer;
- opfinde Pixel-, voice- eller scheduler-evidens;
- erstatte den senere Stage A `verify`/`complete`-gate.
