# RSI improvement proposal — eval → modelhypotese uden authority

Denne slice lukker det første manglende RSI-led i ModelRig:

```text
Agent 3 eval
    ↓
SHA/digest-bundet improvement brief
    ↓
modelprompt
    ↓
kaliv-rsi-improvement-proposal/v1
    ↓
strict evidence binding
    ↓
SEPARAT authority-step → DevelopmentTask (ikke implementeret her)
```

## Hvad den kan

`devcontrol/src/kaliv_dev_control/improvement_proposal.py` normaliserer observerede fejl fra `kaliv-agent3-model-eval/v1`. Kun cases med request-fejl, manglende exact-match eller manglende discipline-pass bliver findings. En ren eval producerer et tomt brief og må ikke udløse opdigtet forbedringsarbejde.

Et modeloutput valideres som `ImprovementProposal`. Kontrakten kræver en falsificerbar hypotese, forventet målbar gevinst, acceptance criteria og required evals. `suggested_paths` og `suggested_tests` er rådgivende og bærer ingen authority.

`improvement_binding.py` binder derefter proposal tilbage til præcis samme repository, base SHA, eval schema, evidence SHA-256 og finding IDs som modellen fik vist. Modellen kan derfor ikke skifte evidens undervejs.

## Hvad den bevidst ikke kan

Denne slice kan ikke:

- oprette eller starte en `DevelopmentTask`;
- tildele `allowed_paths`, `allowed_command_ids`, budget eller protected paths;
- skrive patches eller commits;
- pushe en branch eller oprette/merge en PR;
- release/deploye/aktivere noget;
- køre som baggrundsagent eller unattended RSI-loop.

Det er proposal-laget, ikke execution-laget.

## Offline flow

Fra repo-roden, efter en rigtig Agent 3 model-eval:

```powershell
python scripts/rsi_improvement_planner.py `
  --eval-report validation/agent3-model-eval-latest.json `
  --base-sha <EXACT_40_HEX_SHA> `
  --brief-out validation/rsi-improvement-brief.json `
  --prompt-out validation/rsi-improvement-prompt.txt
```

`rsi-improvement-prompt.txt` kan gives til den model, der skal formulere forbedringshypotesen. Modeloutput gemmes som JSON og bindes derefter tilbage til evidensen:

```powershell
python scripts/rsi_improvement_planner.py `
  --eval-report validation/agent3-model-eval-latest.json `
  --base-sha <SAMME_EXACT_40_HEX_SHA> `
  --brief-out validation/rsi-improvement-brief.json `
  --proposal validation/rsi-improvement-proposal.raw.json `
  --canonical-proposal-out validation/rsi-improvement-proposal.json
```

Kun det kanoniske output efter binding er et gyldigt forslag. Det er stadig **ikke** en udviklingsopgave.

## Næste RSI-slices

Efter denne proposal-boundary er de naturlige næste led:

1. deterministisk gap/prioritets-score fra målbar eval-evidens;
2. separat promotion-gate fra proposal til menneskeligt reviewet `DevelopmentTask`;
3. kandidat-udvikling gennem eksisterende DevControl;
4. candidate-vs-incumbent regression proof;
5. iterativ proposal-revision, hvis kandidaten ikke slår baseline;
6. først langt senere en eventuel cadence/controller — stadig uden at ændre ADR-DC-001's terminale menneskelige autoritet uden en ny beslutning.

Arkitekturgrænsen er beskrevet i `docs/devcontrol/ADR-DC-002_RSI_IMPROVEMENT_PROPOSAL_BOUNDARY.md`.
