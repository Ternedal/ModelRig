# Kaliv Development Control — DC-L01–DC-L04 foundations

These slices are the dormant, dependency-minimal foundation defined by
`docs/devcontrol/ADR-DC-001_DEVCONTROL_AUTHORITY_BOUNDARY.md` and the landed
DC-L00 decomposition contract.

## DC-L01 authority

DC-L01 supplies immutable task contracts, canonical repository-relative scope,
bounded reads/search, fail-closed patching, deterministic raw-byte receipts,
fixed command templates, exact-HEAD and clean-state binding, bounded subprocess
supervision and disposable Git sandboxes.

`default_registry()` remains empty. Product code must not import
`kaliv_dev_control`.

## DC-L02 authority

DC-L02 adds local, dormant campaign and review structure:

- immutable hash-chained campaign state;
- crash-durable create-once and atomic-replace publication primitives;
- a compare-and-swap `CampaignStore` with fail-closed stale-lock recovery;
- independent structural review requests and verdicts; and
- deterministic draft pull-request proposals with human-only merge authority.

## DC-L03 authority

DC-L03 adds immutable catalog and toolchain contracts plus a fixed-host,
HTTPS, GET-only GitHub read boundary. The default ModelRig catalog and default
registry remain empty, and every non-empty catalog materialization is rejected
fail-closed. Python, Go, sandbox and custom-static command execution remain
deferred.

## DC-L04 authority

DC-L04 defines the signed physical Windows-isolation evidence contract. It does
not implement Windows containment and cannot activate command execution.

The contract provides:

- eleven mandatory I0b probe identities covering token restriction, workspace
  access and escape denial, network denial, process-tree cleanup, reboot,
  memory/process limits and existing-tool compatibility;
- canonical unsigned and signed JSON report models;
- exact task, repository, base SHA, catalog, toolchain, rig, workspace and
  authority-code binding;
- separate collector and approver identities;
- detached HMAC-SHA256 signing with an operator-controlled key;
- exactly one fresh matching evidence artifact for verification; and
- crash-durable, create-once publication of canonical signed evidence.

A failed probe can be recorded honestly but cannot authorize anything. Historical
physical evidence remains stale until the final authority closure is frozen and a
fresh physical campaign is run.

## Operator flow

The physical harness writes one canonical unsigned report matching
`schemas/windows-isolation-physical-report-v1.schema.json`. Signing and
verification are separate operator actions. The key file must remain outside the
developer workspace and must not be a symlink.

```bash
PYTHONPATH=devcontrol/src python -m kaliv_dev_control sign-physical-report \
  C:/ModelRigEvidence/i0b-unsigned.json \
  C:/ModelRigEvidence/i0b-signed.json \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026

PYTHONPATH=devcontrol/src python -m kaliv_dev_control verify-physical-report \
  C:/ModelRigEvidence/attestation.json \
  --evidence-root C:/ModelRigEvidence \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

HMAC proves exact artifact/key binding only while the operator key remains under a
separate custody boundary. Copying the key into the developer workspace invalidates
the claimed independence.

## Deliberately absent

DC-L01–DC-L04 provide no Windows containment substrate, non-empty executable
catalog, GitHub write adapter, credential loader, remote Git, push, pull-request
mutation, reviewer request, merge, release, deployment or activation authority.
Native Windows containment belongs to DC-L05.

## Validation

```bash
PYTHONPATH=devcontrol/src python -m unittest discover -s devcontrol/tests -p 'test_*.py' -v
PYTHONPATH=devcontrol/src python -m kaliv_dev_control validate-task task.json
python3 tests/workflow_test_coverage.py
```

Exact-path, provenance, mutation and review evidence for this slice lives under
`docs/devcontrol/dc-l04/`.
