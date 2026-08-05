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
Windows fails closed until the native Job Object boundary lands in DC-L05; DC-L01
does not import that future product module.

## Source projection decisions

Nine source paths are copied byte-identically from the locked source head.
Eleven source-derived paths are deliberately projected:

- `bounded_subprocess.py`: replaces process-group-only cleanup and the DC-L05
  Windows import with Linux subreaper containment and Windows fail-closed behavior;
- `commands.py`: includes ignored artifacts in clean-state evidence and uses
  `git clean -fdx` when resetting a mutated workspace;
- `workspace.py`: removes the DC-L09 `trusted_git_runtime` import and replaces it
  with an implementation-free injected protocol;
- `test_bounded_subprocess.py`: removes the deferred DC-L09 runner import and
  proves termination of a descendant that calls `start_new_session=True`;
- `test_foundation.py`: tests the workspace seam, future/product imports and the
  ignored-artifact mutation gate;
- `__init__.py`: exports only DC-L01 symbols;
- `__main__.py`: exposes only task validation and path checking;
- `pyproject.toml`: has no runtime dependency; cryptography remains deferred;
- `README.md`: describes only landed authority;
- `_tests.yml`: adds only the DC-L01 lint and unittest gate; and
- `workflow_test_coverage.py`: proves the three DC-L01 tests are reached by CI.

## Required gates

1. Changed paths equal `exact-path-allowlist.json`.
2. All exact copies match their recorded source blobs.
3. Projected files contain only the deltas recorded in `source-provenance.json`.
4. The package imports without a future-slice or product module.
5. The default command registry is empty.
6. Missing or wrong workspace Git seams fail closed.
7. Wrong SHA, dirty or ignored workspace, path escape, protected path, budget
   overflow, malformed patch, timeout and output overflow all fail closed.
8. Linux containment terminates descendants that escape into new sessions;
   unsupported platforms fail closed.
9. Repository CI, CodeQL, diagnostics and independent exact-head review pass.

## Definition of done

The PR may merge only from a fresh current-main base, with every check green on
the exact head and an independent no-findings/approval verdict bound to that
head. The merge remains a human action.
