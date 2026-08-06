# DC-L03 exact-head validation

Status: **authority candidate validated; repository workflow gates pending**

Authority implementation and regression candidate:
`852c4604376d48290700c7a1a7f05729623106ee`.

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
- an explicit TLS client context with certificate verification and hostname
  checking whose trust roots come only from compiled OpenSSL paths or explicit
  Windows certificate stores, never `SSL_CERT_FILE` or `SSL_CERT_DIR`;
- fail-closed TLS setup when no approved system trust roots can be loaded;
- exact-SHA validation before transport, protected-path denial before network,
  bounded response/base64 handling and decoded Git-blob verification;
- concrete integer receipt status validation, including rejection of `200.0`.

Focused DC-L03 validation produced **24/24 passing tests** using the exact landed
runtime and test blob IDs `9e3760fb87b68b6cb59ec4885ab43673a31427a6`
and `f1bae155af0e4e28fae1bc6c09979c9ec6a3212f`. The suite covers deep mutation
of catalog specs and tool bindings, verifier replacement during an external
callback, task mutation, registry retargeting and cross-task reuse, catalog
replacement, toolchain mutation, pathname replacement, descriptor retirement,
symlinks, hash mismatch, moving refs, complete GitHub adapter retargeting,
protected paths, proxy/redirect escape, environment-selected TLS roots, blob
mismatch, token non-persistence and strict persisted types.

The independent review of exact head
`5ca477c95b6e6a5ac396b6ff9d55db2de49b3511` found one actionable P2 issue:
process-environment TLS trust overrides could affect the default HTTPS handler.
The explicit system-trust context and regression in candidate
`852c4604376d48290700c7a1a7f05729623106ee` close that finding. A fresh
independent review is required for the resulting exact head.

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
