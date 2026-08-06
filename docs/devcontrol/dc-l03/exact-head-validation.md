# DC-L03 exact-head validation

Status: **authority candidate validated; repository workflow gates pending**

Authority implementation and regression candidate:
`660e85dcb0281cdbc0991d9cb5c06a7f0064ff6f`.

The candidate keeps the complete 16-path allowlist and includes:

- a reconstructed DevelopmentTask snapshot used for attestation comparison,
  materialization and registry binding;
- one deep-owned immutable catalog snapshot used for command resolution and the
  attested catalog hash;
- one deep-owned immutable toolchain snapshot used for the attested toolchain
  hash and every later binding lookup;
- local snapshots of the reviewed isolation and executable verifier objects
  before any external callback;
- a private reconstructed isolation-attestation snapshot, a separate verifier
  copy and a post-callback canonical/authority check, so caller or verifier
  mutation cannot retarget the accepted proof;
- a sealed task-bound command registry that enforces the exact attested task
  identity on every resolution and retains the original executable verifier;
- Linux executable verification through no-follow, nonblocking descriptor opens,
  bounded reads and execution from sealed memfd bytes;
- explicit FIFO regression coverage proving a non-regular executable candidate
  is rejected without waiting for a writer;
- process-lifetime descriptor retirement preventing pathname replacement and
  stale fd retargeting;
- fail-closed Windows/non-Linux executable verification;
- strict catalog environment policy rejecting all `LD_*`, `DYLD_*`, `GIT_*`,
  Python path and sandbox-reserved authority variables;
- a sealed GitHub adapter whose task snapshot, repository path, token, timeout
  and transport authority cannot be retargeted after construction;
- fixed-host HTTPS GET-only GitHub reads with redirects and environment proxies
  disabled;
- an explicit TLS client context with certificate verification and hostname
  checking whose trust roots come only from compiled OpenSSL paths or explicit
  Windows certificate stores, never `SSL_CERT_FILE` or `SSL_CERT_DIR`;
- fail-closed TLS setup when approved system trust roots cannot be loaded;
- exact-SHA validation before transport, protected-path denial before network,
  bounded response/base64 handling and decoded Git-blob verification;
- concrete integer receipt status validation, including rejection of `200.0`.

Focused DC-L03 validation produced **26/26 passing tests** using the candidate
catalog and test blobs. The suite covers isolation-attestation mutation inside
the verifier callback, FIFO/non-regular executable handling without blocking,
deep mutation of catalog specs and tool bindings, verifier replacement during
an external callback, task mutation, registry retargeting and cross-task reuse,
catalog replacement, toolchain mutation, pathname replacement, descriptor
retirement, symlinks, hash mismatch, moving refs, complete GitHub adapter
retargeting, protected paths, proxy/redirect escape, environment-selected TLS
roots, blob mismatch, token non-persistence and strict persisted types.

The independent review of exact head
`96967da26134cb68cc59242fbee004cc403228ba` found two actionable issues:

1. the verifier could mutate the attestation object after the initial authority
   comparison;
2. opening a FIFO with blocking `O_RDONLY` could hang before regular-file
   validation.

Both findings are closed by candidate
`660e85dcb0281cdbc0991d9cb5c06a7f0064ff6f` and their executable regressions.
A fresh independent review is required for the resulting evidence head.

Verified repository facts:

- diff equals `exact-path-allowlist.json` at 16 paths;
- branch merge base is declared fresh `main` head
  `c9bda459f10e682ec200fdfea8484d726c6c0057` and branch is 0 commits behind;
- all review threads opened before this evidence update are resolved;
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
