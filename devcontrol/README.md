# Kaliv Development Control — DC-L01 and DC-L02 foundations

These slices are the dormant, dependency-minimal foundation defined by
`docs/devcontrol/ADR-DC-001_DEVCONTROL_AUTHORITY_BOUNDARY.md` and the landed
DC-L00 decomposition contract.

## DC-L01 authority

DC-L01 supplies immutable task contracts, canonical repository-relative scope,
bounded reads/search, fail-closed patching, deterministic raw-byte receipts,
fixed command templates, exact-HEAD and clean-state binding, bounded subprocess
supervision, disposable Git sandboxes, Linux Landlock ABI 3+ confinement and an
architecture-checked seccomp metadata-mutation boundary.

`default_registry()` remains empty. Windows command containment remains
fail-closed until DC-L05. Product code must not import `kaliv_dev_control`.

## DC-L02 authority

DC-L02 adds only local, dormant campaign and review structure:

- immutable hash-chained campaign state;
- crash-durable create-once and atomic-replace publication primitives;
- a compare-and-swap `CampaignStore`;
- stale-lock recovery only when the recorded owner is provably dead or its
  process identity no longer matches;
- durable lock create, reclaim and release operations;
- parent-directory metadata persistence after directory creation, file
  publication, replacement and unlink;
- independent structural review requests and verdicts;
- deterministic draft pull-request proposals with human-only merge authority.

The campaign store never deletes an unverifiable or live lock. Lock records bind
PID, stable process identity and a random nonce. Malformed lock evidence fails
closed.

## Deliberately absent

These slices provide no non-empty command catalog, concrete Git runner, GitHub
write adapter, credentials, remote publication, merge, release, deployment or
activation authority. `streaming_publication.py` belongs to DC-L07 and is not
part of DC-L02.

## Validation

```bash
PYTHONPATH=devcontrol/src python -m unittest discover -s devcontrol/tests -p 'test_*.py' -v
PYTHONPATH=devcontrol/src python -m kaliv_dev_control validate-task task.json
python3 tests/workflow_test_coverage.py
```

Exact-path, provenance, mutation and review evidence for DC-L02 lives under
`docs/devcontrol/dc-l02/`.
