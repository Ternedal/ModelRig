# Trusted runtime staging and signed closures

The original Slice 10A stager proved deterministic staging for one executable.
Slice 10B made its receipt mandatory in the public Tier-A path. Slice 10D extends
that boundary to an independently signed, command-specific set of exact files and
a reviewed workspace-relative working directory.

The staging code cannot create a process, register a ModelRig tool, write to
GitHub, alter feature switches, merge, release or deploy.

## Legacy executable staging

`TrustedRuntimeStager` remains the narrow single-executable primitive used by the
earlier contract. It verifies an operator-bound executable and publishes it under:

```text
.kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
```

It produces `kaliv-development-runtime-staging-receipt/v1`. This contract remains
useful as a low-level staging primitive, but the Slice 10D runtime path now requires
the stronger signed-closure flow below.

## Signed runtime closure

`RuntimeClosureManifest` describes one command's complete reviewed file set:

- task ID, canonical task SHA and base commit;
- command ID and tool ID;
- catalog, toolchain, execution-lease and workspace identities;
- a hashed identity for the separate trusted runtime root;
- exact entrypoint relative path;
- exact workspace-relative working directory;
- sorted file paths, SHA-256 values and byte sizes;
- exact total file bytes.

`HmacRuntimeClosureSigner` wraps this manifest in
`kaliv-development-signed-runtime-closure-manifest/v1`. The key ID and signature
are separate from the task and physical-isolation evidence. A valid signature does
not authorize another command, cwd, lease, workspace or base commit because all of
those fields are inside the signed canonical payload.

HMAC is appropriate only while its secret is protected by the independent operator
boundary. A secret placed in the agent workspace destroys that independence claim.

## Path and tree safety

Every relative path is validated before filesystem access. The closure rejects:

- absolute paths, `..`, `.`, backslashes and NUL;
- NTFS alternate-data-stream syntax;
- trailing spaces or dots;
- Windows device names such as `CON`, `NUL`, `COM1` and `LPT1`;
- duplicate paths and Windows case-fold collisions;
- a file path that is also the parent of another manifested file;
- more than 512 files, per-file overflow or total closure overflow.

The trusted runtime root and workspace must be separate absolute directory trees
without symlink or junction components. Source files must be regular, non-empty,
physically inside the trusted root and match the signed hash and size. The signed
entrypoint must additionally match the exact operator toolchain binding.

## Deterministic closure destination

The complete closure is staged under:

```text
.kaliv/runtime-closures/<tool-id>/<manifest-sha256>/...
```

No model-selected argument chooses this location. Parent directories are built one
component at a time and rejected if a component is a link, junction or non-directory.
Each file is copied to a private temporary file, hashed during copying, flushed,
fsynced and atomically published without overwrite. Existing identical bytes can
be reused; existing different bytes fail closed.

The publisher removes its private hardlink name before locking the final file,
avoiding the Windows read-only hardlink-ordering failure previously caught in the
single-executable stager.

## Staging receipt and revalidation

A successful stage emits
`kaliv-development-runtime-closure-staging-receipt/v1`, binding:

- exact task, command, catalog, toolchain and lease;
- signed workspace authority;
- manifest and signed-manifest hashes;
- deterministic closure root and staged entrypoint;
- working directory;
- complete exact file list and total bytes.

Verification performs a full recursive walk. Missing and unmanifested files fail
closed. Files must be regular, link-free and have exactly one hardlink. Every file
is rehashed and resized. `bind_for_launch` then creates a new one-command leased
registry whose only runtime change is `argv[0]` pointing at the staged entrypoint.
Arguments, cwd, timeout, environment, lease, catalog, toolchain and attestation are
preserved.

The launch plan stores the receipt hash and both closure hashes. Immediately before
`CreateProcessW`, the private executor walks and rehashes the closure again. A
persisted staging receipt cannot authorize changed bytes or an extra file.

## Working directory

The catalog supplies the only allowed cwd. `.` denotes the workspace root; another
value must be a normalized workspace-relative descendant. Planning binds both the
relative value and canonical physical directory into
`working_directory_sha256`.

The directory is checked for existence, containment, links, junctions and reparse
points during planning and again at process creation. The output-capture wrapper
may replace the lower launcher's verified workspace-root `lpCurrentDirectory` only
with that exact prevalidated descendant.

## Deliberate limitations

This slice does not yet:

- discover transitive imported DLLs or build Python/Go runtime closures
  automatically;
- prove that the staged closure remains read-only for the complete child lifetime;
- provide a general model-authored manifest or arbitrary executable arguments;
- produce a complete Git-aware development `CommandReceipt`;
- activate any registered ModelRig command;
- replace the selected rig's physical eleven-probe I0b campaign;
- grant GitHub write, merge, release or deployment authority.

The native Windows contract currently proves a two-file closure, distinct
command/cwd signature identities, actual nested `backend/` cwd at `CreateProcessW`,
bounded parallel output capture and timeout EOF cleanup through the same public
runtime path.
