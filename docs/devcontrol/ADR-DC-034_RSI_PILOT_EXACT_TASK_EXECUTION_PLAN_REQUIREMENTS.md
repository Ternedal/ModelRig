# ADR-DC-034 — Exact execution-plan requirements before executor consumption

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-033 kan udstede én live, host-local, replay-safe admission for præcis den human-authorized execution nonce. Det receipt kan sætte `task_execution_authorized=true`, men holder bevidst `task_execution_started=false` og `execution_consumed=false`.

Det er stadig ikke sikkert at kalde en executor direkte. ADR-DC-033 binder pilot-task-ID, workspace-scope og upstream host-attested evidence, men den materialiserer ikke de konkrete runtime-objekter som eksisterende Tier-A execution kræver: `DevelopmentTask`, reviewed command catalog, toolchain, signed runtime closure, trusted Git runtime, Windows isolation evidence og exact workspace.

De objekter må ikke blive caller-valgt authority blot fordi en tidligere host-attestation sagde, at tilsvarende gates var grønne. Der skal først være en separat boundary, som fastlåser hvilke konkrete objekter, trust roots, workspace-state og identitetschecks den senere executor-transaktion skal materialisere.

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
11. en exact host-resolved signed runtime closure; caller må ikke vælge mellem signer-godkendte closure-artifacts;
12. en host-pinned `WindowsPhysicalIsolationVerifier`, inklusive dens physical-evidence root, keyring, freshness policy, clock og file bound;
13. en host-resolved exact `IsolationAttestation`, bundet til task/catalog/toolchain og den samme canonical physical-evidence authority;
14. caller-selected `IsolationAttestation` forbidden, også når objektet isoleret set har korrekt Python-type og schema;
15. en host-pinned `RuntimeClosureVerifier`, inklusive dens verification keyring og closure budgets;
16. en canonical **host-resolved** trusted-runtime-root, som den signerede runtime closure er bundet til; caller-selected root er forbidden;
17. en host-pinned `TrustedGitRunner`, ikke en caller-konstrueret Git authority;
18. signed control-plane/toolhost identity, så caller ikke kan vælge en anden `control_plane_root`;
19. reviewed host-owned source environment for den native launch path; caller-valgt `source_env` er forbidden;
20. exact host-resolved native process limits, inklusive memory- og active-process bounds, i tillæg til taskens runtime/output budget; caller-valgte limits er forbidden;
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
31. en host-resolved pre-execution `GitWorkspaceSnapshot` med exact base HEAD, staged-patch SHA-256/byte count og dokumenteret tom unstaged/untracked state;
32. exact workspace-state snapshot bundet ind i det materialiserede executor-plan/capability;
33. fresh trusted-Git re-snapshot umiddelbart før process launch og exact equality med planens snapshot;
34. enhver workspace-state ændring efter plan-materialization og før launch skal fail closed uden task execution;
35. post-execution canonical Tier-A command receipt;
36. fail-closed exact-base reset hvis workspace drift opdages;
37. separat post-execution consumption receipt, så ADR-DC-033 admission ikke kan eksekveres to gange.

## Host-pinned executor authority

De eksplicitte host-pinning krav er nødvendige, fordi den eksisterende hardened Tier-A API med vilje tager flere authority-bearing objekter som inputs. En korrekt Python-type eller en isoleret gyldig signatur er ikke i sig selv en canonical current execution authority.

`WindowsPhysicalIsolationVerifier` konstrueres blandt andet med `evidence_root` og `keyring`. En caller-konstrueret verifier kunne derfor ellers verificere caller-valgt fysisk evidence med caller-valgte signing keys. Den senere materialization boundary skal selv eje og resolve den canonical verifier; caller må ikke levere den.

`IsolationAttestation` er samtidig et separat input til `run_verified_tier_a_command(...)`. Selvom den eksisterende `LeasedCatalogMaterializer` revaliderer attestationens task/catalog/toolchain-identitet og kræver et report fra `WindowsPhysicalIsolationVerifier`, må caller ikke vælge mellem eller konstruere attestationer som execution authority. Den senere boundary skal host-resolve den exact attestation fra den canonical physical-evidence context og bevise dens binding til exact `DevelopmentTask`, reviewed catalog og exact toolchain før Tier-A materialization.

