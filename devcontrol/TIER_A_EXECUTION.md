# Tier-A execution bridge

The Development Control Plane is dormant and fail closed. Slices 9 through 10D
connect fresh signed Windows-isolation evidence to one private AppContainer launch
path. Slice 10D adds a signed exact-file runtime closure and an exact
workspace-relative working directory without introducing another executor.

Nothing here registers a ModelRig tool, activates Agent 3 or Agent 4, writes to
GitHub, merges, releases or deploys code.

## Executable authority chain

A command can cross the Windows process boundary only through this complete chain:

1. `kaliv-development-task/v1` grants one reviewed command ID plus fixed runtime
   and output budgets.
2. The command exists in an immutable `ModelRigCommandCatalog`.
3. An operator `Toolchain` binds its tool ID to one absolute source entrypoint and
   SHA-256.
4. `WindowsPhysicalIsolationVerifier` reloads the exact signed report referenced by
   the task attestation.
5. Signature, freshness, task SHA, base SHA, catalog SHA, toolchain SHA, boundary,
   network mode and all eleven physical probes are verified.
6. Verification issues `kaliv-development-execution-lease/v1`, binding the rig,
   workspace and complete Tier-A authority bundle.
7. A command-specific `kaliv-development-runtime-closure-manifest/v1` names the
   exact entrypoint, support files, sizes, hashes and workspace-relative cwd.
8. An independent HMAC signature produces
   `kaliv-development-signed-runtime-closure-manifest/v1`.
9. `RuntimeClosureVerifier` binds the signed closure to the exact task, command,
   catalog, toolchain, lease, workspace and trusted runtime root.
10. `TrustedRuntimeClosureStager` copies every manifested file to:

    ```text
    .kaliv/runtime-closures/<tool-id>/<manifest-sha256>/...
    ```

11. Staging emits
    `kaliv-development-runtime-closure-staging-receipt/v1`; the staged tree is
    rejected if a file is missing, extra, linked, hardlinked or changed.
12. A new one-command leased registry changes only `argv[0]` to the verified staged
    entrypoint. Fixed arguments, cwd, timeout, environment and lease remain exact.
13. `kaliv-development-tier-a-launch-plan/v3` binds manifest, signature, staging
    receipt, cwd identity, workspace, executable, timeout, output budget and the
    full authority-code identity.
14. Immediately before launch, the private executor rehashes the authority bundle,
    workspace identity, complete staged closure, entrypoint and working directory.
15. Windows creates the child suspended in a zero-capability AppContainer, with an
    exact three-handle inheritance list, then assigns the Job Object before resume.
16. stdout and stderr are drained concurrently to EOF, fully hashed and retained
    only within the signed output budget. Execution emits
    `kaliv-development-tier-a-execution-result/v1`.

A serialized launch plan is review evidence, not reusable execution authority.
Plans lacking a verified closure remain serializable for inspection but the only
runtime path rejects them.

## Runtime closure rules

Manifest paths are POSIX-style, relative and bounded. The parser rejects absolute
paths, traversal, backslashes, NUL, NTFS alternate-data-stream syntax, trailing
dot/space components and Windows reserved device names. File paths must be sorted
and unique, cannot collide under Windows case folding, and cannot conflict with a
parent path that is itself a file.

The trusted runtime root and workspace must be separate link-free directory trees.
Every source file must be regular, non-empty, physically inside the trusted root
and match its manifest hash and size. The entrypoint must also match the operator
toolchain binding.

Staging is deterministic and no-overwrite. Files are hashed while copied, flushed,
fsynced and atomically published. Existing different bytes fail closed. A complete
post-stage walk rejects unmanifested entries. Destination files must have exactly
one hardlink and are rehashed again immediately before process creation.

These checks guarantee the exact signed bytes at staging and prelaunch. They do
not yet keep the staged tree read-only with a dedicated ACL for the entire child
lifetime.

## Working-directory authority

The catalog still chooses cwd; the model or caller cannot supply it dynamically.
A cwd is either `.` or a normalized repository-relative path. Absolute paths,
traversal, backslashes, links, junctions, reparse points, missing directories and
workspace escapes fail closed.

The launch plan records `working_directory_sha256`, derived from the canonical
workspace-relative value and its exact physical path. The directory is validated
when planning, when building the output-capture wrapper and immediately inside the
`CreateProcessW` wrapper. The wrapper accepts only the lower launcher's already
verified workspace root and may replace it only with the prevalidated descendant.
Executable selection, arguments, environment, AppContainer identity and Job Object
configuration remain outside the wrapper.

## Native output and timeout boundary

The child inherits only read-only `NUL` stdin plus stdout and stderr pipe write
handles through `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`. Unrelated inheritable parent
handles cannot enter the child.

Two non-daemon reader threads drain the streams concurrently. Every byte contributes
to the full stream SHA-256 and total byte count. Retained memory is split
predictably:

```text
stdout prefix = ceil(max_output_bytes / 2)
stderr prefix = floor(max_output_bytes / 2)
```

Binary prefixes are canonical base64. On timeout, the complete Job Object is
terminated, the process is reaped and both streams reach EOF before a non-passing
result is finalized. `TierAExecutionTimeout` carries that evidence so timeout
output remains auditable but cannot be mistaken for success.

## Code identity

`tier_a_toolhost_sha256` v4 covers all modules that can issue, transform, stage,
launch or report Tier-A authority, including the runtime-closure model, verifier,
stager, launch-plan v3, cwd binding, output capture and public facade. Every report
issued for an earlier authority bundle is therefore invalid.

## Current limitations

- No registered ModelRig tool calls `run_verified_tier_a_command`.
- Hosted Windows CI uses synthetic signed evidence; it does not replace the
  selected rig's independent eleven-probe I0b campaign.
- The closure is exact-file based, not yet an automatically discovered transitive
  PE/DLL, Python or Go runtime closure.
- Staged bytes are revalidated before launch, but a lifetime read-only ACL and
  immutable mounted runtime are not yet proven.
- `TierAExecutionResult` is not a complete development `CommandReceipt`; Git
  before/after identity and reset evidence remain owned by the separate command
  executor.
- No branch push, pull-request write, merge, release, settings, feature-switch or
  deployment authority is granted.

The next safe unit is a reviewed closure builder for one concrete self-contained
command, followed by lifetime runtime-file immutability. It must preserve the same
fresh signed-evidence, exact staging, cwd, output and Job Object boundaries.
