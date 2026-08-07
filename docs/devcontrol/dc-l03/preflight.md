# DC-L03 preflight

Status: **implementation candidate authored; exact-head CI pending**

## Base and dependency lock

- Branch base: `main @ c9bda459f10e682ec200fdfea8484d726c6c0057`
- DC-L01: merged through PR #355
- DC-L02: merged through PR #372
- Locked source reference: PR #338 at
  `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`
- Branch policy: fresh, non-stacked DC-L03 branch

## Scope

The complete candidate diff must equal the 16 paths in
`exact-path-allowlist.json`:

- 5 assigned DC-L03 source paths;
- 3 progressive package/execution/CI-coverage surfaces;
- 8 required slice-control artifacts.

The pre-existing command executor is a progressive surface only to carry one
strict private `DevelopmentTask` snapshot through its already-landed execution
path. DC-L03 adds no command ID, generic process launcher or activation path.

## Authority boundary

DC-L03 may introduce an immutable command catalog, exact executable hash
bindings, isolation attestations and a fixed-host GET-only GitHub adapter.

It may not introduce:

- an HTTP method other than GET;
- a caller-controlled host, repository, ref or generic URL fetch;
- GitHub mutation or remote Git;
- token persistence or token material in receipts;
- a non-empty `default_registry()`;
- physical isolation approval;
- Windows process containment or executable verification;
- new process-launch authority, publication, merge, release, deployment or
  activation.

## Load-bearing closures added during projection

1. GitHub file bytes must verify against the returned Git blob SHA.
2. Environment proxies and redirects are disabled in the default transport.
3. Catalog environment cannot introduce loader, Python-path, toolchain, Git or
   child-tool PATH authority.
4. POSIX executable hashing uses a no-follow descriptor, regular-file checks,
   bounded streaming and before/after identity verification.
5. Windows executable verification remains fail-closed pending later native
   containment slices.
6. One reconstructed task snapshot is used for command resolution, sandbox
   creation, budgets, post-run verification, cleanup verification and receipt
   identity, so caller mutation cannot retarget execution after authorization.
7. GitHub connection setup, request output, headers, chunk framing and body reads
   are covered by one monotonic deadline with bounded setup workers and no
   automatic reconnect after cancellation.
