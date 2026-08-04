# Slice 10F — runtime closure lifetime guard

Slice 10F closes the mutation window between final closure verification and the
end of the complete Windows Job Object process tree. It adds no second executor,
no new command authority and no production activation.

## Invariant

From the final prelaunch verification until the Job Object handle is confirmed
closed, the exact staged runtime closure must remain:

- byte-identical to the signed manifest;
- free of added, removed, renamed, linked or replaced entries;
- readable and executable by the exact zero-capability AppContainer;
- non-writable and non-deletable by the AppContainer and ordinary concurrent
  host processes.

The ordinary workspace outside the staged closure remains writable according to
the existing workspace policy. This allows test output and temporary repository
state without granting write access to executable runtime bytes.

## Guard acquisition

`WindowsRuntimeClosureLifetimeGuard.acquire` runs only inside the existing private
Tier-A execution path, after:

1. fresh signed physical evidence has issued an execution lease;
2. the signed runtime closure has been independently verified;
3. deterministic staging has completed;
4. the launch plan has rebound only `argv[0]` to the verified workspace copy;
5. the complete staged tree has passed its final prelaunch hash and structure
   verification;
6. the exact AppContainer profile and workspace ACL have been provisioned.

The guard reloads the receipt's exact file list and rejects missing or extra
files/directories, reparse points, symlinks, junctions, hardlinks, changed sizes
or changed hashes.

## Two independent Windows controls

### Protected read/execute DACL

Every closure directory and file receives a protected DACL containing only:

- read/execute access for the current operator account;
- read/execute access for the exact AppContainer package SID.

Write, append, delete and child-creation rights are absent. The DACL is applied by
handle, not by a path-only update after verification.

### Deny-write and deny-delete sharing handles

The control plane keeps every closure directory and file open with read sharing
only. New handles requiring write or delete sharing therefore fail while the
guard is alive. This blocks ordinary concurrent attempts to:

- overwrite either the entrypoint or a support file;
- replace or rename a manifested file;
- delete a file or directory;
- insert an unmanifested file into a closure directory.

Guard acquisition itself fails if an incompatible pre-existing handle prevents
these locks from being established.

## DACL restoration

Before applying the protected DACL, the guard opens each object with `WRITE_DAC`
and retains the original security descriptor. The original DACL and its protected
or inherited state are restored only after the Job Object has been confirmed
closed and the child process has been reaped.

If Job Object cleanup cannot be proven, the guard is quarantined in memory instead
of releasing the filesystem locks. This deliberately prefers a locked staged
runtime over reopening a mutation window while a process may still exist.

A DACL restoration or handle-close failure is a Tier-A execution failure. The
runtime cannot report success while cleanup authority is ambiguous.

## Native sabotage proof

The real-Windows gate compiles a statically linked helper and signs a two-file
closure. It proves both attack surfaces:

1. **AppContainer attack:** the child attempts entrypoint/support overwrite,
   support-file deletion, rename and injected-file creation. Every operation is
   denied while normal read/execute succeeds.
2. **Concurrent host attack:** a host thread waits until a long-running Job Object
   command signals readiness, then attempts the same overwrite, delete, rename and
   insertion operations. Every operation is denied until the command exits.

The gate then verifies every staged byte and tree entry is unchanged. Only after
the Job Object has ended can a new temporary file be created in the closure
directory, proving that the original DACL was restored rather than permanently
weakening or freezing the workspace.

The existing burst-output, nested-cwd and timeout/EOF proofs run through the same
guarded path.

## Authority identity

`worker/app/windows_runtime_guard.py` is included in
`tier_a_toolhost_sha256` **v5**. The domain change intentionally invalidates every
physical isolation report issued for authority bundle v4 or earlier. A new report
must bind the exact v5 code, task, catalog, toolchain, workspace and rig.

## Deliberate limits

The guard is designed for the unprivileged operator/AppContainer boundary used by
Tier-A. It does not claim resistance against a separate administrator or kernel
component with takeover, backup/restore or direct-volume privileges.

It also does not:

- discover transitive PE/DLL, Python or Go dependencies automatically;
- create or sign a runtime closure;
- register or activate a ModelRig tool;
- join runtime evidence to a complete Git-aware `CommandReceipt`;
- grant GitHub write, merge, release, settings or deployment authority.
