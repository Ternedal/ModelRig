# DC-L08 mutation results

**Status:** implementation mutations encoded; frozen exact-head execution pending.

## Observed red states

The implementation sequence proved three integration failures before the current
head:

1. the generic Windows bounded-subprocess contract is intentionally fail-closed
   and is not owned by DC-L08;
2. the locked executor source referenced the later `ExecutableVerifier` protocol,
   which is absent from the landed DC-L07 catalog surface; and
3. static `from app.windows_job` imports violated the dormant-foundation boundary,
   while the later source fixture also used an environment key outside the landed
   reviewed positive list.

The slice now uses only the owned closure-bound Windows contract, projects the
verifier annotation to `Any`, late-binds the same approved native modules and
projects the test fixture in memory to the already reviewed DC-L08 environment.

## Load-bearing mutations

The following mutations are required to fail:

| Mutation | Detecting contract |
|---|---|
| Export either executor function from package root, `tier_a_authority` or `_tier_a_execution_core` | `test_public_and_authority_surfaces_do_not_export_executor` and the DC-L08 workflow boundary |
| Add the final `tier_a_execution.py` facade or command-receipt module | import-spec assertions in H10R and the workflow boundary |
| Reintroduce an import of the unlanded `ExecutableVerifier` protocol | Python lint/import gates and the native Windows executor import contract |
| Reintroduce static `from app.windows_*` imports | the dormant foundation import contract |
| Remove the signed-closure or verifier runtime type checks | real-Windows closure-bound execution contract and source-boundary assertions |
| Permit an unverified launch plan | `_run_tier_a_launch_plan` fail-closed plan validation |
| Remove executable, cwd, workspace, toolhost or staged-closure revalidation | native Windows tamper and runtime-lifetime tests |
| Release the runtime guard before Job Object shutdown is proven | concurrent AppContainer/host mutation contract |
| Continue after Job Object close or termination authority is lost | timeout and cleanup failure contracts |
| Capture more than the signed output budget | burst-output bounded capture contract and result-model tests |
| Remove `_tier_a_legacy_runner.py` or `tier_a_execution_v3.py` from the v6 bundle | H10R and Slice 9 bundle identity tests |
| Activate generic bounded-subprocess or command-receipt Windows contracts | workflow coverage contract, which keeps those authorities deferred |
| Remove one of the twenty-eight landed test modules from CI discovery | `tests/workflow_test_coverage.py` |

## Green evidence

Green evidence is valid only for the final frozen pull-request head. Workflow run
IDs and results are recorded in the pull-request body after all four required
workflows finish successfully on that same commit.
