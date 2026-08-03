# Trusted runtime staging

Slice 10A adds deterministic runtime staging. Slice 10B makes the resulting
receipt mandatory in the single public Tier-A execution path. The stager itself
still cannot launch a process, activate a tool, write to GitHub, alter a feature
switch, merge, release or deploy anything.

## Authority chain

`TrustedRuntimeStager` accepts only:

1. an already validated `kaliv-development-task/v1` task;
2. a `LeasedCommandRegistry` issued from exact signed physical evidence;
3. one command ID already granted by that task;
4. the command's immutable catalog specification and exact toolchain binding;
5. a separate absolute operator-controlled runtime root;
6. the workspace root named by the signed physical report.

The operator runtime root and workspace must be separate directory trees. The
source executable must be a regular, non-empty file physically inside the
operator root, contain no symlink or junction component and match the exact
SHA-256 stored in the toolchain binding.

## Deterministic destination

The executable is staged under:

```text
.kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
```

No task, model or command argument chooses this path. Parent directories are
created one component at a time and rejected if any component becomes a link,
junction or non-directory.

The copy is written to a private temporary file, hashed while copying, flushed,
fsynced and published with an atomic no-overwrite hard link. An existing matching
destination is reusable. An existing destination with different bytes fails
closed and is never overwritten.

## Receipt

A successful stage produces a canonical
`kaliv-development-runtime-staging-receipt/v1` artifact binding:

- task ID, canonical task SHA-256 and base commit;
- command ID and tool ID;
- catalog, toolchain and execution-lease SHA-256;
- signed workspace-root authority SHA-256;
- a hash of the canonical operator source path, without disclosing that path;
- executable SHA-256 and byte size;
- the deterministic workspace-relative destination.

Reload verification rebinds every authority field and rehashes both the operator
source and staged copy. Changing either side invalidates the receipt.

## Launch binding

`bind_for_launch` accepts only a valid receipt plus the same leased registry, task
and command ID. It verifies the receipt again, resolves the staged executable and
constructs a new one-command `LeasedCommandRegistry`.

Only `argv[0]` changes. Fixed arguments, cwd, timeout, environment, lease, catalog,
toolchain and attestation are copied exactly from the original materialized
command. The original registry is never mutated.

The public `run_verified_tier_a_command` path now performs this sequence every
time it is called:

1. reload and verify signed physical evidence;
2. issue a fresh execution lease;
3. stage the operator-bound executable;
4. reverify the receipt and bind the staged registry;
5. build a fresh launch plan;
6. rehash code, workspace and executable;
7. enter the zero-capability AppContainer and Job Object boundary.

There is still no public function that executes a persisted launch plan.

## Signed code identity

`runtime_staging.py` is now included in `tier_a_toolhost_sha256`. Any staging-code
change therefore invalidates older physical reports and prevents a lease from
being issued until fresh exact-bundle evidence is collected and attested.

The staging module remains absent from the package top-level exports. Its import
inside the public runtime is local to avoid a circular package initialization
path, not to exclude it from signed authority.

## Deliberate non-goals

This slice does not:

- stage dependent DLLs, Python standard libraries, Go toolchain trees or another
  complete runtime closure;
- support non-root command working directories;
- capture or expose stdout and stderr;
- create a complete `CommandReceipt`;
- activate a registered ModelRig tool;
- perform the selected rig's physical eleven-probe I0b campaign;
- grant GitHub write, merge, release or deployment authority.

## Next safe slice

The next step is bounded native stdout/stderr capture. Pipe handles, inheritance,
reader lifecycle, timeout cleanup and byte budgets must be proven together in the
real Windows isolation gate without introducing a second public execution path.
