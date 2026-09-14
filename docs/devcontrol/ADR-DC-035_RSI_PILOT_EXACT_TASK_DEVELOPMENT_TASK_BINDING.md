# ADR-DC-035 — Host-pinned pilot-task → DevelopmentTask binding

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-034 fastlåser, at en senere executor kun må materialisere én exact `DevelopmentTask` via en host-pinned mapping. Det er nødvendigt, fordi pilot-domænet og DevControl-task-domænet med vilje bruger forskellige identitetsgrammatikker:

- pilot scope kan fx bruge `task-local-001`;
- `DevelopmentTask.task_id` kræver `[A-Z][A-Z0-9_-]{2,63}`.

De to IDs må derfor ikke sammenlignes som rå strings. Samtidig må modellen eller en caller ikke selv vælge hvilken `DevelopmentTask` et signed pilot-ID skal betyde.

## Decision

Vi indfører en separat host-controlled ADR-DC-035 boundary.

Production læser kun én canonical registry-fil:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-development-task-registry-v1.json`
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-development-task-registry-v1.json`

Registry-filen skal være host-admin controlled efter samme fail-closed fil/ACL-regler som de eksisterende verification-only authority files. Production kræver elevated operator og accepterer ingen caller-valgt path, registry payload eller alternativ loader.

Registry-schemaet er `kaliv-rsi-dc-l16-exact-task-development-task-registry/v1`. Hver entry binder:

- `selected_pilot_task_id`;
- hele den immutable `kaliv-development-task/v1`;
- canonical SHA-256 af taskens canonical JSON.

Entries skal være canonical JSON, sorteret og unikke på pilot-ID. `DevelopmentTask.task_id` skal også være unik i registryen.

## DevelopmentTask restrictions

En ADR-DC-035-registry entry accepteres kun når tasken allerede opfylder den smalle execution-shape, som ADR-DC-034 kræver:

- repository er exact `Ternedal/ModelRig`;
- base SHA matcher den signerede pilot-scope;
- merge authority forbliver `human`;
- præcis én `allowed_command_id`;
- `required_tests` er præcis den samme ene command;
- task budget er et validt bounded `TaskBudget`.

ADR-DC-035 vælger ikke catalog, toolchain eller binary. Den binder kun den exact task, som næste boundary må bruge.

## Live provenance

Binding kræver samtidig:

1. det exact ADR-DC-034 requirements-artifact;
2. den **samme live ADR-DC-033 receipt-instans** med `transaction_authenticated=true`, leveret separat;
3. exact receipt SHA, execution nonce, selected pilot task og workspace digest skal matche ADR-DC-034.

ADR-DC-034 requirements er med vilje serializable/reloadable. Den nested ADR-DC-033 receipt i et reloaded requirements-artifact er derfor inert og behøver ikke være samme Python-instans som den separat leverede live receipt. ADR-DC-035 validerer semantic identity mellem requirements og den live receipt og binder derefter live provenance til den separat leverede receipt-instans.

Det serialized binding-artifact er kun audit-evidence. `host_registry_verified=true` i JSON er derfor ikke i sig selv live materialization authority: en caller kunne ellers konstruere et syntaktisk gyldigt binding-artifact uden nogensinde at have læst den host-kontrollerede registry.

Kun den exact binding-instans, som returneres direkte af production-boundaryen efter succesfuld læsning af den canonical host-admin registry, får process-local `transaction_authenticated=true`. Provenance bindes til exact binding-object identity, bindingens canonical SHA-256 og den **separat leverede exact live ADR-DC-033 receipt-instans**. Den process-lokale registry holder både binding og receipt stærkt, så Python object-ID reuse ikke kan overføre authority til en anden instans.

Live-provenance-registryen er bounded til 1024 bindings. Hvis grænsen overskrides, evictes den ældste entry; det revokerer kun authority og er derfor fail-closed. Registryen nulstilles efter `fork`, så child-processer ikke arver host-registry authority.

`transaction_authenticated` er bevidst **ikke** et dataclass-/JSON-schemafelt og serialiseres ikke. Den deterministic/private binding-seam får aldrig live provenance. `from_mapping(...)` og enhver anden reload skaber en ny binding-instans og giver derfor `transaction_authenticated=false`, selv hvis de serialized bytes er identiske og den oprindelige live ADR-DC-033 receipt stadig findes i processen.

Public production-verifier `require_live_pilot_exact_task_development_task_binding(binding, admission_receipt)` kræver både den exact registrerede binding-instans og den exact live receipt-instans, som production registrerede sammen med den. En inert/reloaded receipt eller en reloaded binding afvises fail-closed.

En senere Tier-A materialization-boundary skal derfor kræve både:

- ADR-DC-035 binding med `transaction_authenticated=true`; og
- den samme live ADR-DC-033 receipt separat gennem production-verifieren.

Durable ADR-DC-035 JSON kan bruges som historisk evidens, men kan ikke mint'e en execution-plan capability efter serialization/reload.

## Binding artifact

Et successfuldt `kaliv-rsi-dc-l16-exact-task-development-task-binding/v1` binder mindst:

- ADR-DC-034 requirements + SHA;
- ADR-DC-033 receipt SHA;
- execution nonce;
- whole-registry SHA-256;
- selected pilot task ID;
- whole `DevelopmentTask` + task ID + task SHA-256;
- exact fixed command ID;
- repository/base/requested-main scope;
- workspace digest;
- human local-commit upper bound.

Positive serialized evidence flags er kun:

- `host_registry_verified=true`;
- `pilot_task_mapping_verified=true`;
- `development_task_materialized=true`;
- `single_fixed_command_verified=true`.

De flags er historical evidence; live downstream authority kræver desuden process-local `transaction_authenticated=true` som beskrevet ovenfor.

Authority er kun `host-bound-one-exact-development-task-only`.

## Authority stop

ADR-DC-035 holder obligatorisk:

- `execution_plan_materialized=false`;
- `execution_consumed=false`;
- `task_execution_started=false`;
- `task_execution_completed=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Boundaryen kalder ikke `LeasedCatalogMaterializer`, bygger ingen execution lease, resolver ingen runtime closure, læser ingen workspace, starter ingen subprocess og muterer ikke Git.

## Why the whole task is embedded

Det er ikke nok kun at gemme `DevelopmentTask.task_id`. Task-kontrakten indeholder også paths, commands, required tests og execution budget. ADR-DC-035 embedder derfor hele canonical task plus SHA-256, så en senere materializer ikke kan resolve samme task-ID til ændret authority.

## Next boundary

Næste sikre boundary er exact Tier-A capability/materialization over en **live-authenticated** ADR-DC-035 binding plus den samme live ADR-DC-033 receipt:

- reviewed non-empty one-command catalog;
- exact toolchain;
- fresh physical Windows isolation attestation;
- `LeasedCatalogMaterializer` / execution lease;
- signed runtime closure;
- exact workspace identity.

Den boundary skal stadig være non-executing. Først et efterfølgende one-shot executor-consumption-led må kalde `run_single_verified_tier_a_command_with_receipt(...)` og udstede separat post-execution consumption evidence.

`production_activation=false`.
