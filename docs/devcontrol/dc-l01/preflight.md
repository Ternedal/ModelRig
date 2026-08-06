# DC-L01 preflight — task, scope, workspace and bounded command foundation

**Slice:** DC-L01  
**Original branch base:** `main @ 4c7f4c7c31d97faea98147ebdfa97d0479abbdc1`  
**Synchronized current main:** `6644512e1d442349f263ffc157fe63e18886507f`  
**Source reference:** PR #338 at `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Depends on:** landed DC-L00 (PR #352)  
**Status:** exact-head validation and independent review required before merge

## Purpose

Land only dependency-minimal primitives for immutable task contracts, path and
budget policy, bounded file access, fail-closed patching, deterministic receipts,
fixed command templates, bounded subprocess evidence and exact-SHA workspace
verification.

## Authority boundary

- `default_registry()` is empty.
- `WorkspaceManager` requires an injected local Git protocol.
- Commands execute only in independent disposable exact-HEAD repositories.
- Linux command descendants inherit Landlock ABI 3+ and seccomp boundaries.
- Windows command containment fails closed until its later native boundary.
- Merge remains human-only.

Command templates freeze argv and reject non-canonical raw `cwd` authority before
`PurePosixPath` normalization. The executor verifies a clean exact-HEAD source,
creates a temporary bundle clone, removes the bundle and origin, exposes no object
alternate or real metadata backup, isolates command context, requires Linux
Landlock ABI 3+, applies the Landlock domain and installs an architecture-checked
seccomp filter before the reviewed argv starts. Landlock persistent write, create,
delete, truncate and refer rights exist only below the disposable sandbox root;
`/dev/null` is the sole non-persistent sink exception. Seccomp denies chmod,
chown, extended-attribute and timestamp mutation syscall families that Landlock
cannot mediate. Both restrictions are inherited by descendants; unavailable or
insufficient containment fails closed.

Patch application verifies exact HEAD and checks staged, unstaged, untracked,
ignored, assume-unchanged and skip-worktree state before parsing or invoking
`git apply`. Hidden index flags are explicitly cleared before verified reset and
must remain absent after reset and successful application.

## Projection summary

Six files remain exact copies and fourteen are documented projections. The final
projections additionally include:

- canonical raw command cwd validation in `commands.py`;
- inherited Landlock ABI 3+ and seccomp confinement in `commands.py`;
- dirty and hidden-index patch-workspace rejection before `git apply` in
  `patch.py`; and
- executable regressions proving descendant content and metadata escape attempts
  fail, hidden index flags are cleared, and direct sandbox metadata/nested-repo
  mutations remain observable and disposable.

## Required gates

1. Changed paths equal `exact-path-allowlist.json`.
2. Six exact copies match their recorded source blobs.
3. Fourteen projections match `source-provenance.json`.
4. The package imports with no missing future module and starts no work.
5. Task paths and command cwd authority are canonical before normalization.
6. Command and patch evidence binds to exact task HEAD.
7. Dirty command source state is rejected before execution.
8. Dirty or hidden-index patch state is rejected and reset before `git apply`.
9. Command execution is confined to the independent disposable sandbox.
10. Landlock ABI 3+ denies persistent content mutation outside that sandbox.
11. Seccomp denies host mode, ownership, xattr and timestamp mutation families.
12. Worktree and complete bounded Git metadata jointly determine receipts.
13. Sandbox cleanup and final source verification are mandatory.
14. Linux escaped descendants are terminated only with positive acknowledgement;
    unsupported containment fails closed.
15. Ignored artifacts, hidden index flags and nested repositories cannot coexist
    with positive command or patch evidence.
16. CI, CodeQL, diagnostics and independent exact-head review pass.

## Definition of done

The PR may merge only from a fresh current-main base, with every check green on
the exact head and an independent no-findings verdict bound to that head. Merge
remains a human action.
