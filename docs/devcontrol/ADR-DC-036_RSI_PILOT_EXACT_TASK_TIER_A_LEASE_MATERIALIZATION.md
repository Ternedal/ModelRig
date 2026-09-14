# ADR-DC-036 — Host-pinned exact Tier-A lease materialization

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-035 binder ét signeret pilot-task-ID til én immutable `DevelopmentTask`, men giver stadig ingen Tier-A capability. ADR-DC-034 kræver, at senere execution genbruger den eksisterende hardenede Tier-A Windows-path og ikke introducerer general shell, model-definerede commands eller caller-valgte trust roots.

Det næste authority-led skal derfor materialisere den mindst mulige eksisterende Tier-A capability uden at bygge runtime closure eller starte en proces.

## Decision

ADR-DC-036 materialiserer præcis én non-executing `LeasedCommandRegistry` gennem den eksisterende `LeasedCatalogMaterializer` og udleverer den kun bag en process-local capability-wrapper.

Første slice er bevidst låst til den allerede reviewed standalone version-check profil:

- command ID: `modelrig.version.check`;
- tool ID: `modelrig-version-check`;
- exact reviewed catalog SHA-256: `b687f940160ba6ca7a14ae84f8315da851a9698b0c50039f8bb6d02dfee458c4`;
- native process memory limit: `134217728` bytes;
- active process limit: `1`.

Det normale `modelrig_command_catalog()` forbliver tomt. ADR-DC-036 aktiverer ikke en generel command catalog.

## Required live authority

Materialization kræver samtidigt:

1. den exact ADR-DC-035 `DevelopmentTask` binding;
2. den samme **live** ADR-DC-033 admission receipt med `transaction_authenticated=true`;
3. exact receipt SHA, execution nonce, selected pilot task og signed workspace-path identity fra upstream kæden.

En serialized/reloaded ADR-DC-033 receipt er audit evidence בלבד og kan ikke materialisere en ny Tier-A capability.

## Host-owned production roots

Production er Windows-only og accepterer ingen caller-valgt profile, verifier, evidence-root, catalog, toolchain eller attestation.

Den canonical profile læses kun fra:

`C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-tier-a-version-check-profile-v1.json`

Profilen skal være host-admin controlled via de eksisterende fail-closed Windows ACL-regler og indeholder kun den exact tool binding, exact isolation attestation, physical-verifier policy/keyring og de fixed native process limits.

Signed physical evidence læses kun under:

`C:\Program Files\ModelRig\DevControl\state\rsi-pilot-exact-task-tier-a-physical-evidence-v1`

Hele evidence-directory-kæden tilbage til `Program Files` ACL-valideres som host-admin controlled og link/reparse-point-fri, før den eksisterende `WindowsPhysicalIsolationVerifier` må bruge den.

## Existing Tier-A materializer

ADR-DC-036 genbruger uændret:

- `WindowsPhysicalIsolationVerifier`;
- `LeasedCatalogMaterializer`;
- `TierAExecutionLease`;
- `LeasedCommandRegistry`;
- `workspace_root_authority_sha256(...)`;
- `tier_a_toolhost_sha256(...)`.

Den signed physical report skal være exact bundet til `DevelopmentTask`, reviewed catalog, toolchain, OS-isolated boundary og `network_mode=deny`. Materializeren udsteder derefter den eksisterende execution lease, men **ingen proces startes**.

## Two workspace identities

Pilot-kædens `workspace_root_path_sha256` og Tier-A lease'ens `workspace_root_sha256` er forskellige security-domæner og må ikke sammenlignes direkte:

- pilot-kæden binder SHA-256 af den canonical workspace path;
- Tier-A bruger den domain-separerede `kaliv-tier-a-workspace/v1` authority-hash.

ADR-DC-036 revaliderer og binder begge identities til den samme resolved workspace. Den binder samtidig den exact `tier_a_toolhost_sha256` til den signed physical lease.

## Durable evidence vs live capability

Det durable artifact `kaliv-rsi-dc-l16-exact-task-tier-a-lease-materialization/v1` indeholder task-binding, nonce, profile/catalog/toolchain identities, isolation attestation, execution lease, begge workspace identities, toolhost identity og fixed native process limits.

Durable evidence kan round-trippe for audit, men kan ikke genskabe den process-local registry capability. Public reload validerer desuden reviewed catalog SHA både top-level og inde i attestation/lease samt fixed command/process limits. Et selvkonsistent artifact med en anden catalog identity afvises.

Den public capability eksponerer ikke den rå `LeasedCommandRegistry`. En senere host-owned boundary kan kun få registryen gennem en privat handoff-seam, som først revaliderer catalog, toolchain, attestation, lease, workspace, toolhost og process limits mod durable evidence.

## Authority stop

ADR-DC-036 sætter kun materialization-evidence for host profile, reviewed catalog, exact toolchain, isolation attestation, execution lease, workspace og toolhost.

Følgende forbliver obligatorisk `false`:

- `runtime_closure_materialized`;
- `execution_plan_materialized`;
- `execution_consumed`;
- `task_execution_started`;
- `task_execution_completed`;
- `integration_ready`;
- `product_pilot_started`;
- `local_commit_authorized`;
- remote write / push / PR mutation / merge / release / deploy;
- `production_activation_authorized`.

Boundaryen starter ingen subprocess, ændrer ikke Git, laver ingen local commit og udfører ikke tasken.

## What remains after ADR-DC-036

ADR-DC-034 kræver fortsat flere host-owned gates før execution. Næste non-executing boundary skal mindst host-resolve og binde:

- exact signed runtime closure;
- host-pinned `RuntimeClosureVerifier`;
- canonical trusted-runtime-root;
- host-pinned `TrustedGitRunner`;
- exact pre-execution `GitWorkspaceSnapshot` inklusive staged/unstaged/untracked state;
- reviewed host-owned source environment;
- launch-plan identity med fresh snapshot revalidation før launch.

Først et separat one-shot executor-consumption-led må derefter kalde den eksisterende `run_single_verified_tier_a_command_with_receipt(...)`. Uncertainty efter execution-consumption reservation må ikke gøre nonce/genforsøg genbrugeligt.

`production_activation=false`.
