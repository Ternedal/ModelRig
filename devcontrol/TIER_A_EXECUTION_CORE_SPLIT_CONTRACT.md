# Tier-A execution core split contract

Schema: `kaliv-tier-a-execution-core-split-contract/v6`

This is the authoritative review and migration contract for `devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py`. H10O moves physical-evidence capture, the leased registry and catalog materialization into `_tier_a_materialization.py`, while the legacy core imports and re-exports the exact same class objects.

The machine-readable contract is `devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json`.

## Proposed private modules

- `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` — Lease schema, shared validation, canonical lease identity and TierAExecutionLease.
- `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` — Reviewed Tier-A application environment policy and validation.
- `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` — Canonical directory, workspace authority and regular-file identity checks.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py` — Retained v2 bundle identity used only by the legacy core.
- `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` — Physical-evidence capture, leased registry and catalog materialization.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` — Retained v1 launch-plan model and plan construction.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py` — Retained non-capturing Windows executor that modern authority removes at import time.

## Completed module ownership

### `devcontrol/src/kaliv_dev_control/_tier_a_environment.py`

Completed slices: `H10K`.

| Symbol | Kind | Responsibility | Destination |
|---|---|---|---|
| `TIER_A_APPLICATION_ENVIRONMENT` | constant | environment_policy | `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` |
| `_validated_application_env` | function | environment_policy | `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` |

### `devcontrol/src/kaliv_dev_control/_tier_a_lease.py`

Completed slices: `H10L`, `H10M`.

| Symbol | Kind | Responsibility | Destination |
|---|---|---|---|
| `LEASE_SCHEMA` | constant | lease_model | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `_HEX40` | constant | schema_validation | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `_HEX64` | constant | schema_validation | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `_TASK_ID` | constant | schema_validation | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `TierAExecutionError` | class | lease_model | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `_canonical` | function | canonical_identity | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `_sha256` | function | canonical_identity | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `_task_sha` | function | canonical_identity | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |
| `TierAExecutionLease` | class | lease_model | `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` |

### `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py`

Completed slices: `H10N`.

| Symbol | Kind | Responsibility | Destination |
|---|---|---|---|
| `_has_symlink_component` | function | path_authority | `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` |
| `_canonical_directory` | function | path_authority | `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` |
| `workspace_root_authority_sha256` | function | path_authority | `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` |
| `_regular_file_hash` | function | path_authority | `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` |

### `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py`

Completed slices: `H10O`.

| Symbol | Kind | Responsibility | Destination |
|---|---|---|---|
| `_LeaseCapturingVerifier` | class | evidence_materialization | `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` |
| `LeasedCommandRegistry` | class | command_registry | `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` |
| `LeasedCatalogMaterializer` | class | evidence_materialization | `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` |

## Remaining symbols owned by the legacy core

| Symbol | Kind | Responsibility | Proposed destination |
|---|---|---|---|
| `PLAN_SCHEMA` | constant | legacy_plan_model | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` |
| `_COMMAND_ID` | constant | legacy_plan_model | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` |
| `_TIER_A_BUNDLE_FILES` | constant | legacy_toolhost_identity | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py` |
| `tier_a_toolhost_sha256` | function | legacy_toolhost_identity | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py` |
| `TierALaunchPlan` | class | legacy_plan_model | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` |
| `build_tier_a_launch_plan` | function | legacy_launch_planning | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` |
| `_run_tier_a_launch_plan` | function | legacy_execution | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py` |
| `run_verified_tier_a_command` | function | legacy_execution | `devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py` |

## Exact external core consumers

- `devcontrol/src/kaliv_dev_control/runtime_closure_builder.py` — direct; imports `LeasedCommandRegistry`, `workspace_root_authority_sha256`
- `devcontrol/src/kaliv_dev_control/runtime_closure_staging.py` — module_alias; references `LeasedCommandRegistry`
- `devcontrol/src/kaliv_dev_control/runtime_closure_verify.py` — module_alias; references `LeasedCommandRegistry`
- `devcontrol/src/kaliv_dev_control/tier_a_authority.py` — module_alias; references `LEASE_SCHEMA`, `LeasedCatalogMaterializer`, `LeasedCommandRegistry`, `TIER_A_APPLICATION_ENVIRONMENT`, `TierAExecutionError`, `TierAExecutionLease`, `_canonical_directory`, `workspace_root_authority_sha256`; removes `_run_tier_a_launch_plan`, `run_verified_tier_a_command`
- `devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py` — module_alias; references `_canonical_directory`, `_regular_file_hash`
- `devcontrol/src/kaliv_dev_control/tier_a_plan.py` — module_alias; references `_canonical_directory`, `_regular_file_hash`, `_validated_application_env`

## Public identity chains

- `LeasedCatalogMaterializer`: `_tier_a_execution_core.LeasedCatalogMaterializer` → `tier_a_authority.LeasedCatalogMaterializer` → `tier_a_execution.LeasedCatalogMaterializer` → `kaliv_dev_control.LeasedCatalogMaterializer`
- `LeasedCommandRegistry`: `_tier_a_execution_core.LeasedCommandRegistry` → `tier_a_authority.LeasedCommandRegistry` → `tier_a_execution.LeasedCommandRegistry` → `kaliv_dev_control.LeasedCommandRegistry`
- `TIER_A_APPLICATION_ENVIRONMENT`: `_tier_a_execution_core.TIER_A_APPLICATION_ENVIRONMENT` → `tier_a_authority.TIER_A_APPLICATION_ENVIRONMENT` → `tier_a_execution.TIER_A_APPLICATION_ENVIRONMENT` → `kaliv_dev_control.TIER_A_APPLICATION_ENVIRONMENT`
- `TierAExecutionError`: `_tier_a_execution_core.TierAExecutionError` → `tier_a_authority.TierAExecutionError` → `tier_a_execution.TierAExecutionError` → `kaliv_dev_control.TierAExecutionError`
- `TierAExecutionLease`: `_tier_a_execution_core.TierAExecutionLease` → `tier_a_authority.TierAExecutionLease` → `tier_a_execution.TierAExecutionLease` → `kaliv_dev_control.TierAExecutionLease`
- `workspace_root_authority_sha256`: `_tier_a_execution_core.workspace_root_authority_sha256` → `tier_a_authority.workspace_root_authority_sha256` → `tier_a_execution.workspace_root_authority_sha256` → `kaliv_dev_control.workspace_root_authority_sha256`

## Migration history

- **H10K**: `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` gained `TIER_A_APPLICATION_ENVIRONMENT`, `_validated_application_env`.
- **H10L**: `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` gained `TierAExecutionError`.
- **H10M**: `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` gained `LEASE_SCHEMA`, `_HEX40`, `_HEX64`, `_TASK_ID`, `_canonical`, `_sha256`, `_task_sha`, `TierAExecutionLease`.
- **H10N**: `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` gained `_has_symlink_component`, `_canonical_directory`, `workspace_root_authority_sha256`, `_regular_file_hash`.
- **H10O**: `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` gained `_LeaseCapturingVerifier`, `LeasedCommandRegistry`, `LeasedCatalogMaterializer`.

H10O changes the exact Tier-A source bundle bytes and therefore the toolhost digest. Every earlier physical I0b report remains stale; no replacement physical evidence is created by this contract.
