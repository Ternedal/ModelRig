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
- All six exact-copy files equal the source blob in `source-provenance.json`.
- All fourteen projections match their documented dependency-minimal deltas.
- The package imports with no missing or future module and starts no work.
- Command templates freeze argv, reject reserved environment overrides and reject
  raw cwd values containing empty, dot, parent, duplicate or trailing segments
  before `PurePosixPath` normalization.
- Generic command execution strips inherited Git context.
- Command and patch execution verify workspace `HEAD == task.base_sha`; a
  mismatch returns no passing receipt.
- Staged, unstaged, untracked and ignored source state is rejected before a
  registered command starts.
- Staged, unstaged, untracked and ignored patch-workspace state is rejected and
  verified-reset before any `git apply` invocation.
- Each registered command executes in a bounded independent exact-HEAD Git
  repository created through a temporary bundle.
- The bundle and origin are removed before command execution; the sandbox uses no
  object alternates and exposes no source path through arguments, environment,
  Git configuration or logs.
- Before the reviewed argv starts, Linux Landlock handles persistent filesystem
  write, create, delete, truncate and refer operations; only the disposable
  sandbox root receives those rights, with `/dev/null` as the sole non-persistent
  sink exception required by Git.
- The Landlock restriction is inherited by descendants. An absolute or parent
  escape write outside the sandbox must fail, leave no host artifact and never
  coexist with positive command evidence; unavailable Landlock fails closed.
- Worktree state and the complete bounded sandbox `.git` metadata fingerprint
  jointly determine command receipt state.
- Config, hook, ref, object, ignored-file and nested-repository mutations remain
  inside the disposable sandbox, invalidate positive evidence and are removed
  when the sandbox is destroyed.
- Sandbox cleanup is mandatory and the source repository is re-verified at the
  exact task HEAD with zero staged, unstaged, untracked or ignored state before a
  receipt can be returned.
- Empty, dot and parent raw task-path segments are rejected before path
  normalization can alter authority.
- Linux subprocess containment kills descendants that escape into new sessions
  and requires positive quiescence acknowledgement; unsupported paths fail closed.
- Ignored files and nested Git repositories count as patch-workspace mutations,
  cannot coexist with a positive patch receipt and are physically removed by
  double-force cleanup during patch reset.
- Patch reset verifies exact HEAD and zero staged, unstaged, untracked and ignored
  residual state before success is claimed.
- No merge, release, deployment or activation adapter exists in the slice.
- Any commit after review invalidates the verdict and requires complete rerun.

The PR body must name the exact head and check run numbers. A green ancestor is
not evidence.
