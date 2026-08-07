# DC-L03 exact-head validation

Status: **authority candidate hardened; exact-head workflow gates pending**

Current authority implementation/regression candidate:
`b74701c41ef05775597b930aaf23b919df1a7533`.

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
- an owned HTTPS connection supervised from connection setup through request,
  HTTP status, headers, chunk framing and response body under one monotonic
  deadline;
- explicit connection establishment followed by cancellation/deadline checks
  before any authenticated GET may be sent;
- `auto_open=0` before the sole explicit connection, preventing `http.client`
  from reconnecting after cancellation closes the socket between authority
  checks and request output;
- a single process-global setup slot so an uninterruptible DNS/setup worker
  cannot accumulate and further attempts fail closed while it remains pending;
- socket shutdown/close, response close and connection close on deadline expiry;
- fail-closed handling when a deadline-capable transport socket is unavailable;
- exact-SHA and protected-path checks before transport, bounded JSON/base64
  handling and decoded Git-blob identity verification;
- strict receipt runtime/schema identity, status and repository validation.

Latest landed authority blobs:

- catalog: `e562bbbf9acb6833279491303b6ab7b508bc3e0e`;
- GitHub read transport: `dd30559d6b95a155de4a80def6454400719c9889`;
- receipt schema: `40615abb093d890a98391ad8dc38d90fb8166c2d`;
- workflow contract/regressions: `d1b5c9b97d3b3a3f9d20eea16e28126b75bea9ed`.

The latest complete focused DC-L03 run before the final environment/deadline
hardening produced **26/26 passing tests**. Existing public test surfaces were
preserved while additional executable contract regressions and direct validation
now cover:

- rejection of `GOROOT=.`, `PYTHONUSERBASE=.`, `GOTOOLCHAIN=auto` and an
  attacker-selected PATH;
- automatic fixed-PATH insertion for a caller-supplied `env={}` spec;
- a `read1()` call that blocks internally until socket cancellation;
- a `getresponse()` call that blocks while reading HTTP status/headers;
- a `connect()` call that remains blocked beyond the deadline, followed by proof
  that no authenticated request is sent after delayed setup completion;
- rejection of a second setup attempt while the first unresolved setup worker
  still owns the single bounded setup slot;
- a race where request output pauses after setup, cancellation closes the socket,
  and delayed continuation proves there is no automatic reconnect or auth send;
- wall-clock rejection with socket, response and connection closure;
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
- review of `3483ac687a267d6ec31aa71eaa4896baa5604d74` found omitted PATH authority and
  status/header framing outside the supervisor; candidate
  `ac4eaa44fa501eba797818d8563e82c9b83ce8f0` closed them;
- review of `3a0a99ab987ec22219787a086a97fc7cf13f9998` found that a blocked DNS/setup
  worker could later send after the caller timed out and repeated calls could
  accumulate workers; candidate `33b762a9145dedf93365921b359477f81d22eb5f`
  closed that finding;
- author-side race audit then found `http.client` could auto-reconnect if the
  socket closed between the final check and request output; candidates
  `c147d12c295f6ee5844b757e13c91ac521105977` and
  `b74701c41ef05775597b930aaf23b919df1a7533` close that race.

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
