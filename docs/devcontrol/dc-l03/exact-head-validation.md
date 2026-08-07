# DC-L03 exact-head validation

Status: **authority candidate hardened; exact-head workflow gates pending**

Current authority implementation/regression candidate:
`ac4eaa44fa501eba797818d8563e82c9b83ce8f0`.

The candidate keeps the complete 16-path allowlist and includes:

- reconstructed DevelopmentTask, catalog, toolchain and attestation snapshots;
- private isolation-verifier proof plus post-callback canonical revalidation;
- sealed exact-task command registries and reviewed verifier retention;
- Linux no-follow, nonblocking, bounded executable reads and sealed memfd launch;
- process-lifetime descriptor retirement and fail-closed non-Linux verification;
- a fixed-value environment positive list with `PATH=/usr/bin:/bin` injected into
  every accepted catalog entry, including entries supplied with `env={}`;
- rejection of every explicitly different PATH and all unreviewed interpreter,
  loader and toolchain environment authority;
- fixed-host HTTPS GET-only GitHub reads with redirects and proxies disabled;
- explicit system TLS roots independent of environment CA overrides;
- a raw owned HTTPS connection supervised from request start through status,
  headers, chunk framing and response body under one monotonic deadline;
- socket shutdown/close, response close and connection close on deadline expiry;
- fail-closed handling when a deadline-capable transport socket is unavailable;
- exact-SHA and protected-path checks before transport, bounded JSON/base64
  handling and decoded Git-blob identity verification;
- strict receipt runtime/schema identity, status and repository validation.

Latest landed authority blobs:

- catalog: `e562bbbf9acb6833279491303b6ab7b508bc3e0e`;
- GitHub read transport: `0b32313fe2d613367c15e4df23ede556943c27c5`;
- receipt schema: `40615abb093d890a98391ad8dc38d90fb8166c2d`;
- workflow contract/regressions: `8e1eeb504aff2829a2dfe025d1972b6832070006`.

The latest complete focused DC-L03 run before the final environment/deadline
hardening produced **26/26 passing tests**. Existing public test surfaces were
preserved while additional executable contract regressions and direct validation
now cover:

- rejection of `GOROOT=.`, `PYTHONUSERBASE=.`, `GOTOOLCHAIN=auto` and an
  attacker-selected PATH;
- automatic fixed-PATH insertion for a caller-supplied `env={}` spec;
- a `read1()` call that blocks internally until socket cancellation;
- a `getresponse()` call that blocks while reading HTTP status/headers;
- wall-clock rejection in approximately 0.05 seconds with socket, response and
  connection closure;
- preserved successful reads, fixed-host validation and byte-budget rejection.

Review history:

- review of `96967da26134cb68cc59242fbee004cc403228ba` found mutable verifier proof and
  blocking FIFO-open issues; candidate `660e85dcb0281cdbc0991d9cb5c06a7f0064ff6f`
  closed both;
- author-side schema audit found receipt repository syntax looser than runtime;
  candidate `157b158011d120797a230912f1c96a23babb1ace` aligned them;
- review of `002306223eb172351f9bfd1665dc1d5f9bdcfd2a` found remaining interpreter/
  toolchain environment authority and missing end-to-end response-read deadline;
  candidate `b7cabc3524a75d980cd5e0710b2acfeed7a15eb2` closed them;
- review of `9829fe24227f363141c779237a9e042a1a1af2ca` found ambient PATH authority and
  chunk-framing work occurring inside one `read1()` call; candidate
  `5eb237398cd4b9867e50bc42656476835ca4a057` closed them;
- review of `3483ac687a267d6ec31aa71eaa4896baa5604d74` found that omitted PATH still
  inherited ambient authority and status/header framing remained outside the
  supervisor; candidates `5944d164badbb1af773ab7d63408e37c01c54bf1`,
  `58dac7690c9ed669b2648049382321b50f7119d9`,
  `bfe8bedf1c5115615db3b3986a2fd7759c15c9d7` and
  `ac4eaa44fa501eba797818d8563e82c9b83ce8f0` close those findings.

Verified repository facts:

- diff equals `exact-path-allowlist.json` at 16 paths;
- merge base is fresh `main` head
  `c9bda459f10e682ec200fdfea8484d726c6c0057` and branch is 0 commits behind;
- all review threads opened before this evidence update are resolved;
- package activation remains unchanged and `default_registry()` remains empty;
- no GitHub write, non-GET HTTP, remote Git, merge, publication, deployment or
  activation authority is introduced.

Still required before merge:

- an independent review of the resulting exact head with no actionable finding;
- repository CI, CodeQL, agent3-diagnostics and agent3-full-diagnostics on the
  exact head. Connector-authored events have not created Actions runs, so no
  workflow success or full exact-head rerun is claimed here.

This evidence update changes the branch head. Final conclusions must bind to the
resulting exact head rather than the implementation candidate above.
