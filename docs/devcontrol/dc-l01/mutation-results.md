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
| Loader hooks cannot run before confinement | Permit explicit or inherited `LD_*` environment keys | **RED** — dynamic-loader constructors run before Landlock/seccomp |
| File reads are physically bounded | Replace `read(maximum + 1)` with `read()` | **RED** — oversized or growing files can consume unbounded memory |
| Search reads remain bounded after stat | Trust `st_size` and call whole-file `read_bytes()` | **RED** — a concurrently growing file bypasses the scan bound |
| Raw command output evidence is lossless | Hash replacement-decoded UTF-8 text | **RED** — distinct invalid byte streams collapse and byte counts change |
| Pre-staged command workspaces are rejected | Ignore cached diff in clean-state check | **RED** — command starts on staged state |
| Dirty patch state is rejected before apply | Remove the pre-apply state gate | **RED** — `git apply` runs against dirty state |
| Hidden index state is rejected | Ignore lowercase/S tags from `git ls-files -v` | **RED** — hidden tracked mutation survives |
| Hidden index state is physically cleared | Omit update-index clearing before reset | **RED** — flags survive reset |
| Commands do not execute in source checkout | Run registered argv with `cwd=source` | **RED** — source authority is exposed |
| Persistent host writes are denied | Remove Landlock or grant rights above sandbox | **RED** — descendant creates a host artifact |
| Truncate is always mediated | Permit Landlock ABI 1/2 or omit `TRUNCATE` | **RED** — host file can be truncated |
| Metadata mutation is denied | Remove inherited seccomp | **RED** — host metadata changes without Git state |
| Alternate xattr entrypoints are denied | Permit syscall 463, 466 or 469 | **RED** — alternate syscall bypasses denylist |
| io_uring cannot dispatch metadata mutations | Permit syscall 425, 426 or 427 | **RED** — alternate dispatch bypasses comparisons |
| x86_64 x32 aliases are denied | Remove `X32_SYSCALL_BIT` guard | **RED** — x32 metadata calls bypass native numbers |
| File-flag ioctl mutation is denied | Permit architecture-specific `ioctl` | **RED** — file flags remain mutable |
| Seccomp architecture is verified | Accept mismatched audit architecture | **RED** — wrong syscall table is inspected |
| Containment installation fails closed | Ignore Landlock/seccomp setup failure | **RED** — argv runs unconfined |
| Landlock and seccomp denial are inherited | Install after spawning command | **RED** — child mutates host state |
| Real Git metadata is unreachable | Expose source `.git` backup or alternates | **RED** — source authority is discoverable |
| Bundle source is removed | Keep bundle or origin remote | **RED** — source material is exposed |
| Sandbox Git metadata participates in evidence | Omit bounded `.git` fingerprint | **RED** — metadata mutation can pass |
| Sandbox cleanup is mandatory | Skip destruction or cleanup failure | **RED** — disposable repository survives |
| Source cleanliness is re-verified | Remove final source verification | **RED** — escaped source mutation is undetected |
| Host Git context cannot redirect commands | Preserve inherited `GIT_DIR` | **RED** — Git is redirected |
| Raw task paths remain unambiguous | Validate only normalized path parts | **RED** — ambiguous authority is accepted |
| Default registry grants no command | Register a default command | **RED** — empty-registry assertion fails |
| Escaped POSIX sessions remain contained | Replace descendant scan with leader-only kill | **RED** — new-session child survives |
| Termination evidence needs acknowledgement | Simulate unacknowledged supervisor exit | **RED** — no receipt may return |
| Ignored artifacts count as mutations | Remove ignored-file scans | **RED** — hidden state can pass |
| Nested repositories are observable/disposable | Preserve nested `.git` mutation | **RED** — nested state survives |
| Patch reset proves physical cleanliness | Remove post-reset verification | **RED** — residual state is called reset |
| Snapshot failures cannot dirty source | Inspect source instead of sandbox | **RED** — oversized mutation reaches source |

The unmodified candidate passed the focused harness for exact-SHA binding,
immutable argv, canonical paths, loader-hook rejection, physically bounded reads,
lossless raw-byte output evidence, dirty and hidden-index preconditions,
independent sandbox execution, Landlock ABI 3+ content confinement, inherited
seccomp metadata confinement, combined worktree/Git-metadata evidence, mandatory
cleanup, source re-verification, process-tree containment, ignored-artifact
handling and nested-repository cleanup.

Executable descendants attempted absolute writes plus chmod, chown, xattr and
utime changes against host targets. Raw-syscall regressions require `EPERM` for
io_uring, xattr-at, file-setattr, ioctl and x86_64 x32 paths. Additional CI
regressions prove all explicit `LD_*` loader hooks fail before spawn, bounded reads
request only limit-plus-one bytes, non-UTF-8 stdout/stderr retain their original
hash inputs and byte counts, and the preflight attests to synchronized current
main.

The exact-head execution remains authoritative; this document does not substitute
for repository checks and external review bound to the reviewed commit.
