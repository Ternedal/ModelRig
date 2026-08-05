# Tier-A execution core split contract

Schema: `kaliv-tier-a-execution-core-split-contract/v1`

This is a review and migration contract for `devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py`. H10J does **not** move production code. It freezes the current ownership surface, the only external source consumer, the public object-identity chains and a one-to-one proposed destination for every owned top-level symbol.

The authoritative machine-readable contract is `devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json`.

## Proposed private modules

- `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` — lease schema, shared validation, canonical lease identity and `TierAExecutionLease`.
- `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` — reviewed application-environment policy and validation.
- `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` — canonical directory, workspace authority and regular-file identity checks.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py` — retained v2 bundle identity used only by the legacy core.
- `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` — physical-evidence capture, leased registry and catalog materialization.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` — retained v1 launch-plan model and construction.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py` — retained non-capturing Windows executor removed by modern authority at import time.

## Exact symbol mapping

| Symbol | Kind | Responsibility | Proposed destination |
|---|---|---|---|
| `LEASE_SCHEMA` | constant | lease model | `_tier_a_lease.py` |
| `PLAN_SCHEMA` | constant | legacy plan model | `_tier_a_legacy_plan.py` |
| `_HEX40` | constant | schema validation | `_tier_a_lease.py` |
| `_HEX64` | constant | schema validation | `_tier_a_lease.py` |
| `_TASK_ID` | constant | schema validation | `_tier_a_lease.py` |
| `_COMMAND_ID` | constant | legacy plan model | `_tier_a_legacy_plan.py` |
| `TIER_A_APPLICATION_ENVIRONMENT` | constant | environment policy | `_tier_a_environment.py` |
| `_TIER_A_BUNDLE_FILES` | constant | legacy toolhost identity | `_tier_a_legacy_toolhost.py` |
| `TierAExecutionError` | class | lease model | `_tier_a_lease.py` |
| `_canonical` | function | canonical identity | `_tier_a_lease.py` |
| `_sha256` | function | canonical identity | `_tier_a_lease.py` |
| `_task_sha` | function | canonical identity | `_tier_a_lease.py` |
| `_has_symlink_component` | function | path authority | `_tier_a_path_authority.py` |
| `_canonical_directory` | function | path authority | `_tier_a_path_authority.py` |
| `workspace_root_authority_sha256` | function | path authority | `_tier_a_path_authority.py` |
| `tier_a_toolhost_sha256` | function | legacy toolhost identity | `_tier_a_legacy_toolhost.py` |
| `_validated_application_env` | function | environment policy | `_tier_a_environment.py` |
| `TierAExecutionLease` | class | lease model | `_tier_a_lease.py` |
| `_LeaseCapturingVerifier` | class | evidence materialization | `_tier_a_materialization.py` |
| `LeasedCommandRegistry` | class | command registry | `_tier_a_materialization.py` |
| `LeasedCatalogMaterializer` | class | evidence materialization | `_tier_a_materialization.py` |
| `TierALaunchPlan` | class | legacy plan model | `_tier_a_legacy_plan.py` |
| `_regular_file_hash` | function | path authority | `_tier_a_path_authority.py` |
| `build_tier_a_launch_plan` | function | legacy launch planning | `_tier_a_legacy_plan.py` |
| `_run_tier_a_launch_plan` | function | legacy execution | `_tier_a_legacy_runner.py` |
| `run_verified_tier_a_command` | function | legacy execution | `_tier_a_legacy_runner.py` |

The contract test parses the source AST and requires this table's authoritative JSON mapping to match the source order, symbol names and kinds exactly. A missing, duplicated or newly added top-level symbol fails CI.

## Current external consumer

The only source module importing `_tier_a_execution_core` is `devcontrol/src/kaliv_dev_control/tier_a_authority.py` under the alias `_core`.

It directly references `LEASE_SCHEMA`, `LeasedCatalogMaterializer`, `LeasedCommandRegistry`, `TIER_A_APPLICATION_ENVIRONMENT`, `TierAExecutionError`, `TierAExecutionLease`, `_canonical_directory` and `workspace_root_authority_sha256`.

It deliberately removes `_run_tier_a_launch_plan` and `run_verified_tier_a_command` from the imported legacy core. This prevents the obsolete non-capturing executor from remaining reachable after modern authority initialization.

## Public object identities that a future split must preserve

- `LeasedCatalogMaterializer`: `_tier_a_execution_core` → `tier_a_authority` → `tier_a_execution` → `kaliv_dev_control`.
- `LeasedCommandRegistry`: `_tier_a_execution_core` → `tier_a_authority` → `tier_a_execution` → `kaliv_dev_control`.
- `TIER_A_APPLICATION_ENVIRONMENT`: `_tier_a_execution_core` → `tier_a_authority` → `tier_a_execution` → `kaliv_dev_control`.
- `TierAExecutionError`: `_tier_a_execution_core` → `tier_a_authority` → `tier_a_execution` → `kaliv_dev_control`.
- `TierAExecutionLease`: `_tier_a_execution_core` → `tier_a_authority` → `tier_a_execution` → `kaliv_dev_control`.
- `workspace_root_authority_sha256`: `_tier_a_execution_core` → `tier_a_authority` → `tier_a_execution` → `kaliv_dev_control`.

CI imports all four surfaces and proves each chain is the same Python object by identity, not merely an equivalent replacement.

## Future split constraints

A later production split must preserve the public import paths and object identities above, retain the modern authority's removal of the two obsolete executor functions, and update the exact Tier-A bundle. Because moving authority-bearing source changes the toolhost digest, all previous physical evidence will become stale and a fresh physical campaign will be required after the code is frozen.
