# DC-L03 exact-head validation

Status: **authority candidate validated; repository workflow gates pending**

Authority implementation and regression candidate:
`ddcbf355a173d59dca3e8c695ae3cd2f393d2bc6`.

The candidate keeps the complete 16-path allowlist and includes:

- a reconstructed DevelopmentTask snapshot used for attestation comparison,
  materialization and registry binding;
- one deep-owned immutable catalog snapshot used for both command resolution and
  the attested catalog hash;
- one deep-owned immutable toolchain snapshot used for both the attested
  toolchain hash and every later binding lookup;
- local snapshots of the reviewed isolation and executable verifier objects
  before any external callback;
- a sealed task-bound command registry that enforces the exact attested task
  identity on every resolution and retains the original executable verifier;
- sealed Linux executable-object pinning and process-lifetime descriptor
  retirement, preventing pathname replacement and stale fd retargeting;
- fail-closed Windows/non-Linux executable verification;
- strict catalog environment policy rejecting all `LD_*`, `DYLD_*`, `GIT_*`,
  Python path and sandbox-reserved authority variables;
- a sealed GitHub adapter whose reconstructed task snapshot, repository path,
  token, timeout and transport authority cannot be retargeted after construction;
- fixed-host HTTPS GET-only GitHub reads with redirects and environment proxies
  disabled;
- exact-SHA validation before transport, protected-path denial before network,
  bounded response/base64 handling and decoded Git-blob verification;
- concrete integer receipt status validation, including rejection of `200.0`.

Focused DC-L03 validation produced **24/24 passing tests** in an isolated harness
with the landed DC-L03 implementations and dependencies. The suite covers deep
mutation of catalog specs and tool bindings, verifier replacement during an
external callback, task mutation, registry retargeting and cross-task reuse,
catalog replacement, toolchain mutation, pathname replacement, descriptor
retirement, symlinks, hash mismatch, moving refs, complete GitHub adapter
retargeting, protected paths, proxy/redirect escape, blob mismatch, token
non-persistence and strict persisted types.

Verified repository facts:

- diff equals `exact-path-allowlist.json` at 16 paths;
- branch merge base is declared fresh `main` head
  `c9bda459f10e682ec200fdfea8484d726c6c0057` and branch is 0 commits behind;
- all five locked source paths have projection disposition and provenance;
- package activation surface remains unchanged and `default_registry()` remains
  empty;
- no GitHub write, non-GET HTTP, remote Git, merge, publication, deployment or
  activation authority is introduced.

Still required before merge:

- an independent review of the resulting exact head with no actionable finding;
- repository CI, CodeQL, agent3-diagnostics and agent3-full-diagnostics on the
  exact head. GitHub has not created Actions runs for connector-authored heads,
  so no workflow success is claimed here.

This evidence update changes the branch head. Final conclusions must bind to the
resulting exact head rather than the implementation candidate above.
