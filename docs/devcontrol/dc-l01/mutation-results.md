# DC-L01 mutation results

Focused controlled mutations were executed against the projected DC-L01 seams
before publication. Each mutation was applied alone and the corresponding guard
was required to turn red.

| Load-bearing property | Controlled mutation | Result |
|---|---|---|
| Workspace binds exact task base SHA | Replace `if head != task.base_sha` with `if False` | **RED** — wrong SHA was accepted; workspace guard detects it |
| New workspace must be clean | Replace `if status.strip()` with `if False` | **RED** — dirty status was accepted; guard test detects it |
| Command receipts bind the exact task base SHA | Remove the source/sandbox `rev-parse HEAD` checks | **RED** — a no-op command can execute while its receipt names another base commit |
| Patch receipts bind the exact task base SHA | Remove the patch `rev-parse HEAD` check | **RED** — a patch can be applied while the receipt names another base commit |
| Fixed command argv authority is immutable | Retain the caller-owned argv list instead of copying to a tuple | **RED** — post-registration list mutation changes executable arguments |
| Fixed command cwd authority is canonical | Validate only `PurePosixPath.parts` after normalization | **RED** — `./devcontrol`, duplicate separators and dot segments are silently accepted |
| Pre-staged command workspaces are rejected | Remove `cached` from the clean-state boolean | **RED** — the marker command starts despite a staged index mutation |
| Pre-staged patch workspaces are rejected before apply | Remove the pre-apply workspace-state gate | **RED** — `git apply --index` runs on a staged change and can issue evidence against the wrong base state |
| Commands do not execute in the source checkout | Run the registered argv with `cwd=source` instead of the sandbox repository | **RED** — executable regressions observe source metadata/worktree exposure |
| Real Git metadata is unreachable | Store a source `.git` backup below sandbox HOME or expose it through an object alternate | **RED** — command code can discover the backup/alternate |
| Bundle source is removed before execution | Keep `source.bundle` or its origin remote in the sandbox | **RED** — the sandbox regression detects the bundle, remote or bundle path |
| Sandbox Git metadata participates in receipt evidence | Omit the bounded `.git` fingerprint | **RED** — remote/hook mutations can return positive evidence |
| Sandbox cleanup is mandatory | Skip `shutil.rmtree()` or ignore cleanup failure | **RED** — the disposable repository remains and execution fails closed |
| Source cleanliness is re-verified | Remove the final source exact-HEAD/clean-state check | **RED** — source mutation can escape detection |
| Host Git context cannot redirect commands | Preserve inherited `GIT_DIR` | **RED** — a host value redirects Git away from the sandbox repository |
| Templates cannot override Git isolation | Permit reserved Git or home variables in template env | **RED** — a registered command can bypass isolation |
| Raw task paths remain unambiguous | Validate only normalized path parts | **RED** — dot, duplicate-separator or trailing-separator authority is accepted |
| Default registry grants no command | Register a default command | **RED** — empty-registry assertion detects it |
| Escaped POSIX sessions remain inside the boundary | Replace descendant scan with leader-only `killpg` | **RED** — a new-session descendant survives |
| Termination evidence requires positive acknowledgement | Simulate an unacknowledged supervisor exit | **RED** — bounded execution raises and returns no receipt |
| Command ignored artifacts count as mutations | Remove the ignored-file scan | **RED** — the command regression reports unchanged/passed |
| Command artifacts are physically discarded | Preserve the sandbox after mutation | **RED** — ignored files or nested repositories remain |
| Patch ignored artifacts invalidate evidence | Remove the ignored scan or weaken patch cleanup | **RED** — patch evidence passes or hidden state remains |
| Nested Git repositories are removed during patch reset | Weaken double-force cleanup | **RED** — the nested repository survives |
| Patch reset success requires clean-state proof | Remove post-reset state verification | **RED** — surviving state can be reported as reset |
| Snapshot failures cannot dirty the source | Inspect the source instead of the sandbox | **RED** — an oversized mutation reaches the source |

The unmodified candidate passed the focused harness for exact-SHA binding,
immutable argv, canonical raw command cwd, clean command and patch preconditions,
independent sandbox execution, metadata isolation, mandatory cleanup, source
re-verification, ambiguous task-path rejection, empty registry, process-tree
containment, ignored-artifact handling, nested-repository patch cleanup and
verified reset. The pre-staged patch regression additionally records every Git
call and proves no `git apply` invocation occurs before the fail-closed reset.

The exact-head execution remains authoritative; this document does not substitute
for the repository checks and external review bound to the reviewed commit.
