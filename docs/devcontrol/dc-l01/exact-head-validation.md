# DC-L01 exact-head validation contract

This artifact defines the validation that must be green on the exact pull-request
head. It intentionally makes no transient claim about a SHA or workflow status;
those are recorded by GitHub checks and the PR review bound to that SHA.

## Required commands

```bash
python3 -m compileall -q devcontrol/src devcontrol/tests
PYTHONPATH=devcontrol/src python3 -m unittest discover -s devcontrol/tests -p 'test_*.py' -v
python3 tests/workflow_test_coverage.py
```

## Required repository checks

- `ci`
- `codeql`
- `agent3-diagnostics`
- `agent3-full-diagnostics`

## Exact-head assertions

- PR base equals current `main` before final review.
- Changed paths equal `exact-path-allowlist.json` exactly.
- All five exact-copy files equal the source blob in `source-provenance.json`.
- All fifteen projections match their documented dependency-minimal deltas.
- The package imports with no missing or future module and starts no work.
- Command templates freeze argv and reject non-canonical cwd authority.
- Explicit `LD_*` environment authority is rejected before any subprocess spawn;
  inherited `LD_*` and `GIT_*` context is stripped.
- Workspace reads consume at most the declared per-file limit plus one byte;
  search reads remain bounded if a file grows after `stat`.
- Real subprocess output retains its original bytes for SHA-256 and byte-count
  evidence even when display decoding uses replacement characters.
- Command and patch execution bind evidence to `HEAD == task.base_sha`.
- Dirty command source state fails before a registered command starts.
- Staged, unstaged, untracked, ignored, assume-unchanged and skip-worktree patch
  state is rejected and verified-reset before any `git apply` invocation.
- Hidden index flags are explicitly cleared before reset and verified absent.
- Each registered command executes in a bounded independent exact-HEAD Git
  repository created through a temporary bundle.
- The bundle and origin are removed; no object alternate, source path or real Git
  metadata backup is exposed to command code.
- Linux Landlock ABI 3+ grants persistent write/create/delete/truncate/refer rights
  only below the disposable sandbox root, with `/dev/null` as the sole
  non-persistent sink exception.
- An inherited architecture-checked seccomp filter denies direct and alternate
  host metadata mutation paths, including xattr-at, io_uring and x86_64 x32
  syscall variants; unsupported confinement fails closed.
- Worktree state and complete bounded sandbox Git metadata jointly determine
  command receipt state.
- Sandbox cleanup is mandatory and the source repository is re-verified at the
  exact task HEAD with zero residual state before a receipt can return.
- Linux subprocess containment kills descendants that escape into new sessions
  and requires positive quiescence acknowledgement.
- Ignored files and nested Git repositories count as patch mutations and are
  physically removed by verified double-force cleanup.
- No merge, release, deployment or activation adapter exists in the slice.
- Any commit after review invalidates the verdict and requires complete rerun.

The PR body must name the exact head and check run numbers. A green ancestor is
not evidence.
