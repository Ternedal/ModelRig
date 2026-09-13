# ADR-DC-016 — Single-trial scope projection without DC-L16 start authority

**Dato 13/09-2026. Status: foreslået til beslutning.**

## Beslutning

Et verificeret positivt ADR-DC-015 human pilot decision proof må indsnævres
deterministisk til **én** konkret DC-L16 trial-scope, men projektionen må ikke
starte piloten eller påstå, at produkt-runtime, feature-flag eller operatorflade
faktisk er klar.

Slicen indfører derfor `PilotTrialScopeProof`, som kun kan produceres fra et
exact `HumanPilotDecisionProof` med `GO` eller `GO WITH CONDITIONS` og
`pilot_go_authorized=true`.

`NO-GO` kan aldrig projiceres til en trial-scope.

## Hvorfor

Issue #423 kræver én eksplicit, allowlisted lokal pilotopgave efter en separat
human GO. ADR-DC-015 binder det menneskelige beslutningsrum, men en positiv
beslutning kan stadig omfatte flere tilladte task IDs. Før en senere
produkt-/runtime-boundary må der derfor findes et mekanisk, reviewbart led, som
kun **indsnævrer** den signerede authority.

Repositoryets normale ModelRig command catalog forbliver tomt. Denne ADR
registrerer ingen kommandoer og gør ingen product entrypoint levende.

## Exact narrowing

En scope-projektion binder:

- exact ADR-DC-015 decision-proof SHA-256;
- decision- og signature-digest;
- campaign/task/repository/base/requested-main fra human proofet;
- human decision ID og decision maker;
- exact operator surface;
- præcis ét `selected_pilot_task_id`, som allerede skal være i den signerede
  allowlist;
- exact workspace-root path digest;
- om denne ene trial anmoder om lokale commits.

Projektionen må kun indsnævre `local_commits_allowed`:

- human `false` → trial skal være `false`;
- human `true` → trial må vælge `false` eller `true`.

Operator surface og workspace digest skal matche human proofet byte-for-byte.

## Conditional GO

`GO WITH CONDITIONS` må projiceres, men conditions/notes kopieres ind i proofet
og `conditional_go=true`. Projektionen erklærer **ikke**, at betingelserne er
opfyldt. Det er en senere runtime/start-gates ansvar.

## Explicit non-authority

Et successful `PilotTrialScopeProof` betyder kun:

- `human_pilot_go_verified=true`;
- `pilot_scope_verified=true`;
- den valgte scope er en ren indsnævring af ADR-DC-015.

Det betyder eksplicit ikke:

- at product/runtime er verificeret;
- at feature flag faktisk er observeret OFF;
- at feature flag må enable'es;
- at en pilot må starte;
- at en task må execute;
- at lokale commits faktisk må udføres;
- remote write/push/PR/merge/release/deploy;
- production activation.

Derfor er følgende hårdt låst:

- `pilot_runtime_verified=false`;
- `feature_flag_off_observed=false`;
- `pilot_start_authorized=false`;
- `product_pilot_started=false`;
- `remote_write_authorized=false`;
- `push_authorized=false`;
- `pr_mutation_authorized=false`;
- `merge_authorized=false`;
- `release_authorized=false`;
- `deploy_authorized=false`;
- `production_activation_authorized=false`.

Authority-strengen er kun:

`verified-dc-l16-single-trial-scope-only`

## Ingen runtime-observation

Denne slice har bevidst ingen host boundary, filesystem-observer, feature-flag
reader, command materializer eller execution adapter. Den tager kun et allerede
verificeret beslutningsproof og producerer et deterministisk, snævrere
data-artifact.

`feature_flag_default_off=true` beskriver den signerede governance-invariant fra
ADR-DC-015. Den må ikke forveksles med en observation af faktisk runtime-state;
derfor er `feature_flag_off_observed=false`.

## Package boundary

Modulet importeres ikke fra `kaliv_dev_control/__init__.py`. En caller skal
eksplicit importere `kaliv_dev_control.improvement_pilot_trial_scope`.

Det normale `modelrig_command_catalog()` forbliver tomt.

## Tests

Adversarial contract skal mindst bevise:

1. NO-GO afvises.
2. Task uden for human allowlist afvises.
3. Operator-surface mismatch afvises.
4. Workspace-digest mismatch afvises.
5. Local-commit escalation afvises.
6. Human `local_commits_allowed=true` kan indsnævres til `false`.
7. Conditional GO bevarer notes og giver stadig ingen start authority.
8. Serialized proof kan ikke eskalere runtime/flag/start booleans.
9. Package root importerer ikke modulet.
10. Det normale command catalog forbliver tomt.

## Governance

Denne ADR udfører ingen fysisk campaign og er ikke et human GO. Den implementerer
heller ikke den rigtige DC-L16 product entrypoint.

Enhver senere runtime-binding, flag-observation, pilot-start eller execution
kræver en separat reviewet authority-grænse. Merge, publication, release, deploy
og production activation forbliver særskilte menneskelige gates.

`production_activation=false`.
