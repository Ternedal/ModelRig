# ADR-DC-034 — Exact execution-plan requirements before executor consumption

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-033 kan udstede én live, host-local, replay-safe admission for præcis den human-authorized execution nonce. Det receipt kan sætte `task_execution_authorized=true`, men holder bevidst `task_execution_started=false` og `execution_consumed=false`.

Det er stadig ikke sikkert at kalde en executor direkte. ADR-DC-033 binder pilot-task-ID, workspace-scope og upstream host-attested evidence, men den materialiserer ikke de konkrete runtime-objekter som eksisterende Tier-A execution kræver: `DevelopmentTask`, reviewed command catalog, toolchain, signed runtime closure, trusted Git runtime, Windows isolation evidence og exact workspace.

De objekter må ikke blive caller-valgt authority blot fordi en tidligere host-attestation sagde, at tilsvarende gates var grønne. Der skal først være en separat boundary, som fastlåser hvilke konkrete objekter og identitetschecks den senere executor-transaktion skal materialisere.

## Decision

Vi indfører et inert `kaliv-rsi-dc-l16-exact-task-execution-plan-requirements/v1` artifact.

Artifactet kan **kun bygges fra den exact live ADR-DC-033 receipt-instans**, som den succesfulde durable admission-transaktion returnerede. `transaction_authenticated=true` er process-local provenance og serialiseres ikke. En durable/reloaded ADR-DC-033 receipt kan derfor bevares som historisk evidens, men kan ikke udstede et nyt ADR-DC-034 requirements-artifact.

ADR-DC-034 binder:

- exact ADR-DC-033 receipt SHA-256;
- admission replay key og human-signed execution nonce;
- ADR-DC-032 revalidation proof SHA-256;
- ADR-DC-030 execution-authorization proof SHA-256;
- ADR-DC-025 start-receipt SHA-256;
- repository, base SHA og requested main SHA;
- trial ID og operator surface;
- exact selected pilot task ID;
- workspace-root digest;
- human-signed local-commit upper bound.

## Pilot task ID vs. DevelopmentTask ID

`selected_pilot_task_id` og `DevelopmentTask.task_id` er bevidst to forskellige identitetsdomæner og må ikke sammenlignes direkte som samme streng.

Det eksisterende pilot-scope bruger IDs som fx `task-local-001`, mens `DevelopmentTask.task_id` følger den strengere control-plane syntaks `[A-Z][A-Z0-9_-]{2,63}`. En direkte equality-gate ville derfor gøre en ellers legitim pilot umulig at materialisere.

Den senere host-pinned task registry skal i stedet levere en canonical, exact-bound mapping:

`selected_pilot_task_id -> DevelopmentTask.task_id + DevelopmentTask SHA-256`.

Mappingen må ikke være model-valgt eller caller-valgt. Den skal komme fra den host-pinned registry, bindes til exact ADR-DC-034 requirements og verificeres før nogen Tier-A plan kan materialiseres.

## Mandatory later executor gates

En senere executor-consumption boundary skal conjunctively materialisere og verificere alle følgende. Ingen må degraderes til optional mode:

1. den exact live ADR-DC-033 admission receipt;
2. exact receipt identity og one-shot executor consumption;
3. host-pinned task registry;
4. exact `DevelopmentTask` for den valgte pilot-task;
5. canonical pilot-task-ID → `DevelopmentTask` ID + SHA-256 mapping;
6. repository/base binding mod signed scope;
7. canonical workspace equality mod signed workspace digest;
8. præcis én fixed required command;
9. et reviewed **non-empty** command catalog for denne execution — det normale ModelRig catalog forbliver tomt;
10. exact toolchain binding;
11. signed runtime closure;
12. trusted Git runtime;
13. native Windows Tier-A isolation;
14. network deny;
15. credentials absent;
16. general shell forbidden;
17. model-defined commands forbidden;
18. unattended cadence forbidden;
19. exact bounded execution budget;
20. manual operator invocation;
21. pre-execution Git snapshot;
22. post-execution canonical Tier-A command receipt;
23. fail-closed exact-base reset hvis workspace drift opdages;
24. separat post-execution consumption receipt, så ADR-DC-033 admission ikke kan eksekveres to gange.

## Existing executor substrate

ADR-DC-034 introducerer **ikke** en ny process runner.

Den senere executor skal genbruge den eksisterende hardened Tier-A path, herunder:

- `run_verified_tier_a_command(...)` / `run_single_verified_tier_a_command_with_receipt(...)`;
- signed runtime-closure verification og staging;
- Windows AppContainer / restricted launch policy;
- Job Object lifetime, memory/process limits og timeout cleanup;
- bounded stdout/stderr capture;
- trusted Git workspace snapshots;
- network-deny policy;
- exact-base reset ved workspace drift.

ADR-DC-034 kalder ingen af disse funktioner. Den fastlåser kun requirements for den senere executor-transaktion.

## Live authority and serialization

`build_pilot_exact_task_execution_plan_requirements(...)` kræver `receipt.transaction_authenticated is True`.

Det færdige requirements-artifact er selv inert og må gerne serialiseres/reloades. Nested ADR-DC-033 receipt vil efter reload have `transaction_authenticated=false`; det er forventet. Reload kan bruges til audit og plan-definition, men kan ikke genskabe live executor authority eller bruges til at udstede et nyt requirements-artifact.

Denne asymmetri er tilsigtet: live authority må kun bevæge sig frem gennem den konkrete process-local transaction, aldrig genopstå fra durable JSON.

## Authority stop

Et gyldigt ADR-DC-034 requirements-artifact holder obligatorisk:

- `execution_plan_materialized=false`;
- `execution_consumed=false`;
- `task_execution_started=false`;
- `task_execution_completed=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority er kun `dc-l16-exact-task-execution-plan-requirements-only`.

Det resolver ingen task registry, opretter ingen command catalog, læser ingen workspace, starter ingen subprocess, ændrer ingen Git-state og giver ingen publication authority.

## Local commit scope

`local_commits_allowed_by_human_scope` arves kun som upper bound fra den signerede upstream scope. ADR-DC-034 giver fortsat `local_commit_authorized=false`.

Hvis en senere execution ønsker at materialisere en lokal commit efter successful Tier-A execution, kræver det en særskilt boundary, som eksplicit narrower human scope og binder post-execution evidence. Remote writes, push, PR mutation, merge, release, deploy og production activation forbliver separate authority-gates.

## Next boundary

Næste sikre boundary er host-pinned materialization af ét exact executor plan/capability fra ADR-DC-034 requirements og den **samme live ADR-DC-033 receipt**. Først når pilot→DevelopmentTask mapping og concrete task/catalog/toolchain/runtime/workspace identities er verificeret mod den signed chain, kan en separat one-shot executor transaction kalde den eksisterende Tier-A runtime og udstede post-execution consumption evidence.

`production_activation=false`.
