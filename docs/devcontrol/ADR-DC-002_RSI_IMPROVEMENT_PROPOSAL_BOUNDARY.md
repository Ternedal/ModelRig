# ADR-DC-002 — RSI-forbedringsforslag som ikke-autoriserende lag

**Dato: 12/09-2026. Status: foreslået til beslutning.**

## Kontekst

ModelRig har allerede målelige eval-flader og en isoleret DevControl-kæde, men mangler et eksplicit led mellem et observeret kvalitetsgab og en udviklingsopgave. Uden et sådant led er rekursiv selvforbedring enten manuel eller risikerer at springe direkte fra modeloutput til `DevelopmentTask`, som allerede er en autoritetsbærende kontrakt.

Dette ADR-udkast afgrænser kun RSI-leddet **evidens → forbedringsforslag**. Det giver ingen ny eksekverings-, Git-, GitHub-, merge-, release-, deploy- eller aktiveringsautoritet og ændrer ikke ADR-DC-001.

## Beslutning 1 — ImprovementProposal er ikke autoritet

Et modelgenereret forbedringsforslag repræsenteres i en separat, streng kontrakt: `kaliv-rsi-improvement-proposal/v1`.

Kontrakten må beskrive problem, hypotese, forventet gevinst, foreslået scope og hvilke evals der skal bevise forbedringen, men den må **ikke** indeholde DevControl-felter som `allowed_paths`, `allowed_command_ids`, publisher-intent eller anden eksekveringsautoritet.

Der findes ingen automatisk konvertering fra `ImprovementProposal` til `DevelopmentTask`.

## Beslutning 2 — Evidens skal være SHA- og digest-bundet

Et forslag skal pege på et konkret eval-artifact med:

- kendt schema;
- repository;
- exact 40-hex base SHA;
- SHA-256 af den kanoniske eval-payload;
- mindst ét observeret, reproducerbart fund.

Et forslag uden verificerbar evidens er ugyldigt.

## Beslutning 3 — Hypotesen skal være falsificerbar

Hvert forslag skal formulere:

- det observerede problem;
- en konkret årsagshypotese;
- den forventede målbare forbedring;
- acceptance criteria;
- de evals, der skal genkøres mod samme type baseline.

"Gør modellen bedre" er ikke et gyldigt forslag.

## Beslutning 4 — Modellen må foreslå scope, aldrig tildele scope

Modellen må returnere `suggested_paths`, `suggested_tests` og en kort implementeringsstrategi. De felter er rådgivende data og kan ikke bruges direkte som DevControl-authority.

Promotion til en rigtig `DevelopmentTask` er et separat trin, hvor scope, command IDs, budget, protected paths og merge-authority fastlægges af den eksisterende authority-kæde.

## Beslutning 5 — Ranking må ikke baseres på modelens selvtillid alene

Prioritering skal være afledt af observeret eval-gap og reproducerbar evidens. Et valgfrit model-estimat må vises, men må ikke alene afgøre rækkefølge eller autorisation.

Første slice implementerer derfor kun normalisering og forslagets kontrakt; automatisk ranking kommer først, når målegrundlaget er eksplicit defineret.

## Beslutning 6 — Ingen unattended rekursion i dette slice

Dette slice må ikke:

- starte en udviklingskampagne;
- skrive patches;
- materialisere kandidater;
- aktivere en baggrundsagent eller cadence;
- kalde et remote Git/GitHub write-endpoint;
- merge, release eller deploye.

Det eneste tilladte output er et valideret forslag/brief, som et senere authority-step kan vælge at omsætte til en opgave.

## Beslutning 7 — Første kilde er Agent 3 model-eval

Første adapter må læse `kaliv-agent3-model-eval/v1` og udtrække fejlede exact-match cases, discipline-fejl, argument-/risk-/tool-score og request-fejl til et kanonisk RSI-brief.

Andre eval-kilder (workflow completion, RAG, voice, latency m.fl.) tilføjes senere gennem separate adapters til samme proposal-kontrakt.

## Beslutning 8 — Ingen proposal ved ren evidens

Hvis eval-artifactet er gyldigt, SHA-bundet og ikke indeholder et observeret kvalitetsgab, skal planner-laget returnere "ingen forslag nødvendigt" frem for at opfinde forbedringsarbejde.

## Obligatoriske kontrakttests

1. Ukendte proposal-felter afvises fail-closed.
2. Base SHA skal være exact lowercase 40-hex.
3. Eval-digest skal være exact lowercase SHA-256.
4. Proposal må ikke indeholde authority-felter som `allowed_paths` eller `allowed_command_ids`.
5. Agent 3 eval-adapteren udtrækker kun observerede failures og bevarer task/repetition/findings.
6. Ren 100 % exact-match evidens producerer et tomt improvement brief.
7. Samme input producerer byte-identisk kanonisk brief/proposal JSON.
8. Ingen modulimport starter tråde, netværk, subprocesser eller filskrivning.

## Konsekvenser

**Positivt:** ModelRig får det manglende RSI-led mellem måling og udvikling uden at gøre modeloutput til autoritet. Forslag bliver eval-bundne, reproducerbare og testbare, og senere modeller kan konkurrere om at formulere bedre hypoteser uden at få ekstra rettigheder.

**Begrænsning:** Et menneske/authority-step er fortsat nødvendigt, før et forslag bliver til en faktisk udviklingsopgave. Det er tilsigtet og i tråd med ADR-DC-001.
