# DC-L03 exact-head validation

Status: **authority candidate hardened; exact-head workflow gates pending**

Current authority implementation/regression candidate:
`b7cabc3524a75d980cd5e0710b2acfeed7a15eb2`.

The candidate keeps the complete 16-path allowlist and includes:

- reconstructed DevelopmentTask, catalog, toolchain and attestation snapshots;
- private isolation-verifier proof plus post-callback canonical revalidation;
- sealed exact-task command registries and reviewed verifier retention;
- Linux no-follow, nonblocking, bounded executable reads and sealed memfd launch;
- process-lifetime descriptor retirement and fail-closed non-Linux verification;
- a fixed-value environment positive list containing only `CI=1`,
  `MODELRIG_DEVCONTROL=1` and `GOTOOLCHAIN=local`;
- fixed-host HTTPS GET-only GitHub reads with redirects and proxies disabled;
- explicit system TLS roots independent of environment CA overrides;
- one monotonic wall-clock deadline covering response-body reads, with the
  underlying socket timeout reset to the remaining budget before every read;
- fail-closed response handling when the transport cannot expose a socket on
  which the deadline can be enforced;
- exact-SHA and protected-path checks before transport, bounded JSON/base64
  handling and decoded Git-blob identity verification;
- strict receipt runtime/schema identity, status and repository validation.

Latest landed authority blobs:

- catalog: `139019db325b48d7137ecf16ee594b3146b5ebc6`;
- GitHub read transport: `cce71c6bc4aae6068ada7ba6b7a85075d4853441`;
- receipt schema: `40615abb093d890a98391ad8dc38d90fb8166c2d`;
- workflow contract/regressions: `a04459eefe97ac7101e2dd80c58da682d8d7b256`.

The latest complete focused DC-L03 run before the final environment/deadline
hardening produced **26/26 passing tests**. The final two findings are covered by
additional executable contract regressions that:

- reject `GOROOT=.`, `PYTHONUSERBASE=.` and `GOTOOLCHAIN=auto` while preserving
  the reviewed fixed environment values;
- simulate an endless slow-drip response and require monotonic wall-clock
  rejection, response closure and a decreasing socket timeout.

Review history:

- review of `96967da26134cb68cc59242fbee004cc403228ba` found mutable verifier proof and
  blocking FIFO-open issues; candidate `660e85dcb0281cdbc0991d9cb5c06a7f0064ff6f`
  closed both;
- author-side schema audit found receipt repository syntax looser than runtime;
  candidate `157b158011d120797a230912f1c96a23babb1ace` aligned them;
- review of `002306223eb172351f9bfd1665dc1d5f9bdcfd2a` found remaining interpreter/
  toolchain environment authority and missing end-to-end response-read deadline;
  candidates `c95a877fbeded87597727b090327ff4c57c3ffca`,
  `9a644231bd59c9e8a6d32ec504476b92992e1d7a`,
  `ed5a646b3a457478bdaea4cc7bbcb9b64af12e6c` and
  `b7cabc3524a75d980cd5e0710b2acfeed7a15eb2` close those findings.

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
