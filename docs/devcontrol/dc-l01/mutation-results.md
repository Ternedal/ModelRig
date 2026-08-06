# DC-L01 mutation results

Focused controlled mutations were executed against the projected DC-L01 seams
before publication. Each mutation was applied alone and the corresponding guard
was required to turn red.

| Load-bearing property | Controlled mutation | Result |
|---|---|---|
| Workspace binds exact task base SHA | Replace `if head != task.base_sha` with `if False` | **RED** — wrong SHA was accepted |
| New workspace must be clean | Replace the clean-state condition with `if False` | **RED** — dirty status was accepted |
| Command receipts bind exact task SHA | Remove source/sandbox `rev-parse HEAD` checks | **RED** — receipt can name another base |
| Patch receipts bind exact task SHA | Remove the patch HEAD check | **RED** — patch can apply against another base |
| Fixed argv authority is immutable | Retain caller-owned argv list | **RED** — post-registration mutation changes execution |
| Command cwd authority is canonical | Validate only normalized path parts | **RED** — ambiguous raw cwd is accepted |
| Pre-staged command workspaces are rejected | Ignore cached diff in clean-state check | **RED** — command starts on staged state |
| Dirty patch state is rejected before apply | Remove the pre-apply state gate | **RED** — `git apply` runs against dirty state |
| Hidden index state is rejected | Ignore lowercase/S tags from `git ls-files -v` | **RED** — assume-unchanged or skip-worktree hides a tracked mutation |
| Hidden index state is physically cleared | Omit `git update-index --no-assume-unchanged/--no-skip-worktree` before reset | **RED** — reset reports clean while flags survive |
| Commands do not execute in source checkout | Run registered argv with `cwd=source` | **RED** — source worktree/metadata is exposed |
| Persistent host writes are denied | Remove Landlock or grant rights above sandbox | **RED** — descendant creates a host artifact |
| Truncate is always mediated | Permit Landlock ABI 1/2 or omit `TRUNCATE` | **RED** — existing host files can be truncated outside the sandbox |
| Metadata mutation is denied | Remove the inherited seccomp filter | **RED** — chmod/chown/xattr/utime changes host metadata without changing Git state |
| Alternate xattr/file-attribute entrypoints are denied | Permit syscall 463, 466 or 469 | **RED** — an at-variant or file-attribute syscall bypasses the legacy xattr denylist |
| io_uring cannot dispatch metadata mutations | Permit syscall 425, 426 or 427 | **RED** — an io_uring context can bypass direct metadata-syscall comparisons |
| x86_64 x32 syscall aliases are denied | Remove the `X32_SYSCALL_BIT` guard | **RED** — x32-numbered metadata calls bypass native syscall comparisons |
| File-flag ioctl mutation is denied | Permit the architecture-specific `ioctl` syscall | **RED** — `FS_IOC_SETFLAGS` remains an alternate host-metadata path |
| Seccomp architecture is verified | Accept unknown/mismatched audit architecture | **RED** — filter can inspect the wrong syscall table |
| Containment installation fails closed | Ignore Landlock/seccomp setup failure | **RED** — reviewed argv runs without the declared boundary |
| Landlock denial is inherited | Apply restriction after spawning command | **RED** — child writes outside sandbox |
| Seccomp denial is inherited | Install filter after spawning command | **RED** — child mutates host metadata |
| Real Git metadata is unreachable | Expose source `.git` backup or alternates | **RED** — command discovers source authority |
| Bundle source is removed | Keep bundle or origin remote | **RED** — sandbox reveals source path/material |
| Sandbox Git metadata participates in evidence | Omit bounded `.git` fingerprint | **RED** — metadata mutation can pass |
| Sandbox cleanup is mandatory | Skip destruction or cleanup failure | **RED** — disposable repository survives |
| Source cleanliness is re-verified | Remove final source verification | **RED** — escaped source mutation is undetected |
| Host Git context cannot redirect commands | Preserve inherited `GIT_DIR` | **RED** — Git is redirected outside sandbox |
| Templates cannot override Git isolation | Permit reserved Git/home environment | **RED** — template bypasses isolation |
| Raw task paths remain unambiguous | Validate only normalized path parts | **RED** — ambiguous path authority is accepted |
| Default registry grants no command | Register a default command | **RED** — empty-registry assertion fails |
| Escaped POSIX sessions remain contained | Replace descendant scan with leader-only `killpg` | **RED** — new-session child survives |
| Termination evidence needs acknowledgement | Simulate unacknowledged supervisor exit | **RED** — no receipt may be returned |
| Ignored artifacts count as mutations | Remove ignored-file scans | **RED** — hidden state can pass |
| Nested repositories are observable/disposable | Preserve direct nested `.git` plus payload mutation | **RED** — nested state survives or passes |
| Patch reset proves physical cleanliness | Remove post-reset verification | **RED** — residual state can be called reset |
| Snapshot failures cannot dirty source | Inspect source instead of sandbox | **RED** — oversized mutation reaches source |

The unmodified candidate passed the focused harness for exact-SHA binding,
immutable argv, canonical raw paths, dirty and hidden-index preconditions,
independent sandbox execution, Landlock ABI 3+ content confinement, inherited
seccomp metadata confinement, combined worktree/Git-metadata evidence, mandatory
cleanup, source re-verification, process-tree containment, ignored-artifact
handling and nested-repository cleanup.

Executable descendants attempted absolute writes plus chmod, chown, xattr and
utime changes against host targets. A separate raw-syscall regression requires
`EPERM` for io_uring setup/entry/registration, setxattrat, removexattrat,
file_setattr, the file-flag ioctl path and the x86_64 x32 syscall namespace. The
kernel denied every tested path before argument validation, and the host content,
mode, ownership-relevant state, timestamps and xattrs remained unchanged.
Separate regressions prove both assume-unchanged and skip-worktree are rejected,
explicitly cleared and restored to exact base before any patch receipt.

The exact-head execution remains authoritative; this document does not substitute
for repository checks and external review bound to the reviewed commit.
