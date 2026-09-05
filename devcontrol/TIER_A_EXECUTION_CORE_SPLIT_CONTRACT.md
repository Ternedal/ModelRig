# Tier-A execution core split contract

Schema: `kaliv-tier-a-execution-core-split-contract/v10`

The historical core is now an import-only identity facade. It owns no executor,
process launcher, remote transport, credential loader or publication adapter.

Source blob: `4765ed7f05eba18d0ac96e052367455bad5af846`

| Extracted module | Re-exported identities |
|---|---|
| `kaliv_dev_control._tier_a_lease` | `LEASE_SCHEMA`, `TierAExecutionError`, `TierAExecutionLease`, `_HEX40`, `_HEX64`, `_TASK_ID`, `_canonical`, `_sha256`, `_task_sha` |
| `kaliv_dev_control._tier_a_path_authority` | `_canonical_directory`, `_has_symlink_component`, `_regular_file_hash`, `workspace_root_authority_sha256` |
| `kaliv_dev_control._tier_a_legacy_toolhost` | `_TIER_A_BUNDLE_FILES`, `tier_a_toolhost_sha256` |
| `kaliv_dev_control._tier_a_legacy_plan` | `PLAN_SCHEMA`, `_COMMAND_ID`, `TierALaunchPlan`, `build_tier_a_launch_plan` |
| `kaliv_dev_control._tier_a_materialization` | `_LeaseCapturingVerifier`, `LeasedCommandRegistry`, `LeasedCatalogMaterializer` |
| `kaliv_dev_control._tier_a_environment` | `TIER_A_APPLICATION_ENVIRONMENT`, `_validated_application_env` |

Forbidden executor identities remain absent: `_run_tier_a_launch_plan` and
`run_verified_tier_a_command`.
