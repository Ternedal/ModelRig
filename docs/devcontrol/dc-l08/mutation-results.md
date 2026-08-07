# DC-L08 mutation results

**Status:** implementation mutations encoded; frozen exact-head execution pending.

## Observed red states

The implementation sequence proved five integration failures before the current
head:

1. the generic Windows bounded-subprocess contract is intentionally fail-closed
   and is not owned by DC-L08;
2. the locked executor source referenced the later `ExecutableVerifier` protocol,
   which is absent from the landed DC-L07 catalog surface;
3. static `from app.windows_job` imports violated the dormant-foundation boundary,
   while the later source fixture also used an environment key outside the landed
   reviewed positive list;
4. the later Windows fixture's file-discovery assumptions did not match the
   independently landed DC-L04 verifier boundary, yielding zero trusted candidates
   before execution was reached; and
5. the platform-neutral signed plan environment was passed wholesale to the
   Windows application-value boundary, which correctly rejected `LANG`.

The slice now uses only the owned closure-bound Windows contract, projects the
verifier annotation to `Any`, late-binds the same approved native modules,
projects the test environment to the reviewed value and uses a test-only
`WindowsPhysicalIsolationVerifier` subclass to supply the already signed report
candidate. Base signature, authority binding, probe and freshness verification
still run. Production verifier code is unchanged.

Both private executors now keep all seven values in the signed plan but forward
only the intersection with the Windows worker application allowlist. The five
portable values omitted at launch are accepted only at their exact signed
constants; unknown keys or altered values fail before ACL provisioning or spawn.

## Load-bearing mutations

The following mutations are required to fail:

| Mutation | Detecting contract |
|---|---|
| Export either executor function from package root, `tier_a_authority` or `_tier_a_execution_core` | `test_public_and_authority_surfaces_do_not_export_executor` and the DC-L08 workflow boundary |
| Add the final `tier_a_execution.py` facade or command-receipt module | import-spec assertions in H10R and the workflow boundary |
| Reintroduce an import of the unlanded `ExecutableVerifier` protocol | Python lint/import gates and the native Windows executor import contract |
| Reintroduce static `from app.windows_*` imports | the dormant foundation import contract |
| Pass the full signed environment directly to the Windows application boundary | native Windows execution rejects portable-only keys such as `LANG` |
| Silently omit an unknown or altered plan environment value | the executor's fail-closed signed-to-Windows projection |
| Remove the signed-closure or verifier runtime type checks | real-Windows closure-bound execution contract and source-boundary assertions |
| Permit an unverified launch plan | `_run_tier_a_launch_plan` fail-closed plan validation |
| Remove executable, cwd, workspace, toolhost or staged-closure revalidation | native Windows tamper and runtime-lifetime tests |
| Release the runtime guard before Job Object shutdown is proven | concurrent AppContainer/host mutation contract |
| Continue after Job Object close or termination authority is lost | timeout and cleanup failure contracts |
| Capture more than the signed output budget | burst-output bounded capture contract and result-model tests |
| Bypass base physical signature, binding, probe or freshness verification in the fixture subclass | the leased materializer and verifier base-class execution path |
| Remove `_tier_a_legacy_runner.py` or `tier_a_execution_v3.py` from the v6 bundle | H10R and Slice 9 bundle identity tests |
| Activate generic bounded-subprocess or command-receipt Windows contracts | workflow coverage contract, which keeps those authorities deferred |
| Remove one of the twenty-eight landed test modules from CI discovery | `tests/workflow_test_coverage.py` |

## Green evidence

Green evidence is valid only for the final frozen pull-request head. Workflow run
IDs and results are recorded in the pull-request body after all four required
workflows finish successfully on that same commit.
