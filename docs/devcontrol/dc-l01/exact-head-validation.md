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
- The package imports with no missing/future/product module and starts no work.
- Command templates freeze argv and reject `GIT_*`, `HOME` and
  `XDG_CONFIG_HOME` isolation overrides.
- Generic command execution strips inherited `GIT_*` context.
- Command and patch execution verify workspace `HEAD == task.base_sha`; a
  mismatch returns no passing receipt.
- Staged, unstaged, untracked and ignored source-workspace state is rejected
  before a registered command starts.
- Each registered command executes in a bounded independent exact-HEAD Git
  repository created through a temporary bundle.
- The bundle and origin are removed before command execution; the sandbox uses no
  object alternates and exposes no source path through arguments, environment,
  Git config or reflogs.
- Worktree state and the complete bounded sandbox `.git` metadata fingerprint
  jointly determine command receipt state.
- Config, hook, ref, object, ignored-file and nested-repository mutations remain
  inside the disposable sandbox, invalidate positive evidence and are physically
  removed when the sandbox is destroyed.
- Sandbox cleanup is mandatory and the source repository is re-verified at the
  exact task HEAD with zero staged, unstaged, untracked or ignored state before a
  receipt can be returned.
- Empty, dot and parent raw task-path segments are rejected before
  `PurePosixPath` can normalize them.
- Linux containment kills descendants that escape into new sessions.
- Termination proof requires the supervisor's positive quiescence acknowledgement;
  unacknowledged or fallback termination fails without returning a result.
- Windows containment fails closed until DC-L05 lands its native boundary.
- Ignored files and nested Git repositories count as patch-workspace mutations,
  cannot coexist with a positive patch receipt and are physically removed by
  `git clean -ffdx` during patch reset.
- Patch reset verifies exact HEAD and zero staged, unstaged, untracked and ignored
  residual state before success is claimed.
- A post-command snapshot/output-limit failure cannot expose or dirty the source
  repository because command execution is confined to the disposable sandbox.
- No product module imports `kaliv_dev_control`.
- No HTTP write, remote Git verb, credential loader, GitHub mutation, merge,
  release, deployment or activation adapter exists in the slice.
- Any commit after review invalidates the verdict and requires complete rerun.

The PR body must name the exact head and check run numbers. A green ancestor is
not evidence.
