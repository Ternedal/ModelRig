# DC-L07 mutation results

**Status:** implementation mutations encoded; frozen exact-head execution pending.

## Observed red state

The seeded DC-L07 head `1d5aa5cd6abb43d782b7ce2a5a6f3731e8a728f8`
failed the repository coverage contract because seven DC-L07 test modules had
landed while `tests/workflow_test_coverage.py` still accepted only the twenty
modules through DC-L06.

The later exact head `0ab93d96644d63e6790e4e281a89343e016562f6`
then proved two additional compatibility failures:

- DC-L06 tests still imported the retained v1 `TierALaunchPlan` identity from
  `tier_a_authority`; and
- the foundation boundary rejected a literal future-slice-style
  `from .tier_a_...` import in `runtime_staging.py`.

A subsequent source review found that the unchanged DC-L06 schema test also
required v2/v3/result schemas to remain absent. DC-L07 necessarily lands those
schemas, so the test is now an explicit projection that preserves v1 parity and
adds v3 plan/result parity without importing an executor.

The coverage contract now requires all twenty-seven modules through DC-L07.

## Load-bearing mutations

The following mutations are required to fail:

| Mutation | Detecting contract |
|---|---|
| Remove `sync_file(temporary)` after `prepare_temporary` | `test_temporary_preparer_metadata_is_synced_before_publication` and the source-shape assertion in `test_streaming_publication_h10g.py` |
| Allow metadata-sync failure to continue to `os.link` | `test_permission_metadata_sync_failure_is_fail_closed` |
| Reorder publication to link before metadata sync | the recorded `prepare`, `sync`, `link` event sequence |
| Require a write-open descriptor for repeated Unix closure staging | repeated staging assertion in `test_slice10e_version_check_closure.py` |
| Remove the retained v1 launch-plan compatibility aliases | v1 parity in `test_slice9.py` and `test_slice9_schemas.py` |
| Remove or weaken v3 plan/result schema parity | `test_slice9_schemas.py` and the dedicated plan/result tests |
| Reintroduce `tier_a_execution.py` or an executor symbol | the `DevControl DC-L07 non-execution boundary` workflow step and projected Slice 10B–10D tests |
| Accept a changed runtime source or staged destination | runtime-staging and runtime-closure hash/tamper tests |
| Accept an unmanifested closure file, case collision, traversal or hardlink alias | `test_slice10d_runtime_closure.py` |
| Permit the legacy Python version-check profile or extra runtime files | `test_slice10e_version_check_closure.py` |
| Remove one of the twenty-seven landed test modules from CI discovery | `tests/workflow_test_coverage.py` |

## Green evidence

Green evidence is valid only for the final frozen PR head. Workflow run IDs and
results are recorded in the pull-request body after all four required workflows
finish successfully on that same commit.
