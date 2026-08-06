# DC-L01 preflight — task, scope, workspace and bounded command foundation

**Slice:** DC-L01  
**Original branch base:** `main @ 4c7f4c7c31d97faea98147ebdfa97d0479abbdc1`  
**Synchronized current main:** `ee1d828b9f956284216b78ff8784c6787c3736dc`  
**Source reference:** PR #338 at `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Depends on:** landed DC-L00 (PR #352)  
**Status:** exact-head validation and independent review required before merge

## Purpose

Land only dependency-minimal primitives for immutable task contracts, canonical
path and command policy, bounded file access, fail-closed patching, deterministic
raw-byte receipts, fixed command templates, bounded subprocess evidence and
exact-SHA workspace verification.

## Authority boundary

- `default_registry()` is empty.
- `WorkspaceManager` requires an injected local Git protocol.
- Commands execute only in independent disposable exact-HEAD repositories.
- Explicit and inherited dynamic-loader hooks are removed or rejected before spawn.
- Linux command descendants inherit Landlock ABI 3+ and seccomp boundaries.
- Windows command containment fails closed until its later native boundary.
- Merge remains human-only.

The executor verifies a clean exact-HEAD source, including staged, unstaged,
untracked, ignored, assume-unchanged and skip-worktree state. Hidden command-source
index flags are included in the snapshot fingerprint before execution and during
final source re-verification. The executor then creates a temporary bundle clone,
removes the bundle and origin, exposes no object alternate or real metadata backup,
isolates command context, requires Linux Landlock ABI 3+, applies the Landlock
domain and installs an architecture-checked seccomp filter before the reviewed
argv starts. Landlock persistent write, create, delete, truncate and refer rights
exist only below the disposable sandbox root; `/dev/null` is the sole
non-persistent sink exception. Seccomp denies chmod, chown, extended-attribute,
timestamp, x32 and io_uring mutation paths that Landlock cannot mediate. Both
restrictions are inherited by descendants; unavailable or insufficient
containment fails closed.

Subprocess display text retains its exact original bytes for receipt hashing and
byte counts, so replacement decoding cannot collapse distinct output evidence.
Workspace file reads and search reads consume at most the declared per-file limit
plus one byte before rejecting overflow.

Patch application verifies exact HEAD and checks staged, unstaged, untracked,
ignored, assume-unchanged and skip-worktree state before parsing or invoking
`git apply`. Hidden index flags are explicitly cleared before verified reset and
must remain absent after reset and successful application.

## Projection summary

Five files remain exact copies and fifteen are documented projections. The final
projections additionally include:

- hidden command-source index detection plus inherited Landlock ABI 3+ and seccomp
  confinement in `commands.py`;
- pre-spawn dynamic-loader rejection and raw-byte output preservation in
  `workspace.py`;
- physically bounded read/search I/O in `files.py`;
- dirty and hidden-index patch-workspace rejection before `git apply`; and
- executable CI regressions for loader hooks, max-plus-one reads, non-UTF-8 output,
  hidden command-source flags and synchronized-main attestation.

## Required gates

1. Changed paths equal `exact-path-allowlist.json`.
2. Five exact copies match their recorded source blobs.
3. Fifteen projections match `source-provenance.json`.
4. The package imports with no missing future module and starts no work.
5. Task paths and command cwd authority are canonical before normalization.
6. Explicit `LD_*` command environment authority is rejected before spawn.
7. File reads remain physically bounded during I/O.
8. Command receipts preserve exact raw output hashes and byte counts.
9. Command and patch evidence binds to exact task HEAD.
10. Staged, unstaged, untracked, ignored, assume-unchanged and skip-worktree
    command source state is rejected before execution and during final verification.
11. Dirty or hidden-index patch state is rejected and reset before `git apply`.
12. Command execution is confined to the independent disposable sandbox.
13. Landlock ABI 3+ and seccomp deny content and metadata mutation escapes.
14. Worktree, hidden index state and complete bounded Git metadata jointly
    determine receipts.
15. Sandbox cleanup and final source verification are mandatory.
16. Linux escaped descendants are terminated only with positive acknowledgement;
    unsupported containment fails closed.
17. Ignored artifacts, hidden index flags and nested repositories cannot coexist
    with positive command or patch evidence.
18. CI, CodeQL, diagnostics and independent exact-head review pass.

## Definition of done

The PR may merge only from a fresh current-main base, with every check green on
the exact head and an independent no-findings verdict bound to that head. Merge
remains a human action.
