# DC-L03 exact-head validation

Status: **authority candidate hardened; exact-head workflow gates pending**

Current authority implementation/regression candidate:
`5eb237398cd4b9867e50bc42656476835ca4a057`.

The candidate keeps the complete 16-path allowlist and includes:

- reconstructed DevelopmentTask, catalog, toolchain and attestation snapshots;
- private isolation-verifier proof plus post-callback canonical revalidation;
- sealed exact-task command registries and reviewed verifier retention;
- Linux no-follow, nonblocking, bounded executable reads and sealed memfd launch;
- process-lifetime descriptor retirement and fail-closed non-Linux verification;
- a fixed-value environment positive list containing `CI=1`,
  `MODELRIG_DEVCONTROL=1`, `GOTOOLCHAIN=local` and the reviewed child-tool
  `PATH=/usr/bin:/bin`;
- fixed-host HTTPS GET-only GitHub reads with redirects and proxies disabled;
- explicit system TLS roots independent of environment CA overrides;
- one monotonic wall-clock deadline covering response-body reads;
- a supervised reader thread so blocking chunk framing inside `read1()` cannot
  outlive the caller deadline;
- socket shutdown/close and response close on deadline expiry;
- fail-closed response handling when the transport cannot expose a socket on
  which cancellation and timeouts can be enforced;
- exact-SHA and protected-path checks before transport, bounded JSON/base64
  handling and decoded Git-blob identity verification;
- strict receipt runtime/schema identity, status and repository validation.

Latest landed authority blobs:

- catalog: `1f312db26214153052c923adbb06896124f21b6a`;
- GitHub read transport: `d6ffca324ca2f69db256814ec08f08a714feb00c`;
- receipt schema: `40615abb093d890a98391ad8dc38d90fb8166c2d`;
- workflow contract/regressions: `f20d6d73cbadebab5d6c98e3f4ac0586a81f53ba`.

The latest complete focused DC-L03 run before the final environment/deadline
hardening produced **26/26 passing tests**. Additional executable contract
regressions and direct validation now cover:

- rejection of `GOROOT=.`, `PYTHONUSERBASE=.`, `GOTOOLCHAIN=auto` and an
  attacker-selected `PATH`;
- presence of the fixed `/usr/bin:/bin` PATH on reviewed catalog commands;
- a `read1()` call that blocks internally until the socket is cancelled;
- wall-clock rejection in approximately 0.05 seconds, response/socket closure,
  preserved successful reads and preserved byte-budget rejection.

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
  chunk-framing work occurring inside one `read1()` call; candidates
  `59bbd4a113fe13d274b05ae8fee8f789ec80b4cd`,
  `e73934c1bc6536e0b89b66eb30819ee7f602210b` and
  `5eb237398cd4b9867e50bc42656476835ca4a057` close those findings.

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
