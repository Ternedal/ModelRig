# Tier-A execution bridge

The Development Control Plane is dormant and fail closed. Slices 9 through 10G
connect fresh signed Windows-isolation evidence to one private AppContainer launch
path, protect the exact runtime closure for the complete Job Object lifetime and
join the resulting native evidence to deterministic Git before/after/reset state.

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
12. A one-command leased registry changes only `argv[0]` to the verified staged
    entrypoint. Fixed arguments, cwd, timeout, environment and lease remain exact.
13. `kaliv-development-tier-a-launch-plan/v3` binds manifest, signature, staging
    receipt, cwd identity, workspace, executable, timeout, output budget and the
    full authority-code identity.
14. Immediately before launch, the private executor rehashes the authority bundle,
    workspace identity, complete staged closure, entrypoint and working directory.
15. `WindowsRuntimeClosureLifetimeGuard` verifies the tree again, applies a
    protected read/execute DACL and opens every closure file and directory with
    sharing that denies write and delete access.
16. Windows creates the child suspended in a zero-capability AppContainer, with an
    exact three-handle inheritance list, then assigns the Job Object before resume.
17. The runtime guard remains owned by the private executor until the Job Object is
    confirmed closed and the child has been reaped. If Job cleanup cannot be
    proven, the guard is retained rather than reopening the runtime tree.
18. stdout and stderr are drained concurrently to EOF, fully hashed and retained
    only within the signed output budget. Execution emits
    `kaliv-development-tier-a-execution-result/v1`.
19. Only after process-tree completion are the original closure DACLs restored and
    deny-write/delete-sharing handles closed.
20. The Git-aware receipt orchestrator removes deterministic runtime staging,
    captures the workspace after state and resets any mutation to the exact task
    base before it can emit a complete command receipt.

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

On Unix, staged files use mode `0555`. On Windows, the DOS read-only attribute is
not treated as a security primitive because the same user can clear it and it
prevents deterministic cleanup after execution. Windows staging therefore remains
executable and removable; actual lifetime immutability is supplied by the
protected DACL and deny-write/delete-sharing handles acquired before launch.

Slice 10E adds a reviewed standalone Go implementation of
`modelrig.version.check` plus an isolated one-command catalog and an unsigned
single-file closure builder. The default ModelRig catalog remains unchanged, so
selecting that standalone profile requires a new catalog hash, toolchain, physical
report, lease and independently signed closure. See `VERSION_CHECK_CLOSURE.md`.

## Runtime lifetime immutability

Slice 10F protects only the exact staged closure subtree; the ordinary workspace
retains its existing write policy. After final verification, each closure object
is opened by handle and its original DACL is retained. A protected DACL grants
read/execute only to the current operator SID and the exact AppContainer package
SID. Open file and directory handles permit read sharing only, denying new write
or delete-sharing opens.

Together these controls block ordinary AppContainer and concurrent host attempts
to overwrite, replace, rename, delete or extend the runtime tree. Guard acquisition
fails closed if an incompatible pre-existing handle prevents the required sharing
lock. Original DACLs are restored only after Job Object closure. See
`RUNTIME_LIFETIME_GUARD.md` for the full lifecycle and sabotage proof.

The boundary does not claim resistance against a separate administrator or kernel
component with takeover, backup/restore or direct-volume privileges.

## Git-aware command receipt

Slice 10G adds `run_single_verified_tier_a_command_with_receipt`. It is an
orchestration layer, not a process executor. It has no `command_id` or arbitrary
argument parameter and accepts only a task with one exact allowed/required command.
It invokes only `run_verified_tier_a_command`.

Before execution, the workspace must be an exact link-free Git worktree at the
task base. A staged candidate patch may exist; unstaged and untracked input is
rejected. Fixed Git commands produce
`kaliv-development-git-workspace-snapshot/v1`, binding:

- `HEAD` SHA;
- staged binary/full-index diff SHA-256 and byte count;
- unstaged binary/full-index diff SHA-256 and byte count;
- NUL-delimited untracked-path SHA-256 and count.

External diff, text conversion, rename detection, shell execution and unbounded
Git output are disabled.

After the native process tree and runtime guard are fully closed, deterministic
runtime staging is removed and the after snapshot is captured. Any difference
from the before snapshot makes the receipt non-passing and triggers fixed
`git reset --hard <task.base_sha>` plus `git clean -fd`. A final reset snapshot must
prove exact-base `HEAD`, zero staged/unstaged patch bytes and zero untracked paths.
Reset ambiguity fails closed.

`kaliv-development-tier-a-command-receipt/v1` embeds the complete native execution
result, before/after snapshots, optional reset snapshot and strict consistency
flags. It passes only when the native result passes, Git state is unchanged and no
reset was required. A timeout retains complete output and Git evidence but remains
non-passing. See `TIER_A_COMMAND_RECEIPT.md`.

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
output remains auditable but cannot be mistaken for success. Runtime locks remain
held through the same timeout and cleanup path.

## Code identity

`tier_a_toolhost_sha256` v6 covers all modules that can issue, transform, stage,
lifetime-lock, launch, join Git evidence or report Tier-A authority, including the
Windows runtime guard, command-receipt orchestrator, runtime-closure model,
verifier, stager, launch-plan v3, cwd binding, output capture and public facade.
Every report issued for authority bundle v5 or earlier is therefore invalid.

## Proofs

Portable tests cover canonical snapshots and receipts, staged-patch preservation,
mutation/reset behavior, timeout evidence, multi-command rejection, dirty-input
rejection and reset after execution error.

The native Windows gate creates a real temporary Git repository, compiles the
static helper, issues synthetic signed eleven-probe evidence and invokes the
receipt orchestrator through the actual AppContainer, Job Object, output capture
and lifetime guard. It proves the staged patch is unchanged, deterministic runtime
staging is removed before the after snapshot and the receipt round-trips
canonically.

Synthetic CI evidence verifies software wiring only and does not replace an
independent physical campaign on the selected host.

## Current limitations

- No registered ModelRig tool calls the Tier-A runtime or receipt orchestrator.
- The selected host still needs a fresh independent I0b campaign for authority
  bundle v6.
- The closure is exact-file based, not yet an automatically discovered transitive
  PE/DLL, Python or Go runtime closure.
- The lifetime guard proves the ordinary unprivileged operator/AppContainer
  boundary, not resistance to a separate administrator or kernel component.
- Receipt evidence is structural; independent semantic AI review is not yet
  implemented.
- No branch push, pull-request write, merge, release, settings, feature-switch or
  deployment authority is granted.

The next safe unit should add independent semantic review over a completed receipt
and the already staged patch. It must consume immutable evidence only, must not
execute commands, mutate the workspace or gain GitHub/merge/release authority.
