# DC-L03 exact-head validation

Status: **runtime candidate validated; resulting evidence head pending workflows and independent review**

Validated runtime and regression candidate:
`fe415f0562f2e3d57d600c80e33673b92b58bfde`.

Base and scope:

- base: `main @ c9bda459f10e682ec200fdfea8484d726c6c0057`;
- complete base diff: exactly the 16 paths in `exact-path-allowlist.json`;
- branch distance: 0 commits behind `main`;
- package activation unchanged and `default_registry()` remains empty;
- no merge, release, deployment or activation authority.

The validated runtime authority includes:

- reconstructed DevelopmentTask, catalog, toolchain and isolation-attestation snapshots;
- one strict private execution-task snapshot across resolution, sandbox creation,
  budgets, verification, cleanup and receipt identity;
- private verifier proof with post-callback canonical revalidation;
- immutable task-bound registries;
- descriptor-bound Linux executable verification with no-follow, nonblocking,
  bounded reads and sealed memfd invocation;
- an attested and pinned Python interpreter for the Landlock/seccomp bootstrap;
- fixed process values for `PATH`, `LANG`, `LC_ALL`, `LC_CTYPE` and `TZ` on every
  accepted catalog entry;
- fail-closed rejection of `GOTOOLCHAIN` and every `tool_id="go"` until the full
  `GOROOT/pkg/tool` helper chain can be attested and pinned;
- a fixed-host HTTPS GET-only GitHub boundary with explicit TLS trust roots,
  redirects and environment proxy authority disabled;
- exact-SHA and protected-path checks before transport;
- one monotonic deadline covering setup, request output, status, headers, chunk
  framing and response body, including cancellation and reconnect prevention;
- bounded JSON/base64 handling, decoded Git-blob identity verification and strict
  receipt/schema reload validation.

Runtime blobs on `fe415f0562f2e3d57d600c80e33673b92b58bfde`:

- catalog: `062e0b2591662412c3aa7bfb6345ac86c58425e4`;
- DC-L03 regressions: `c35efd0456088119fca272c2c9ff6b86fc6b6e28`.

Repository workflows passed on that exact runtime candidate:

- `ci` run `31156740333`;
- `codeql` run `31156738980`;
- `agent3-diagnostics` run `31156739176`;
- `agent3-full-diagnostics` run `31156738930`.

The full repository log, normal Python suite, DevControl foundation tests and
final boundary regressions all passed. The focused DC-L03 suite now proves that:

- the reviewed catalog contains only the three Python-backed command IDs;
- `modelrig.backend.vet` and `modelrig.backend.tests` are absent;
- direct construction of a Go command spec is rejected before materialization;
- a task granting a removed Go command cannot materialize it;
- `GOTOOLCHAIN=local` is no longer accepted as catalog environment authority;
- caller mutation cannot retarget task, catalog, toolchain, verifier proof,
  executable object, bootstrap interpreter, locale/timezone or GitHub authority.

Review history remains recorded in the pull-request threads. Most recently:

1. review of `5c7a969f55f763e37f95aa6f75332c1a9146705c` found an unpinned sandbox
   bootstrap and ambient locale/timezone authority; `b52e42728fed447981a24b64554a22a0abea175f`
   closed both;
2. review of `b52e42728fed447981a24b64554a22a0abea175f` found that the pinned Go driver
   still launched mutable unpinned helpers from its compiled-in GOROOT;
3. `fe415f0562f2e3d57d600c80e33673b92b58bfde` closes that finding fail-closed by
   removing Go commands and rejecting all Go command specs until complete helper
   attestation exists.

This documentation update changes the branch head without changing runtime code
or the 16-path set. Final conclusions must bind to the resulting evidence head,
which requires its own successful workflows and fresh independent review.