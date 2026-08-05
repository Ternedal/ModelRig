# Tier-A execution core split contract

Schema: `kaliv-tier-a-execution-core-split-contract/v2`

This contract now records both the remaining legacy-core ownership and completed identity-preserving extractions. H10K moves only the reviewed Tier-A environment policy; no executor, Git, network or publication authority is added.

## Completed extraction

`TIER_A_APPLICATION_ENVIRONMENT` and `_validated_application_env` now originate in `devcontrol/src/kaliv_dev_control/_tier_a_environment.py`. The legacy core imports and re-exports the exact same objects. `TierAExecutionError` remains in the core and is resolved lazily when validation is called, keeping the new module directly importable during this intermediate split.

Adding the new authority-bearing module to the exact Tier-A bundle and changing the legacy core intentionally changes the toolhost digest. Every earlier physical I0b report is therefore stale; no replacement evidence is manufactured.

## Remaining exact symbol mapping

| Symbol | Kind | Responsibility | Proposed destination |
|---|---|---|---|
| `LEASE_SCHEMA` | constant | lease_model | `_tier_a_lease.py` |
| `PLAN_SCHEMA` | constant | legacy_plan_model | `_tier_a_legacy_plan.py` |
| `_HEX40` | constant | schema_validation | `_tier_a_lease.py` |
| `_HEX64` | constant | schema_validation | `_tier_a_lease.py` |
| `_TASK_ID` | constant | schema_validation | `_tier_a_lease.py` |
| `_COMMAND_ID` | constant | legacy_plan_model | `_tier_a_legacy_plan.py` |
| `_TIER_A_BUNDLE_FILES` | constant | legacy_toolhost_identity | `_tier_a_legacy_toolhost.py` |
| `TierAExecutionError` | class | lease_model | `_tier_a_lease.py` |
| `_canonical` | function | canonical_identity | `_tier_a_lease.py` |
| `_sha256` | function | canonical_identity | `_tier_a_lease.py` |
| `_task_sha` | function | canonical_identity | `_tier_a_lease.py` |
| `_has_symlink_component` | function | path_authority | `_tier_a_path_authority.py` |
| `_canonical_directory` | function | path_authority | `_tier_a_path_authority.py` |
| `workspace_root_authority_sha256` | function | path_authority | `_tier_a_path_authority.py` |
| `tier_a_toolhost_sha256` | function | legacy_toolhost_identity | `_tier_a_legacy_toolhost.py` |
| `TierAExecutionLease` | class | lease_model | `_tier_a_lease.py` |
| `_LeaseCapturingVerifier` | class | evidence_materialization | `_tier_a_materialization.py` |
| `LeasedCommandRegistry` | class | command_registry | `_tier_a_materialization.py` |
| `LeasedCatalogMaterializer` | class | evidence_materialization | `_tier_a_materialization.py` |
| `TierALaunchPlan` | class | legacy_plan_model | `_tier_a_legacy_plan.py` |
| `_regular_file_hash` | function | path_authority | `_tier_a_path_authority.py` |
| `build_tier_a_launch_plan` | function | legacy_launch_planning | `_tier_a_legacy_plan.py` |
| `_run_tier_a_launch_plan` | function | legacy_execution | `_tier_a_legacy_runner.py` |
| `run_verified_tier_a_command` | function | legacy_execution | `_tier_a_legacy_runner.py` |

## Exact core consumers

- `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` — direct: TierAExecutionError.
- `devcontrol/src/kaliv_dev_control/runtime_closure_builder.py` — direct: LeasedCommandRegistry, workspace_root_authority_sha256.
- `devcontrol/src/kaliv_dev_control/runtime_closure_staging.py` — module_alias: LeasedCommandRegistry.
- `devcontrol/src/kaliv_dev_control/runtime_closure_verify.py` — module_alias: LeasedCommandRegistry.
- `devcontrol/src/kaliv_dev_control/tier_a_authority.py` — module_alias: LEASE_SCHEMA, LeasedCatalogMaterializer, LeasedCommandRegistry, TIER_A_APPLICATION_ENVIRONMENT, TierAExecutionError, TierAExecutionLease, _canonical_directory, workspace_root_authority_sha256.
- `devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py` — module_alias: _canonical_directory, _regular_file_hash.
- `devcontrol/src/kaliv_dev_control/tier_a_plan.py` — module_alias: _canonical_directory, _regular_file_hash, _validated_application_env.

## Identity constraints

- `LeasedCatalogMaterializer`: `_tier_a_execution_core.LeasedCatalogMaterializer` → `tier_a_authority.LeasedCatalogMaterializer` → `tier_a_execution.LeasedCatalogMaterializer` → `kaliv_dev_control.LeasedCatalogMaterializer`.
- `LeasedCommandRegistry`: `_tier_a_execution_core.LeasedCommandRegistry` → `tier_a_authority.LeasedCommandRegistry` → `tier_a_execution.LeasedCommandRegistry` → `kaliv_dev_control.LeasedCommandRegistry`.
- `TIER_A_APPLICATION_ENVIRONMENT`: `_tier_a_environment.TIER_A_APPLICATION_ENVIRONMENT` → `_tier_a_execution_core.TIER_A_APPLICATION_ENVIRONMENT` → `tier_a_authority.TIER_A_APPLICATION_ENVIRONMENT` → `tier_a_execution.TIER_A_APPLICATION_ENVIRONMENT` → `kaliv_dev_control.TIER_A_APPLICATION_ENVIRONMENT`.
- `TierAExecutionError`: `_tier_a_execution_core.TierAExecutionError` → `tier_a_authority.TierAExecutionError` → `tier_a_execution.TierAExecutionError` → `kaliv_dev_control.TierAExecutionError`.
- `TierAExecutionLease`: `_tier_a_execution_core.TierAExecutionLease` → `tier_a_authority.TierAExecutionLease` → `tier_a_execution.TierAExecutionLease` → `kaliv_dev_control.TierAExecutionLease`.
- `workspace_root_authority_sha256`: `_tier_a_execution_core.workspace_root_authority_sha256` → `tier_a_authority.workspace_root_authority_sha256` → `tier_a_execution.workspace_root_authority_sha256` → `kaliv_dev_control.workspace_root_authority_sha256`.
- `_validated_application_env`: `_tier_a_environment._validated_application_env` → `_tier_a_execution_core._validated_application_env`.

A later split must keep every listed object identical by Python `is`, preserve the two intentional legacy-executor removals, update the exact bundle and regenerate the H10I inventory.
