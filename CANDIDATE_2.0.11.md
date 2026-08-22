# Candidate 2.0.11 — physical proof authority

Denne fil beskriver **authority-modellen** for den aktive 2.0.11-kandidat. Den
pinner med vilje ikke et bestemt commit-SHA i dokumenttekst: den eksakte SHA
skal altid læses fra den fetch'ede remote candidate-branch og derefter bevises
maskinelt.

## Aktiv authority

- version: `2.0.11`;
- candidate branch: `physical-proof/2.0.11`;
- exact SHA: `origin/physical-proof/2.0.11` efter `git fetch origin`;
- freeze gate: `scripts/candidate_freeze_check.py --expected-sha <exact-sha>`;
- production activation: `false`.

Historiske freeze-PR'er, gamle candidate-branches og tidligere 2.0.11-heads er
**ikke** SHA-authority. Især PR #412, `agent/unified-candidate-2.0.11-r2` og det
gamle `218019fd...` main-anchor tilhører en tidligere promotion-model og må ikke
bruges til en ny fysisk receipt.

## Før fysisk evidens — moving anchor

Indtil den første authority-bearing fysiske observation er taget, følger
`physical-proof/2.0.11` den godkendte current `main`. Efter en software-landing
skal ankeret derfor flyttes til den nye main og re-kvalificeres; en tidligere
freeze-receipt er ikke genbrugelig efter main-drift.

Den autoritative helper er:

```text
GITHUB_TOKEN=... python3 scripts/anchor_and_freeze.py --branch physical-proof/2.0.11
```

Den må kun erklære kandidaten frozen, når:

1. candidate-branch og exact HEAD er den tilsigtede 2.0.11-SHA;
2. working tree og versionssites er rene/konsistente;
3. current `origin/main` kan fetches og er indeholdt i kandidaten;
4. **alle fire** software-gates er `completed/success` på præcis SHA'en:
   - `ci`;
   - `codeql`;
   - `agent3-diagnostics`;
   - `agent3-full-diagnostics`;
5. `candidate_freeze_check.py` skriver en grøn, exact-SHA-bundet receipt.

CI, CodeQL og begge Agent 3-gates kører automatisk på push til `main`.
`workflow_dispatch` for Agent 3 er kun en recovery-vej, hvis en exact-main-run
mod forventning slet ikke findes. En eksisterende failed eller in-progress run
må ikke skjules af en automatisk rerun.

## Efter første fysiske bevis — immutable freeze

Fra første authority-bearing fysiske bevis til promotion eller explicit
abandonment må candidate-branchen ikke flyttes:

- ingen push/rebase/force-push/merge/amend;
- ingen dokument- eller bookkeeping-commit på kandidaten;
- ingen genbrug af receipts fra en anden SHA;
- enhver bevægelse af `origin/main` invaliderer den eksisterende freeze-receipt
  og kræver en ny kandidat/freeze før mere evidens kan accepteres.

Det er bevidst strengere end almindelig CI: fysisk evidens er evidens om én
konkret kodeidentitet, ikke om en versionstekst eller en lignende branch.

## Operatorindgange

Den korte manuelle authority er `RIGDAG_SIMPEL.md`; den fulde promotionorden er
`STAGED_PHYSICAL_PROMOTION.md`.

Den samlede source-bound proof-kampagne kan startes med:

```text
START_PROOF_CAMPAIGN.cmd
```

Den må automatisere softwareklargøring, isoleret pairing og maskinbeviser, men
må aldrig auto-attestere fysiske observationer eller menneskelige approvals.
Skip/reuse forbliver fail-closed. Kampagnen merger, tagger, releaser og
produktionsaktiverer intet.

## Stage A — upubliceret kandidat

Stage A samler de candidate-bound beviser, herunder rig preflight, Agent 3,
model-eval, voice/Pixel, RAG, scheduler og browser/peer-bevis. Den endelige
Stage A-gate skal fortsat vise blandt andet:

```text
candidate_ready_for_fast_forward=true
release_validation_pending=true
release_complete=false
all_physical_evidence_complete=false
production_activation=false
```

Kun efter separat menneskelig beslutning må den **samme eksakte Stage A-SHA**
fast-forwardes til `main`, tagges `v2.0.11` og publiceres som komplet signeret
release-set. En SHA-ændring gør Stage A-evidensen ugyldig.

## Stage B — publiceret 2.0.11

Stage B følger `STAGE_B_UPDATER_EVIDENCE.md` og beviser den installerede
appliance/reboot/supervisor/update/rollback-kæde mod den publicerede signerede
release. `VERIFY_STAGE_B_EVIDENCE.cmd` er den fail-closed slutindgang.

Et grønt Stage A- eller Stage B-resultat aktiverer stadig ikke Agent 3,
DevControl eller andre dormante capabilities. `production_activation=false`
forbliver strukturel gennem hele promotionen.

## Automatic updater self-update er fortsat separat

2.0.11 er den første release i denne kæde med self-update-support. Det ægte
automatiske signed-release-to-signed-release bevis kræver 2.0.11 (eller senere)
som source og en **nyere** signeret target-release. Det spores fortsat i #401
og må ikke erstattes af 2.0.10 → 2.0.11 bootstrap-beviset.
