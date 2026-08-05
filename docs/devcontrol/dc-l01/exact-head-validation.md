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
- All seven exact-copy files equal the source blob in `source-provenance.json`.
- All thirteen projections match their documented dependency-minimal deltas.
- The package imports with no missing/future/product module and starts no work.
- Command templates freeze argv into immutable tuples before registry use.
- Command and patch execution verify workspace `HEAD == task.base_sha`; a
  mismatch returns no passing receipt.
- Staged, unstaged, untracked and ignored workspace state is rejected before a
  registered command starts.
- Empty, dot and parent raw task-path segments are rejected before
  `PurePosixPath` can normalize them.
- Linux containment kills descendants that escape into new sessions.
- Termination proof requires the supervisor's positive quiescence acknowledgement;
  unacknowledged or fallback termination fails without returning a result.
- Windows containment fails closed until DC-L05 lands its native boundary.
- Ignored files count as workspace mutations for both command and patch evidence,
  cannot coexist with a positive receipt, and are physically removed by
  `git clean -fdx` during reset.
- No product module imports `kaliv_dev_control`.
- No HTTP write, remote Git verb, credential loader, GitHub mutation, merge,
  release, deployment or activation adapter exists in the slice.
- Any commit after review invalidates the verdict and requires complete rerun.

The PR body must name the exact head and check run numbers. A green ancestor is
not evidence.
