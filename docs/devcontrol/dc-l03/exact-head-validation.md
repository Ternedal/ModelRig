# DC-L03 exact-head validation

Status: **authority candidate validated; repository workflow gates pending**

Authority implementation and regression candidate:
`4cbd642573546e62b995541d97d5b8909081b873`.

The candidate keeps the complete 16-path allowlist and includes:

- one immutable toolchain snapshot used for both the attested hash and every
  later binding lookup;
- sealed Linux executable-object pinning and process-lifetime descriptor
  retirement, preventing pathname replacement and stale fd retargeting;
- fail-closed Windows/non-Linux executable verification;
- strict catalog environment policy;
- a private reconstructed DevelopmentTask snapshot used for every GitHub host,
  repository, path, budget, ref and receipt decision;
- fixed-host HTTPS GET-only GitHub reads with redirects and environment proxies
  disabled;
- exact-SHA validation before transport, protected-path denial before network,
  bounded response/base64 handling and decoded Git-blob verification;
- concrete integer receipt status validation, including rejection of `200.0`.

Focused DC-L03 validation produced **18/18 passing tests** in an isolated harness
containing the committed DC-L03 implementations and their landed dependencies.
The suite covers both exact-head review findings, pathname replacement,
descriptor retirement, symlinks, hash mismatch, moving refs, public task
reassignment, protected paths, proxy/redirect escape, blob mismatch, token
non-persistence and strict persisted types.

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
