# DC-L03 preflight

Status: **implementation hardened; final exact-head workflows and independent review pending**

## Base and dependency lock

- Base: `main @ c9bda459f10e682ec200fdfea8484d726c6c0057`
- DC-L01: PR #355
- DC-L02: PR #372
- Locked source: PR #338 at `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`
- Complete diff: exactly the 16 paths in `exact-path-allowlist.json`

## Delivered boundary

DC-L03 delivers dormant command-catalog and attestation types plus a fixed-host,
GET-only GitHub read adapter. It grants no default command or process-launch
authority:

- `modelrig_command_catalog()` is empty;
- Python command specs fail closed until the complete interpreter runtime can be
  attested;
- Go command specs fail closed until the complete helper chain can be attested;
- the reserved sandbox helper cannot be used as a catalog command;
- future custom command objects must be sealed, hash-verified static ELF files
  with no `PT_INTERP` or `PT_DYNAMIC` dependency;
- `default_registry()` remains empty and package activation is unchanged.

## Load-bearing closures

1. Catalog, toolchain, task and isolation proof are reconstructed as immutable
   snapshots and rebound after the verifier callback.
2. Catalog environments use reviewed fixed values for `PATH`, locale and
   timezone and reject ambient loader, interpreter, Git and toolchain authority.
3. Linux executable verification is descriptor-bound, no-follow, nonblocking,
   size-bounded, hash-checked, inode-checked and sealed into a memfd.
4. The same static-runtime requirement applies to the sandbox helper and every
   future command executable.
5. GitHub reads use only `https://api.github.com`, GET, the exact task SHA and
   task-scoped paths; redirects, environment proxies and environment-selected
   TLS roots are rejected.
6. One monotonic deadline covers connection setup, request output, response
   framing and body reads with cancellation and reconnect prevention.
7. Decoded content is verified against its Git blob object ID before a strict,
   token-free receipt is issued.

## Exclusions

No GitHub write, remote Git, caller-controlled host/ref, token persistence,
Python or Go command execution, generic launcher, Windows containment, physical
isolation approval, publication, merge, release, deployment or activation
belongs to DC-L03.
