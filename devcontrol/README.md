# Kaliv Development Control — DC-L01–DC-L05 foundations

These slices are the dormant, bounded foundation defined by
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

DC-L04 defines the signed physical Windows-isolation evidence contract. It
provides eleven mandatory probe identities, canonical unsigned and signed report
models, exact authority binding, separate collection and approval actors,
bounded stable evidence reads and crash-durable create-once publication.

A failed probe can be recorded honestly but cannot authorize anything. Historical
physical evidence remains stale until the final authority closure is frozen and a
fresh physical campaign is run.

## DC-L05 authority

DC-L05 lands the product-side native Windows containment substrate without
activating DevControl:

- Job Object assignment before resume, process and memory limits, and kill-on-close;
- AppContainer/restricted-token launch with a workspace-scoped capability;
- bounded product-side stdout/stderr capture and whole-process-tree cleanup;
- exact working-directory and reviewed environment handling;
- runtime-lifetime immutability checks; and
- a dormant Tier-A Windows launch surface used only by explicit product-side tests.

The product modules under `worker/app/` do not import `kaliv_dev_control`.
DC-L05 does not register a command, populate the empty catalog, validate physical
evidence, create a Git authority, or expose a route/remote operation. Support
programs that exercise the later DevControl Windows executor, Tier-A catalog or
trusted-Git receipt remain landed but dormant until their owning slices exist.

## Physical evidence operator flow

The physical harness writes one canonical unsigned report matching
`schemas/windows-isolation-physical-report-v1.schema.json`. Signing and
verification are separate operator actions. The key file must remain outside the
developer workspace.

```bash
PYTHONPATH=devcontrol/src python -m kaliv_dev_control sign-physical-report \
  /operator/evidence/i0b-unsigned.json \
  /operator/evidence/i0b-signed.json \
  --key-file /operator/keys/isolation.key \
  --key-id operator-key-2026

PYTHONPATH=devcontrol/src python -m kaliv_dev_control verify-physical-report \
  /operator/evidence/attestation.json \
  --evidence-root /operator/evidence \
  --key-file /operator/keys/isolation.key \
  --key-id operator-key-2026
```

## Deliberately absent

DC-L01–DC-L05 provide no non-empty executable catalog, Tier-A authority
materialization, verified DevControl execution facade, trusted Git runtime,
credential loader, GitHub write adapter, remote Git, push, pull-request mutation,
reviewer request, merge, release, deployment or activation authority.

## Validation

```bash
PYTHONPATH=devcontrol/src python -m unittest discover -s devcontrol/tests -p 'test_*.py' -v
PYTHONPATH=devcontrol/src python -m kaliv_dev_control validate-task task.json
python3 tests/workflow_test_coverage.py
```

Native Windows containment contracts run in the reusable CI workflow on a real
Windows runner. Exact-path, provenance, mutation and review evidence for this
slice lives under `docs/devcontrol/dc-l05/`.
