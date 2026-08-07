# DC-L06 mutation results

Status: **source mutations identified; exact-head execution pending**

Load-bearing mutations for this slice:

1. Import the retained legacy runner from `_tier_a_execution_core.py`: the
   obsolete-executor absence tests fail.
2. Add `tier_a_execution.py`, v2/v3 plan, result, runtime-closure or trusted-Git
   paths to the stage-local bundle: the projection tests fail.
3. Change one of the two literal bundle tuples without changing the other:
   import fails closed and bundle parity tests fail.
4. Remove one focused module from the bundle or place it after the core:
   extraction-order tests fail.
5. Reintroduce package/future-facade identity assertions into a DC-L06 test:
   import discovery fails because those modules are intentionally absent.
6. Accept an unknown execution-lease or launch-plan field: mapping reload tests
   and schema parity fail.
7. Permit an unreviewed environment key/value or a case-folded duplicate:
   environment validation tests fail.
8. Accept a relative, missing or symlinked workspace/file path: path-authority
   tests fail.
9. Change a toolhost source file or executable after evidence issuance:
   launch-plan construction rejects.
10. Rebind a leased registry to another task: registry resolution rejects.
11. Allow a failed physical probe to issue a lease: materialization tests fail.
12. Add process, network, Git, credential, publication or remote-authority
    imports to the focused modules: boundary AST tests fail.

The final candidate must run these tests together with the full portable
repository suite on the exact pull-request head.
