# DC-L08 mutation results

**Status:** implementation mutations encoded; frozen exact-head execution pending.

## Load-bearing mutations

The following mutations are required to fail:

| Mutation | Detecting contract |
|---|---|
| Export either executor function from package root, `tier_a_authority` or `_tier_a_execution_core` | `test_public_and_authority_surfaces_do_not_export_executor` and the DC-L08 workflow boundary |
| Add the final `tier_a_execution.py` facade or command-receipt module | import-spec assertions in H10R and the workflow boundary |
| Remove the signed-closure or verifier type checks | real-Windows closure-bound execution contract and source-boundary assertions |
| Permit an unverified launch plan | `_run_tier_a_launch_plan` fail-closed plan validation |
| Remove executable, cwd, workspace, toolhost or staged-closure revalidation | native Windows tamper and runtime-lifetime tests |
| Release the runtime guard before Job Object shutdown is proven | concurrent AppContainer/host mutation contract |
| Continue after Job Object close or termination authority is lost | timeout and cleanup failure contracts |
| Capture more than the signed output budget | burst-output bounded capture contract and result-model tests |
| Remove `_tier_a_legacy_runner.py` or `tier_a_execution_v3.py` from the v6 bundle | H10R and Slice 9 bundle identity tests |
| Activate `windows_tier_a_receipt_contract.py` | workflow coverage contract, which keeps receipts deferred to DC-L09 |
| Remove one of the twenty-eight landed test modules from CI discovery | `tests/workflow_test_coverage.py` |

## Green evidence

Green evidence is valid only for the final frozen pull-request head. Workflow run
IDs and results are recorded in the pull-request body after all four required
workflows finish successfully on that same commit.
