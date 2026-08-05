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
| Fixed command authority is immutable | Retain the caller-owned argv list instead of copying to a tuple | **RED** — post-registration list mutation changes the executable arguments |
| Pre-staged command workspaces are rejected | Remove `cached` from the clean-state boolean | **RED** — the marker command starts despite a staged index mutation |
| Commands do not execute in the source checkout | Run the registered argv with `cwd=source` instead of the sandbox repository | **RED** — executable regressions observe source metadata/worktree exposure |
| Real Git metadata is unreachable | Store a source `.git` backup below sandbox HOME or expose it through an object alternate | **RED** — command code can discover the backup/alternate and the sandbox-disclosure regression fails |
| Bundle source is removed before execution | Keep `source.bundle` or its origin remote in the sandbox | **RED** — the executable sandbox regression detects the bundle, remote or bundle path in Git config |
| Sandbox Git metadata participates in receipt evidence | Omit the bounded `.git` fingerprint from the combined receipt fingerprint | **RED** — remote/hook mutations can return positive evidence |
| Sandbox cleanup is mandatory | Skip `shutil.rmtree()` or ignore cleanup failure | **RED** — the disposable repository remains and execution fails closed |
| Source cleanliness is re-verified | Remove the final source exact-HEAD/clean-state check | **RED** — source mutation can escape detection before evidence returns |
| Host Git context cannot redirect commands | Preserve inherited `GIT_DIR` in `SubprocessRunner` | **RED** — a host value redirects Git away from the sandbox repository |
| Templates cannot override Git isolation | Permit `GIT_*`, `HOME` or `XDG_CONFIG_HOME` in template env | **RED** — a registered command can bypass sandbox/config isolation |
| Raw task paths remain unambiguous | Validate only `PurePosixPath.parts` after normalization | **RED** — dot, duplicate-separator or trailing-separator authority is silently accepted |
| DC-L01 cannot import DC-L09/DC-L05 product code | Add `trusted_git_runtime` or `app.windows_job` import | **RED** — future/product-import assertion detects it |
| Default registry grants no command | Register `python.unittest` in the default registry | **RED** — empty-registry assertion detects it |
| Escaped POSIX sessions remain inside the boundary | Replace descendant scan with leader-only `killpg` | **RED** — `start_new_session=True` descendant survives the timeout regression |
| Termination evidence requires positive quiescence acknowledgement | Force `_terminate_tree()` to return `False`/simulate supervisor exit `125` | **RED** — bounded execution raises and returns no receipt |
| Command ignored artifacts count as mutations | Remove the ignored-file scan from the sandbox snapshot | **RED** — the command regression reports unchanged/passed despite an ignored artifact |
| Command artifacts are physically discarded | Preserve the disposable sandbox after a mutating command | **RED** — ignored files or nested repositories remain physically present |
| Patch ignored artifacts invalidate evidence | Remove the ignored scan or replace patch reset `git clean -ffdx` with `git clean -fd` | **RED** — patch regression returns positive evidence or leaves the hidden artifact behind |
| Nested Git repositories are physically removed during patch reset | Replace patch `git clean -ffdx` with `git clean -fdx` | **RED** — the patch regression leaves the nested repository and dirty status behind |
| Patch reset success requires clean-state proof | Remove the post-reset staged/unstaged/untracked/ignored verification | **RED** — a surviving artifact can be reported as successfully reset |
| Snapshot failures cannot dirty the source | Execute post-command inspection against the source checkout rather than the disposable sandbox | **RED** — an oversized tracked mutation reaches the source repository |

The unmodified candidate passed the focused harness for workspace, command and
patch exact-SHA rejection; immutable command argv; staged, unstaged, untracked
and ignored source rejection; independent exact-HEAD bundle-cloned execution;
absence of source paths, metadata backups, retained bundles, remotes and object
alternates; isolated HOME/XDG/TMP/Git configuration; combined sandbox worktree
and complete bounded Git-metadata fingerprinting; sandbox-only remote and hook
mutation; mandatory sandbox destruction; source exact-HEAD/clean-state
re-verification; forbidden template Git context; inherited `GIT_DIR`
sanitization; ambiguous raw task-path rejection; no future/product import; empty
default registry; escaped-session termination; negative acknowledgement handling;
executable ignored-artifact disposal on the command path; ignored-artifact and
nested-Git cleanup on the patch path; and verified patch clean-state reset.

The source tests additionally exercise protected-path precedence, boolean budget
rejection, patch mode/rename/binary rejection, mutation reset, timeout and
combined-output process-tree termination. Their exact-head execution is required
by `exact-head-validation.md`; this document does not substitute for the GitHub
checks on the reviewed commit.
