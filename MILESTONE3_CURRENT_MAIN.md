# Kaliv Milestone 3 — current-main fysisk kandidat

Denne kandidat samler de tre resterende fysiske Agent 3-domæner på én ren Git-head:

1. T-020 read-only developer-pilot.
2. T-022 append-only write-pilot gennem den sanitiserede final-gate.
3. T-023 termination UI-pilot på Android og Windows desktop.

## Autoritativ launcher

Kør fra repository-roden på Windows-riggen:

```text
START_MILESTONE3_CURRENT_MAIN.cmd
```

Launcheren bruger `scripts/milestone3_current_main.py` og er bundet til:

- branch `agent/milestone3-current-main-v2`;
- version `1.58.147`.

Alle child-operatorer får samme branch/version før deres `main()` kaldes. Stage A-gaten køres først. Efter hvert domæne genåbner koordinatoren den kanoniske rapport og kræver:

- `success=true`;
- det forventede schema;
- samme exact candidate Git SHA;
- `production_activation=false`.

## Menneskelig grænse

Software kan ikke fremstille den nødvendige evidens. Kampagnen kræver den rigtige Windows-rig og præcis én parret Android-enhed. T-022 kræver 20 reelle, enhedsbaserede approvals og syv adversarial cases. T-023 kræver de eksplicitte Android- og desktopobservationer.

Koordinatoren udfører ingen merge, push, tag, release eller produktionsaktivering og automatiserer ingen approval eller UI-observation. En grøn hosted CI-run beviser kun den dormante kontrakt — ikke den fysiske kampagne.
