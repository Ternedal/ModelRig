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
- All nine exact-copy files equal the source blob in `source-provenance.json`.
- All eleven projections match their documented dependency-minimal deltas.
- The package imports with no missing/future/product module and starts no work.
- Linux containment kills descendants that escape into new sessions.
- Windows containment fails closed until DC-L05 lands its native boundary.
- Ignored files count as workspace mutations and `git clean -fdx` removes them.
- No product module imports `kaliv_dev_control`.
- No HTTP write, remote Git verb, credential loader, GitHub mutation, merge,
  release, deployment or activation adapter exists in the slice.
- Any commit after review invalidates the verdict and requires complete rerun.

The PR body must name the exact head and check run numbers. A green ancestor is
not evidence.
