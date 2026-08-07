# DC-L07 mutation results

**Status:** implementation mutations encoded; frozen exact-head execution pending.

## Observed red state

The seeded DC-L07 head `1d5aa5cd6abb43d782b7ce2a5a6f3731e8a728f8`
failed the repository coverage contract because seven DC-L07 test modules had
landed while `tests/workflow_test_coverage.py` still accepted only the twenty
modules through DC-L06. Build, vet, lint and the platform jobs reached that
boundary before the aggregate Python suite failed.

The contract now requires all twenty-seven modules through DC-L07.

## Load-bearing mutations

The following mutations are required to fail:

| Mutation | Detecting contract |
|---|---|
| Remove `sync_file(temporary)` after `prepare_temporary` | `test_temporary_preparer_metadata_is_synced_before_publication` and the source-shape assertion in `test_streaming_publication_h10g.py` |
| Allow metadata-sync failure to continue to `os.link` | `test_permission_metadata_sync_failure_is_fail_closed` |
| Reorder publication to link before metadata sync | the recorded `prepare`, `sync`, `link` event sequence |
| Reintroduce `tier_a_execution.py` or an executor symbol | the `DevControl DC-L07 non-execution boundary` workflow step and projected Slice 10B–10D tests |
| Accept a changed runtime source or staged destination | runtime-staging and runtime-closure hash/tamper tests |
| Accept an unmanifested closure file, case collision, traversal or hardlink alias | `test_slice10d_runtime_closure.py` |
| Permit the legacy Python version-check profile or extra runtime files | `test_slice10e_version_check_closure.py` |
| Remove one of the twenty-seven landed test modules from CI discovery | `tests/workflow_test_coverage.py` |

## Green evidence

Green evidence is valid only for the final frozen PR head. Workflow run IDs and
results are recorded in `exact-head-validation.md` after all four required
workflows finish successfully on that same commit.
