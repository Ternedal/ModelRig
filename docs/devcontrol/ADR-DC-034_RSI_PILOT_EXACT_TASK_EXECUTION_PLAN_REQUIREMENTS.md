# ADR-DC-034 — Exact execution-plan requirements before executor consumption

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-033 kan udstede én live, host-local, replay-safe admission for præcis den human-authorized execution nonce. Det receipt kan sætte `task_execution_authorized=true`, men holder bevidst `task_execution_started=false` og `execution_consumed=false`.

Det er stadig ikke sikkert at kalde en executor direkte. ADR-DC-033 binder pilot-task-ID, workspace-scope og upstream host-attested evidence, men den materialiserer ikke de konkrete runtime-objekter som eksisterende Tier-A execution kræver: `DevelopmentTask`, reviewed command catalog, toolchain, signed runtime closure, trusted Git runtime, Windows isolation evidence og exact workspace.

De objekter må ikke blive caller-valgt authority blot fordi en tidligere host-attestation sagde, at tilsvarende gates var grønne. Der skal først være en separat boundary, som fastlåser hvilke konkrete objekter, trust roots og identitetschecks den senere executor-transaktion skal materialisere.

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
12. en host-pinned `WindowsPhysicalIsolationVerifier`, inklusive dens physical-evidence root, keyring, freshness policy, clock og file bound;
13. en host-resolved exact `IsolationAttestation`, bundet til task/catalog/toolchain og den samme canonical physical-evidence authority;
14. caller-selected `IsolationAttestation` forbidden, også når objektet isoleret set har korrekt Python-type og schema;
15. en host-pinned `RuntimeClosureVerifier`, inklusive dens verification keyring og closure budgets;
16. canonical trusted-runtime-root, som den signerede runtime closure er bundet til;
17. en host-pinned `TrustedGitRunner`, ikke en caller-konstrueret Git authority;
18. signed control-plane/toolhost identity, så caller ikke kan vælge en anden `control_plane_root`;
19. reviewed source environment for den native launch path; caller-valgt `source_env` må ikke blive credential/environment authority;
20. exact native process limits, inklusive memory- og active-process bounds, i tillæg til taskens runtime/output budget;
21. caller-selected executable verifier forbidden; den eksisterende materializer accepterer ikke en alternativ verifier;
22. trusted Git runtime identity;
23. native Windows Tier-A isolation;
24. network deny;
25. credentials absent;
26. general shell forbidden;
27. model-defined commands forbidden;
28. unattended cadence forbidden;
29. exact bounded execution budget;
30. manual operator invocation;
31. pre-execution Git snapshot;
32. post-execution canonical Tier-A command receipt;
33. fail-closed exact-base reset hvis workspace drift opdages;
34. separat post-execution consumption receipt, så ADR-DC-033 admission ikke kan eksekveres to gange.

## Host-pinned executor authority

De eksplicitte host-pinning krav er nødvendige, fordi den eksisterende hardened Tier-A API med vilje tager flere authority-bearing objekter som inputs. En korrekt Python-type er ikke i sig selv en canonical trust root.

`WindowsPhysicalIsolationVerifier` konstrueres blandt andet med `evidence_root` og `keyring`. En caller-konstrueret verifier kunne derfor ellers verificere caller-valgt fysisk evidence med caller-valgte signing keys. Den senere materialization boundary skal selv eje og resolve den canonical verifier; caller må ikke levere den.

`IsolationAttestation` er samtidig et separat input til `run_verified_tier_a_command(...)`. Selvom den eksisterende `LeasedCatalogMaterializer` revaliderer attestationens task/catalog/toolchain-identitet og kræver et report fra `WindowsPhysicalIsolationVerifier`, må caller ikke vælge mellem eller konstruere attestationer som execution authority. Den senere boundary skal host-resolve den exact attestation fra den canonical physical-evidence context og bevise dens binding til exact `DevelopmentTask`, reviewed catalog og exact toolchain før Tier-A materialization.

`RuntimeClosureVerifier` konstrueres med sin egen keyring og verifier budgets, mens `trusted_runtime_root` er en separat path authority bundet ind i runtime-closure manifestet. Begge skal resolves fra host-controlled configuration, ikke fra execution-requestet.

`run_single_verified_tier_a_command_with_receipt(...)` tager desuden `git_runner`, `control_plane_root`, `source_env`, `process_memory_bytes` og `active_process_limit`. Den senere boundary skal derfor pinne den trusted Git authority, bevise signed toolhost/control-plane identity, levere et reviewed/sanitized source environment og fastlåse native process limits. `executable_verifier` skal forblive `None`/ikke caller-valgt, i tråd med den eksisterende `LeasedCatalogMaterializer`-boundary.

Disse krav giver ikke ADR-DC-034 process authority. De beskriver præcist, hvilke authority inputs en senere host-pinned materialization/executor boundary skal eje, før eksisterende Tier-A kode må kaldes.

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

Næste sikre boundary er host-pinned materialization af ét exact executor plan/capability fra ADR-DC-034 requirements og den **samme live ADR-DC-033 receipt**. Materialization skal selv resolve pilot→DevelopmentTask mapping, exact isolation attestation og alle canonical trust roots/authority inputs ovenfor; caller må ikke levere verifiers, attestation, keyrings, roots, environment eller native process limits.

Først når concrete task/catalog/toolchain/runtime/workspace/toolhost identities er verificeret mod den signed chain, kan en separat one-shot executor transaction kalde den eksisterende Tier-A runtime og udstede post-execution consumption evidence.

`production_activation=false`.
