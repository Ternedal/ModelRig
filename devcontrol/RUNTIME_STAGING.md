# Trusted runtime staging

Slice 10A adds an auditable preparation primitive for Tier-A command runtimes.
It remains dormant and does not execute a process, activate a tool, write to
GitHub, alter a feature switch, merge, release or deploy anything.

## Authority chain

`TrustedRuntimeStager` accepts only:

1. an already validated `kaliv-development-task/v1` task;
2. a `LeasedCommandRegistry` issued from the exact signed physical-isolation
   authority;
3. one command ID already granted by that task;
4. the command's immutable catalog specification and exact toolchain binding;
5. a separate absolute operator-controlled runtime root;
6. the workspace root named by the signed physical report.

The operator runtime root and development workspace must be separate directory
trees. The source executable must be a regular non-empty file physically inside
the operator root, contain no symlink or junction component, and match the exact
SHA-256 already stored in the toolchain binding.

## Deterministic destination

The executable is staged under:

```text
.kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
```

No task, model or command argument chooses that path. Parent directories are
created one component at a time and rejected if any component becomes a link,
junction or non-directory.

The copy is written to a private temporary file, hashed while copying, flushed,
fsynced and then published with an atomic no-overwrite hard link. An existing
matching destination is reusable. An existing destination with different bytes
fails closed and is never overwritten.

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

## Deliberate non-goals

This slice does not:

- turn the receipt into executable authority;
- modify `run_verified_tier_a_command`;
- add the staging module to the signed Tier-A import/toolhost bundle;
- export staging through the package top-level;
- stage dependent DLLs, Python standard libraries, Go toolchain trees or other
  runtime closure;
- capture stdout or stderr;
- create a `CommandReceipt`;
- perform the physical eleven-probe I0b campaign.

Keeping the module outside the Tier-A import path is intentional. When a later
slice consumes the receipt during launch, `runtime_staging.py` must be added to
the signed toolhost bundle in the same change, and the physical evidence must be
regenerated for that new bundle hash.

## Next safe slice

The next step is to integrate this receipt into the single fresh-verification
runtime path and add bounded stdout/stderr capture. That integration must include
`runtime_staging.py` in the signed Tier-A authority bundle and must not introduce
a second public plan-execution function.
