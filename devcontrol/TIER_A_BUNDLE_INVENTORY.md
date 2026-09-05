# Tier-A authority bundle inventory

Schema: `kaliv-tier-a-bundle-inventory/v1`

This report is generated from the exact `_TIER_A_BUNDLE_FILES` tuple in `devcontrol/src/kaliv_dev_control/tier_a_authority.py`. It records measurements only; it does not enforce size, line-count, complexity or fan-out thresholds.

## Totals

| Files | Bytes | Physical lines | Top-level classes | Top-level functions | Local import edges |
|---:|---:|---:|---:|---:|---:|
| 50 | 634397 | 17231 | 152 | 191 | 163 |

## Per-file measurements

Local import fan-out counts distinct direct imports that resolve to another file in the exact bundle. Responsibility signals are deterministic syntactic indicators for split planning, not claims that every listed implementation is equivalent.

| Path | Bytes | Lines | Classes | Functions | Fan-out | Responsibility signals |
|---|---:|---:|---:|---:|---:|---|
| `worker/app/__init__.py` | 0 | 0 | 0 | 0 | 0 | — |
| `worker/app/windows_job.py` | 13288 | 365 | 8 | 5 | 0 | — |
| `worker/app/windows_restricted.py` | 29682 | 859 | 13 | 8 | 1 | canonicalization, hashing, path_validation |
| `worker/app/windows_capture.py` | 22208 | 591 | 7 | 4 | 2 | canonicalization, hashing, path_validation |
| `worker/app/windows_runtime_guard.py` | 26116 | 713 | 9 | 0 | 2 | canonicalization, hashing, path_validation |
| `worker/app/windows_tier_a.py` | 8063 | 256 | 0 | 3 | 3 | canonicalization |
| `devcontrol/src/kaliv_dev_control/__init__.py` | 6207 | 232 | 0 | 0 | 21 | publication |
| `devcontrol/src/kaliv_dev_control/bounded_subprocess.py` | 22032 | 656 | 4 | 18 | 0 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/campaign.py` | 12599 | 356 | 4 | 3 | 1 | canonicalization, hashing |
| `devcontrol/src/kaliv_dev_control/catalog.py` | 27729 | 548 | 13 | 7 | 2 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/commands.py` | 33779 | 925 | 7 | 1 | 2 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/contract.py` | 9976 | 281 | 5 | 4 | 0 | canonicalization, path_validation |
| `devcontrol/src/kaliv_dev_control/durable_publication.py` | 12352 | 346 | 1 | 14 | 0 | path_validation, publication |
| `devcontrol/src/kaliv_dev_control/evidence.py` | 1890 | 67 | 1 | 1 | 2 | canonicalization, hashing |
| `devcontrol/src/kaliv_dev_control/files.py` | 6189 | 173 | 3 | 0 | 1 | path_validation |
| `devcontrol/src/kaliv_dev_control/github_read.py` | 35225 | 1036 | 8 | 10 | 1 | canonicalization, hashing, publication |
| `devcontrol/src/kaliv_dev_control/patch.py` | 15716 | 490 | 4 | 0 | 4 | canonicalization, hashing, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/physical_isolation.py` | 33478 | 879 | 7 | 15 | 2 | canonicalization, hashing, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/policy.py` | 3600 | 96 | 3 | 0 | 1 | — |
| `devcontrol/src/kaliv_dev_control/proposal.py` | 8516 | 229 | 3 | 2 | 3 | canonicalization, hashing, publication |
| `devcontrol/src/kaliv_dev_control/review.py` | 15996 | 432 | 7 | 4 | 3 | canonicalization, hashing |
| `devcontrol/src/kaliv_dev_control/runtime_staging.py` | 23361 | 617 | 3 | 12 | 7 | canonicalization, hashing, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/streaming_publication.py` | 4047 | 119 | 1 | 1 | 1 | hashing, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/_runtime_closure_common.py` | 9778 | 297 | 1 | 16 | 4 | canonicalization, hashing, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/runtime_closure_model.py` | 12279 | 320 | 4 | 0 | 1 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/runtime_closure_verify.py` | 6605 | 156 | 1 | 0 | 5 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/runtime_closure_staging.py` | 15700 | 388 | 2 | 0 | 7 | canonicalization, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/runtime_closure.py` | 798 | 25 | 0 | 0 | 4 | — |
| `devcontrol/src/kaliv_dev_control/runtime_closure_builder.py` | 8069 | 208 | 1 | 1 | 5 | canonicalization, path_validation |
| `devcontrol/src/kaliv_dev_control/store.py` | 18791 | 486 | 2 | 3 | 2 | canonicalization, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/tier_a_authority.py` | 8403 | 205 | 0 | 8 | 3 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/tier_a_plan.py` | 20389 | 510 | 1 | 3 | 6 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/tier_a_result.py` | 11791 | 310 | 3 | 3 | 0 | canonicalization, hashing |
| `devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py` | 13076 | 343 | 1 | 2 | 9 | canonicalization, path_validation |
| `devcontrol/src/kaliv_dev_control/trusted_git_runtime_model.py` | 19605 | 530 | 5 | 13 | 0 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/trusted_git_runtime_staging.py` | 20064 | 529 | 2 | 8 | 2 | canonicalization, path_validation, publication |
| `devcontrol/src/kaliv_dev_control/trusted_git_runtime_h4.py` | 3361 | 100 | 0 | 2 | 2 | path_validation |
| `devcontrol/src/kaliv_dev_control/trusted_git_runtime_runner.py` | 10206 | 288 | 1 | 0 | 3 | path_validation |
| `devcontrol/src/kaliv_dev_control/trusted_git_runtime.py` | 3750 | 113 | 0 | 1 | 3 | path_validation |
| `devcontrol/src/kaliv_dev_control/tier_a_command_receipt.py` | 22349 | 612 | 4 | 7 | 6 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/tier_a_execution.py` | 2041 | 68 | 0 | 0 | 5 | — |
| `devcontrol/src/kaliv_dev_control/_tier_a_lease.py` | 9954 | 260 | 2 | 3 | 3 | canonicalization, hashing |
| `devcontrol/src/kaliv_dev_control/_tier_a_environment.py` | 2213 | 64 | 0 | 1 | 1 | canonicalization |
| `devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py` | 1694 | 53 | 0 | 4 | 1 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/_tier_a_materialization.py` | 7647 | 204 | 3 | 0 | 6 | path_validation |
| `devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py` | 4261 | 89 | 0 | 1 | 2 | canonicalization, hashing, path_validation |
| `devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py` | 11218 | 284 | 1 | 1 | 7 | canonicalization, path_validation |
| `devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py` | 7032 | 189 | 0 | 2 | 9 | canonicalization, path_validation |
| `devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py` | 1580 | 57 | 0 | 0 | 6 | canonicalization, path_validation |
| `devcontrol/src/kaliv_dev_control/workspace.py` | 9694 | 277 | 7 | 0 | 2 | path_validation, publication |

## Duplicated responsibility signals

| Responsibility | Files with signal |
|---|---:|
| Canonicalization | 36 |
| Hashing | 26 |
| Path Validation | 35 |
| Publication | 13 |

## Signal rules

- **Canonicalization:** canonical-named definitions/references or `json.dumps` calls that explicitly request sorted keys or compact separators.
- **Hashing:** `hashlib` use or cryptographic hash constructor calls.
- **Path validation:** link/junction/symlink, relative-path, canonical-directory or physical resolution checks.
- **Publication:** shared publication primitives, temporary-file/link/replace/fsync calls, or publish/stager/write definitions.

Run `python scripts/tier_a_bundle_inventory.py --format json` for the full machine-readable inventory, including direct local-import targets and category-to-file mappings. Run `python scripts/tier_a_bundle_inventory.py --check` to verify this report and its cryptographic lock.
