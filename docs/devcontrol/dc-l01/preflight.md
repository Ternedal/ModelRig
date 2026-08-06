# DC-L01 preflight — task, scope, workspace and bounded command foundation

**Slice:** DC-L01  
**Base:** `main @ 4c7f4c7c31d97faea98147ebdfa97d0479abbdc1`  
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
- Linux command descendants inherit a Landlock filesystem-write boundary.
- Windows command containment fails closed until its later native boundary.
- Merge remains human-only.

Command templates freeze argv and reject non-canonical raw `cwd` authority before
`PurePosixPath` normalization. The executor verifies a clean exact-HEAD source,
creates a temporary bundle clone, removes the bundle and origin, exposes no object
alternate or real metadata backup, isolates command context, applies a Linux
Landlock ruleset before the reviewed argv starts, fingerprints both worktree and
bounded Git metadata, destroys the sandbox and re-verifies the source before
returning evidence. Persistent filesystem write, create, delete, truncate and
refer rights are granted only below the disposable sandbox root; `/dev/null` is
the sole non-persistent sink exception required by Git. The restriction is
inherited by descendants, and unavailable Landlock fails closed.

Patch application verifies exact HEAD and checks staged, unstaged, untracked and
ignored state before parsing or invoking `git apply`. A dirty ephemeral workspace
is verified-reset to the task base and rejected. Post-apply evidence retains the
ignored-file, nested-repository and double-force reset protections.

## Projection summary

Six files remain exact copies and fourteen are documented projections. The final
projections additionally include:

- canonical raw command cwd validation in `commands.py`;
- inherited Landlock confinement for command filesystem writes in `commands.py`;
- dirty patch-workspace rejection before `git apply` in `patch.py`; and
- executable regressions proving ambiguous cwd values fail, pre-staged patch
  state triggers reset without any `git apply` call, and descendant absolute-path
  writes outside the sandbox leave no host artifact.

## Required gates

1. Changed paths equal `exact-path-allowlist.json`.
2. Six exact copies match their recorded source blobs.
3. Fourteen projections match `source-provenance.json`.
4. The package imports with no missing future module and starts no work.
5. Task paths and command cwd authority are canonical before normalization.
6. Command and patch evidence binds to exact task HEAD.
7. Dirty command source state is rejected before execution.
8. Dirty patch state is rejected and reset before any `git apply` call.
9. Command execution is confined to the independent disposable sandbox.
10. Landlock denies persistent writes outside that sandbox for commands and
    descendants, with only `/dev/null` allowed as a non-persistent sink.
11. Worktree and complete bounded Git metadata jointly determine receipts.
12. Sandbox cleanup and final source verification are mandatory.
13. Linux escaped descendants are terminated only with positive acknowledgement;
    unsupported containment fails closed.
14. Ignored artifacts and nested repositories cannot coexist with positive
    command or patch evidence.
15. CI, CodeQL, diagnostics and independent exact-head review pass.

## Definition of done

The PR may merge only from a fresh current-main base, with every check green on
the exact head and an independent no-findings verdict bound to that head. Merge
remains a human action.
