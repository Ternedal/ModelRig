# DC-L03 exact-head validation

Status: **authority candidate validated; repository workflow gates pending**

Authority implementation and regression candidate:
`157b158011d120797a230912f1c96a23babb1ace`.

The candidate keeps the complete 16-path allowlist and includes:

- a reconstructed DevelopmentTask snapshot used for attestation comparison,
  materialization and registry binding;
- deep-owned immutable catalog and toolchain snapshots used consistently for
  hashing, command resolution and executable binding;
- local snapshots of the reviewed isolation and executable verifier objects
  before any external callback;
- a private reconstructed isolation-attestation snapshot, a separate verifier
  copy and a post-callback canonical/authority check;
- a sealed task-bound command registry that rejects mutation and cross-task use;
- Linux executable verification through no-follow, nonblocking descriptor opens,
  bounded reads and execution from sealed memfd bytes;
- process-lifetime descriptor retirement preventing pathname and stale-fd
  retargeting;
- fail-closed Windows/non-Linux executable verification;
- strict catalog environment rejection for all `LD_*`, `DYLD_*`, `GIT_*`,
  Python-path and sandbox-reserved authority variables;
- a sealed GitHub adapter with fixed task, repository, token, timeout and
  transport authority;
- fixed-host HTTPS GET-only GitHub reads with redirects and environment proxies
  disabled;
- explicit TLS trust from compiled OpenSSL paths or Windows certificate stores,
  never `SSL_CERT_FILE` or `SSL_CERT_DIR`;
- exact-SHA validation before transport, protected-path denial before network,
  bounded response/base64 handling and decoded Git-blob verification;
- strict receipt reload, including rejection of non-integer `200.0`;
- receipt-schema repository syntax aligned with runtime rejection of dot
  segments, whitespace and NUL authority.

Focused DC-L03 validation produced **26/26 passing tests** using catalog/test
blobs `53fa2dbd86b41e0b59342e02447efd3e5f4123af` and
`6a0d9efbee6b357249c4807d8f4e51b883bd67df`. The suite covers attestation
mutation inside the verifier callback, FIFO rejection without blocking, deep
catalog/toolchain mutation, verifier replacement, task mutation, registry
retargeting and cross-task reuse, pathname replacement, descriptor retirement,
symlinks, hash mismatch, moving refs, complete GitHub-adapter retargeting,
protected paths, proxy/redirect escape, environment-selected TLS roots, blob
mismatch, token non-persistence and strict persisted types.

The receipt repository schema regression additionally accepts the canonical
`Ternedal/ModelRig` identity and rejects owner/name dot segments, whitespace and
NUL values, matching runtime `_valid_repository` behavior.

Independent review of `96967da26134cb68cc59242fbee004cc403228ba`
found attestation-callback mutation and blocking FIFO-open issues. Candidate
`660e85dcb0281cdbc0991d9cb5c06a7f0064ff6f` closed both. Candidate
`157b158011d120797a230912f1c96a23babb1ace` additionally closes the author-side
receipt-schema/runtime mismatch. A fresh independent review is required for the
resulting evidence head.

Verified repository facts:

- diff equals `exact-path-allowlist.json` at 16 paths;
- merge base is fresh `main` head
  `c9bda459f10e682ec200fdfea8484d726c6c0057` and branch is 0 commits behind;
- all review threads opened before this evidence update are resolved;
- all five locked source paths have projection disposition and provenance;
- package activation remains unchanged and `default_registry()` remains empty;
- no GitHub write, non-GET HTTP, remote Git, merge, publication, deployment or
  activation authority is introduced.

Still required before merge:

- an independent review of the resulting exact head with no actionable finding;
- repository CI, CodeQL, agent3-diagnostics and agent3-full-diagnostics on the
  exact head. GitHub has not created Actions runs for connector-authored heads,
  so no workflow success is claimed here.

This evidence update changes the branch head. Final conclusions must bind to the
resulting exact head rather than the implementation candidate above.
