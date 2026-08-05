# Tier-A execution core split contract

Schema: `kaliv-tier-a-execution-core-split-contract/v3`

This is the authoritative review and migration contract for `devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py`. H10J froze the original ownership surface; H10K extracted the environment policy; H10L now extracts the shared error identity and removes the temporary reverse dependency from the environment module.

The machine-readable contract is `devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json`.

## Proposed private modules

- `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` — Lease schema, shared validation, canonical lease identity and TierAExecutionLease.
- `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` — Reviewed Tier-A application environment policy and validation.
- `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` — Canonical directory, workspace authority and regular-file identity checks.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py` — Retained v2 bundle identity used only by the legacy core.
- `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` — Physical-evidence capture, leased registry and catalog materialization.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` — Retained v1 launch-plan model and plan construction.
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py` — Retained non-capturing Windows executor that modern authority removes at import time.

## Remaining symbols owned by the legacy core

| Symbol | Kind | Responsibility | Proposed destination |
|---|---|---|---|
| `LEASE_SCHEMA` | constant | lease model | `_tier_a_lease.py` |
| `PLAN_SCHEMA` | constant | legacy plan model | `_tier_a_legacy_plan.py` |
| `_HEX40` | constant | schema validation | `_tier_a_lease.py` |
| `_HEX64` | constant | schema validation | `_tier_a_lease.py` |
| `_TASK_ID` | constant | schema validation | `_tier_a_lease.py` |
| `_COMMAND_ID` | constant | legacy plan model | `_tier_a_legacy_plan.py` |
| `_TIER_A_BUNDLE_FILES` | constant | legacy toolhost identity | `_tier_a_legacy_toolhost.py` |
| `_canonical` | function | canonical identity | `_tier_a_lease.py` |
| `_sha256` | function | canonical identity | `_tier_a_lease.py` |
| `_task_sha` | function | canonical identity | `_tier_a_lease.py` |
| `_has_symlink_component` | function | path authority | `_tier_a_path_authority.py` |
| `_canonical_directory` | function | path authority | `_tier_a_path_authority.py` |
| `workspace_root_authority_sha256` | function | path authority | `_tier_a_path_authority.py` |
| `tier_a_toolhost_sha256` | function | legacy toolhost identity | `_tier_a_legacy_toolhost.py` |
| `TierAExecutionLease` | class | lease model | `_tier_a_lease.py` |
| `_LeaseCapturingVerifier` | class | evidence materialization | `_tier_a_materialization.py` |
| `LeasedCommandRegistry` | class | command registry | `_tier_a_materialization.py` |
| `LeasedCatalogMaterializer` | class | evidence materialization | `_tier_a_materialization.py` |
| `TierALaunchPlan` | class | legacy plan model | `_tier_a_legacy_plan.py` |
| `_regular_file_hash` | function | path authority | `_tier_a_path_authority.py` |
| `build_tier_a_launch_plan` | function | legacy launch planning | `_tier_a_legacy_plan.py` |
| `_run_tier_a_launch_plan` | function | legacy execution | `_tier_a_legacy_runner.py` |
| `run_verified_tier_a_command` | function | legacy execution | `_tier_a_legacy_runner.py` |

## Completed identity-preserving extractions

### H10K — `devcontrol/src/kaliv_dev_control/_tier_a_environment.py`

Exact current Git blob: `68cee74aa519e41cb9b8e3a5e74e3dbb90a6d78d`

The legacy core imports and re-exports the exact environment mapping and validator. H10L replaces the earlier lazy core lookup with a direct dependency on `_tier_a_lease.py`.

| Symbol | Kind | Responsibility | Extracted destination |
|---|---|---|---|
| `TIER_A_APPLICATION_ENVIRONMENT` | constant | environment policy | `_tier_a_environment.py` |
| `_validated_application_env` | function | environment policy | `_tier_a_environment.py` |

### H10L — `devcontrol/src/kaliv_dev_control/_tier_a_lease.py`

Exact current Git blob: `1f4a6eac5b9f0874bbb12897f690f8ae2ee9efe1`

The legacy core imports and re-exports the exact error class. `_tier_a_environment.py` imports the same class directly from this module, so the H10K module no longer imports the legacy core.

| Symbol | Kind | Responsibility | Extracted destination |
|---|---|---|---|
| `TierAExecutionError` | class | lease model | `_tier_a_lease.py` |

## Exact current core consumers

- `devcontrol/src/kaliv_dev_control/runtime_closure_builder.py` — direct imports: `LeasedCommandRegistry`, `workspace_root_authority_sha256`.
- `devcontrol/src/kaliv_dev_control/runtime_closure_staging.py` — module alias `_core`; attributes: `LeasedCommandRegistry`.
- `devcontrol/src/kaliv_dev_control/runtime_closure_verify.py` — module alias `_core`; attributes: `LeasedCommandRegistry`.
- `devcontrol/src/kaliv_dev_control/tier_a_authority.py` — module alias `_core`; attributes: `LEASE_SCHEMA`, `LeasedCatalogMaterializer`, `LeasedCommandRegistry`, `TIER_A_APPLICATION_ENVIRONMENT`, `TierAExecutionError`, `TierAExecutionLease`, `_canonical_directory`, `workspace_root_authority_sha256`; dynamic removals: `_run_tier_a_launch_plan`, `run_verified_tier_a_command`.
- `devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py` — module alias `_core`; attributes: `_canonical_directory`, `_regular_file_hash`.
- `devcontrol/src/kaliv_dev_control/tier_a_plan.py` — module alias `_core`; attributes: `_canonical_directory`, `_regular_file_hash`, `_validated_application_env`.

## Public object identities preserved

- `LeasedCatalogMaterializer`: `_tier_a_execution_core.LeasedCatalogMaterializer` → `tier_a_authority.LeasedCatalogMaterializer` → `tier_a_execution.LeasedCatalogMaterializer` → `kaliv_dev_control.LeasedCatalogMaterializer`.
- `LeasedCommandRegistry`: `_tier_a_execution_core.LeasedCommandRegistry` → `tier_a_authority.LeasedCommandRegistry` → `tier_a_execution.LeasedCommandRegistry` → `kaliv_dev_control.LeasedCommandRegistry`.
- `TIER_A_APPLICATION_ENVIRONMENT`: `_tier_a_execution_core.TIER_A_APPLICATION_ENVIRONMENT` → `tier_a_authority.TIER_A_APPLICATION_ENVIRONMENT` → `tier_a_execution.TIER_A_APPLICATION_ENVIRONMENT` → `kaliv_dev_control.TIER_A_APPLICATION_ENVIRONMENT`.
- `TierAExecutionError`: `_tier_a_execution_core.TierAExecutionError` → `tier_a_authority.TierAExecutionError` → `tier_a_execution.TierAExecutionError` → `kaliv_dev_control.TierAExecutionError`.
- `TierAExecutionLease`: `_tier_a_execution_core.TierAExecutionLease` → `tier_a_authority.TierAExecutionLease` → `tier_a_execution.TierAExecutionLease` → `kaliv_dev_control.TierAExecutionLease`.
- `workspace_root_authority_sha256`: `_tier_a_execution_core.workspace_root_authority_sha256` → `tier_a_authority.workspace_root_authority_sha256` → `tier_a_execution.workspace_root_authority_sha256` → `kaliv_dev_control.workspace_root_authority_sha256`.

## H10L constraints and evidence

- Only `TierAExecutionError` moved in H10L.
- `_tier_a_execution_core.py` imports and re-exports that exact class object; all supported public paths retain object identity.
- `_tier_a_environment.py` imports the error directly from `_tier_a_lease.py`; it no longer imports `_tier_a_execution_core.py` lazily or otherwise.
- `_tier_a_lease.py` is included exactly once in `_TIER_A_BUNDLE_FILES` before `_tier_a_environment.py` and the legacy core.
- Moving authority-bearing source intentionally changes the Tier-A toolhost digest. All earlier physical I0b evidence remains stale; no replacement evidence is manufactured.
- H10L adds no credential, signer, Git remote, network, publication, pull-request, merge, deployment or production authority.
