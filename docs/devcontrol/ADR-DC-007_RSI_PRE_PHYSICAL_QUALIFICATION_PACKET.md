# ADR-DC-007 — RSI pre-physical qualification packet før DC-L15/DC-L16

**Dato: 12/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-002 til ADR-DC-006 etablerer en bounded RSI-kæde fra observeret eval-gap til et ikke-autoriserende forslag, menneskeligt signeret promotion, candidate-vs-incumbent regression proof, runtime provenance og read-only collection af det materialiserede Git-tree.

Det er stadig ikke det samme som, at ModelRig må starte eller aktivere KalivDev-piloten. Den eksisterende DC-L15-kontrakt kræver en fresh physical I0b campaign på exact frozen `main` head, uafhængig collector/approver og et efterfølgende menneskeligt pilotvalg. DC-L16 er den senere kontrollerede produktpilot.

Der mangler derfor et eksplicit artifact, som kan sige: **software-evidenskæden er komplet**, uden samtidig at sige: **GO er givet**.

## Beslutning 1 — Qualification packet er evidence-only

Artifactet bruger schema `kaliv-rsi-qualification-packet/v1` og har altid:

- `authority = evidence-only`;
- `merge_authority = human`;
- `software_chain_complete = true`;
- `ready_for_human_go = false`;
- `activation_authorized = false`;
- `automatic_activation = false`;
- `remote_publication_authorized = false`.

Et gyldigt packet kan derfor dokumentere, at softwarekæden hænger sammen, men kan ikke starte campaign, pilot, merge, release, deploy eller activation.

## Beslutning 2 — Packet binder hele RSI chain-of-custody

Packetet skal kryptografisk binde samme:

- `ImprovementProposal` og proposal SHA-256;
- human-signed `PromotionReceipt`;
- `DevelopmentTask` identity;
- DC-L13 materialization receipt identity;
- read-only candidate snapshot receipt;
- candidate commit og root tree;
- målt worker `code_sha256`;
- incumbent- og candidate-eval digests;
- accepted `CandidateRegressionProof`;
- `CandidateRuntimeProvenance`;
- proposalets `required_evals`.

Et mismatch i proposal, promotion, task, snapshot, candidate tree, eval, regression proof eller runtime provenance skal fejle lukket.

## Beslutning 3 — Fem eksterne gates må ikke kunne tilfredsstilles af software-pakken

Et v1-packet skal altid bevare disse fem manglende gates i præcis denne orden:

1. `dc_l14_independent_human_verdict`;
2. `exact_frozen_main_head_confirmation`;
3. `fresh_physical_i0b_campaign`;
4. `independent_physical_collector_approver`;
5. `human_pilot_go_decision`.

`fresh_physical_evidence_required` og `independent_collector_approver_required` er altid `true`.

Forsøg på at fjerne en gate, sætte `ready_for_human_go=true`, sætte activation/publication authority eller ændre authority til andet end evidence-only skal afvises ved parsing/konstruktion.

## Beslutning 4 — DC-L15 forbliver fysisk og fresh

Qualification packet må ikke erstatte eller genbruge pre-freeze fysisk evidens. Det må heller ikke attestere, at stackens aktuelle feature-branch er den exact frozen `main` head.

Når/ hvis DC-L15 køres, skal dens eksisterende kontrakt fortsat gælde: fresh native probes på exact frozen head, uafhængig collection/approval og et grønt packet som evidens til en senere menneskelig beslutning — aldrig automatisk activation.

## Beslutning 5 — DC-L14 human verdict må ikke syntetiseres

Merge-status, grøn CI, exact-head qualification eller en modelvurdering er ikke et independent human verdict.

Qualification packet skal derfor fortsat markere `dc_l14_independent_human_verdict` som manglende, indtil den særskilte menneskelige review-kontrakt faktisk er opfyldt.

## Beslutning 6 — Ingen unattended recursion i dette slice

Denne slice må ikke:

- starte DC-L15 eller DC-L16;
- starte en candidate runtime;
- køre evals automatisk;
- oprette recurring/background cadence;
- foretage remote Git/GitHub write;
- merge, release, deploye eller aktivere;
- omsætte packet-status til automatisk GO.

Næste fysiske skridt er en separat, menneske-initieret qualification/physical execution boundary under de eksisterende DC-L15/DC-L16-regler.

## Konsekvens

RSI-kæden får et tydeligt stop mellem **bevist softwareforbedring** og **fysisk/pilotmæssig authority**. Det gør det muligt at automatisere og efterprøve chain-of-custody uden at snige unattended activation ind gennem et evidensartifact.

## Forhold til tidligere ADR'er

- ADR-DC-001 er fortsat terminal authority-boundary.
- ADR-DC-002 definerer proposal-only laget.
- ADR-DC-003 definerer human-signed promotion.
- ADR-DC-004 definerer candidate-vs-incumbent regression proof.
- ADR-DC-005 binder materialized Git tree til målt runtime-kode.
- ADR-DC-006 indsamler candidate-treeet read-only gennem trusted local Git.

Dette ADR-udkast ændrer ingen af deres authority-grænser.