`SignedRuntimeClosureManifest` er også et direkte executor-input. Runtime-closure signaturen beviser, at en closure er signer-godkendt og binder den til task/catalog/toolchain/lease/workspace/root, men den udpeger ikke alene hvilken af flere potentielt signer-godkendte closures der er den current execution authority. Den senere boundary skal derfor host-resolve den exact signed closure; caller-selected closure er forbidden.

`RuntimeClosureVerifier` konstrueres med sin egen keyring og verifier budgets, mens `trusted_runtime_root` er en separat path authority. `trusted_runtime_root_sha256(...)` binder den canonical absolute root-path ind i runtime-closure manifestet. Derfor skal både verifieren og rooten resolves fra host-controlled configuration. Ellers kan en caller vælge en anden signer-godkendt closure/root-kombination uden at bryde closure-signaturen.

`run_single_verified_tier_a_command_with_receipt(...)` tager desuden `git_runner`, `control_plane_root`, `source_env`, `process_memory_bytes` og `active_process_limit`. Den senere boundary skal derfor pinne den trusted Git authority, bevise signed toolhost/control-plane identity, bruge den host-ejede source environment gennem den eksisterende positive allowlist og resolve én canonical native process-limit policy. Caller må ikke levere `source_env`, memory-limit eller process-count. `executable_verifier` skal forblive `None`/ikke caller-valgt, i tråd med den eksisterende `LeasedCatalogMaterializer`-boundary.

Disse krav giver ikke ADR-DC-034 process authority. De beskriver præcist, hvilke authority inputs en senere host-pinned materialization/executor boundary skal eje, før eksisterende Tier-A kode må kaldes.

## Pre-execution workspace-state binding

Den eksisterende `run_single_verified_tier_a_command_with_receipt(...)` kræver exact task base som `HEAD`, afviser unstaged og untracked state, men tillader bevidst en optional **staged patch** før execution. `GitWorkspaceSnapshot` binder allerede `head_sha`, staged patch SHA-256/byte count, unstaged patch SHA-256/byte count og untracked-path SHA-256/count.

ADR-DC-030 human execution authorization binder task, base, canonical workspace og one-shot nonce, men binder ikke staged-patch hash direkte. ADR-DC-034 må derfor ikke lade en senere executor-plan sige blot "pre-execution snapshot required" og derefter acceptere hvad der tilfældigvis ligger staged ved launch.

Den næste materialization boundary skal selv læse workspace gennem den host-pinned `TrustedGitRunner`, kræve exact base `HEAD`, kræve tom unstaged/untracked state og fryse hele `GitWorkspaceSnapshot` ind i plan/capability-identiteten. Hvis en staged patch findes, bliver dens exact SHA-256 og byte count dermed en del af den materialiserede plan-identitet.

Den separate one-shot executor transaction skal tage en fresh trusted-Git snapshot **umiddelbart før launch** og kræve byte-identisk snapshot-identitet med planen. Enhver ændring af HEAD, staged patch, unstaged state eller untracked paths mellem materialization og launch skal afvises før `task_execution_started` kan blive sand.

Dette er en TOCTOU-grænse, ikke en påstand om at human authorization signer staged-patch bytes. Hvis en senere policy kræver menneskelig godkendelse af selve patch-indholdet, skal den authority tilføjes eksplicit som en særskilt signed scope/boundary; den må ikke udledes af ADR-DC-030. Lokale commits og al publication authority forbliver fortsat separate gates.

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

Næste sikre boundary er host-pinned materialization af ét exact executor plan/capability fra ADR-DC-034 requirements og den **samme live ADR-DC-033 receipt**. Materialization skal selv resolve pilot→DevelopmentTask mapping, exact isolation attestation, exact signed runtime closure, canonical authority inputs og exact pre-execution `GitWorkspaceSnapshot`; caller må ikke levere verifiers, attestation, closure, keyrings, roots, environment, native process limits eller workspace snapshot identity.

Den separate one-shot executor transaction skal derefter fresh re-snapshotte workspace lige før launch og kræve exact match med planens snapshot. Først når concrete task/catalog/toolchain/runtime/workspace/toolhost identities og workspace-state er verificeret mod planen, kan den kalde den eksisterende Tier-A runtime og udstede post-execution consumption evidence.

`production_activation=false`.
