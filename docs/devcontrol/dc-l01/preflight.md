# DC-L01 preflight — task, scope, workspace and bounded command foundation

**Slice:** DC-L01  
**Base:** `main @ 4c7f4c7c31d97faea98147ebdfa97d0479abbdc1`  
**Source reference:** PR #338 at `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Depends on:** landed DC-L00 (PR #352)  
**Status:** implementation candidate; exact-head CI and independent review required before merge

## Purpose

Land only the dependency-minimal primitives required to describe and constrain a
development task: immutable contract, path/budget policy, bounded file access,
fail-closed patching, deterministic receipts, fixed command templates, bounded
subprocess evidence and exact-SHA workspace verification.

## Authority boundary

DC-L01 deliberately has:

- no command registered by default;
- no command catalog or executable selection;
- no concrete Git runner;
- no remote Git verbs, network transport, GitHub API or credential mechanism;
- no campaign, reviewer, publisher, physical-evidence or Tier-A execution layer;
- no product import or route registration; and
- no merge, release, deployment or activation authority.

`WorkspaceManager` accepts only an injected structural `WorkspaceGitRunner` seam.
The slice itself cannot instantiate Git authority. Its fixed calls are limited to
local worktree add/remove, exact `rev-parse HEAD`, and clean-status verification.

Bounded command execution is concrete only on Linux. A subreaper supervisor
tracks and kills descendants even when they create a new session/process group.
The caller records termination proof only after the supervisor exits with its
positive quiescence acknowledgement; an unacknowledged or fallback path fails
without returning a result. Windows fails closed until the native Job Object
boundary lands in DC-L05; DC-L01 does not import that future product module.

Registered commands never execute in the source checkout. The executor first
verifies the source is at the exact task HEAD with no staged, unstaged, untracked
or ignored state, creates a temporary Git bundle and clones a bounded independent
repository at that exact SHA. Before command execution it removes the origin and
bundle, uses no object alternates, isolates HOME/XDG/TMP/Git configuration and
rejects any source-path or Git-context disclosure. The sandbox worktree and its
complete bounded `.git` metadata are fingerprinted. Every sandbox is destroyed,
and the source repository is re-verified unchanged before evidence can return.

## Source projection decisions

Six source paths are copied byte-identically from the locked source head.
Fourteen source-derived paths are deliberately projected:

- `bounded_subprocess.py`: replaces process-group-only cleanup and the DC-L05
  Windows import with Linux subreaper containment, positive quiescence
  acknowledgement and Windows fail-closed behavior;
- `commands.py`: freezes mutable argv inputs, verifies exact task HEAD and clean
  source state, executes in a bounded independent bundle-cloned repository,
  removes origin/bundle before execution, uses no alternates, isolates command
  environment and Git config, fingerprints worktree plus complete sandbox Git
  metadata, destroys the sandbox and re-verifies the source before evidence;
- `contract.py`: rejects empty, dot and parent raw path segments before
  `PurePosixPath` can normalize ambiguous task authority;
- `patch.py`: verifies exact task HEAD, includes ignored artifacts in post-apply
  cleanliness evidence, removes nested Git repositories with `git clean -ffdx`
  and verifies staged/unstaged/untracked/ignored state is empty after reset;
- `workspace.py`: removes the DC-L09 `trusted_git_runtime` import, replaces it
  with an implementation-free injected protocol and strips inherited `GIT_*`
  context from generic subprocess execution;
- `test_bounded_subprocess.py`: removes the deferred DC-L09 runner import, proves
  escaped-session containment and negative acknowledgement behavior, and
  exercises nested-Git handling, oversized snapshot failure, forbidden template
  environment and inherited `GIT_DIR` regressions;
- `test_foundation.py`: tests the workspace seam, future/product imports,
  immutable command argv, exact command/patch HEAD binding, pre-staged command
  rejection, ambiguous raw path rejection and executable ignored-artifact
  disposal for command plus ignored-artifact reset for patch;
- `test_slice2.py`: adds executable independent-sandbox regressions proving that
  no source path, metadata backup, bundle, remote or alternate is visible and
  that sandbox-only config/hook mutations invalidate evidence while source
  metadata and status remain unchanged;
- `__init__.py`: exports only DC-L01 symbols;
- `__main__.py`: exposes only task validation and path checking;
- `pyproject.toml`: has no runtime dependency; cryptography remains deferred;
- `README.md`: describes only landed authority;
- `_tests.yml`: adds the DC-L01 lint/unittest gate and captures verbose failure
  output in the existing failed-test artifact; and
- `workflow_test_coverage.py`: proves the three DC-L01 tests are reached by CI.

## Required gates

1. Changed paths equal `exact-path-allowlist.json`.
2. All exact copies match their recorded source blobs.
3. Projected files contain only the deltas recorded in `source-provenance.json`.
4. The package imports without a future-slice or product module.
5. The default command registry is empty and registered argv cannot be mutated
   after template construction.
6. Missing or wrong workspace Git seams fail closed.
7. Command and patch receipts are bound to the exact task base SHA; a mismatched
   workspace HEAD returns no passing receipt.
8. Staged, unstaged, untracked or ignored source state is rejected before a
   command starts.
9. Commands execute only inside an independent exact-HEAD sandbox with no source
   path, bundle, remote, metadata backup or object alternate visible.
10. Sandbox worktree and complete bounded Git metadata jointly determine command
    receipt state; metadata-only mutations invalidate positive evidence.
11. Every sandbox is physically destroyed and the source is re-verified exact and
    clean before command evidence returns.
12. Ambiguous raw task paths are rejected before filesystem path normalization.
13. Path escape, protected path, budget overflow, malformed patch, timeout and
    output overflow all fail closed.
14. Linux containment terminates descendants that escape into new sessions and
    emits termination proof only after positive supervisor acknowledgement;
    unsupported platforms and unacknowledged/fallback termination fail closed.
15. Ignored artifacts and nested Git repositories cannot coexist with positive
    command evidence because they mutate and are destroyed with the sandbox.
16. Ignored artifacts and nested Git repositories cannot coexist with positive
    patch evidence and are physically removed by double-force patch reset.
17. Patch reset verifies exact HEAD and zero staged, unstaged, untracked and
    ignored residual state before it can be claimed successful.
18. Repository CI, CodeQL, diagnostics and independent exact-head review pass.

## Definition of done

The PR may merge only from a fresh current-main base, with every check green on
the exact head and an independent no-findings/approval verdict bound to that
head. The merge remains a human action.
