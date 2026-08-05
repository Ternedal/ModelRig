# DC-L01 mutation results

Focused controlled mutations were executed against the projected DC-L01 seams
before publication. Each mutation was applied alone and the corresponding guard
was required to turn red.

| Load-bearing property | Controlled mutation | Result |
|---|---|---|
| Workspace binds exact task base SHA | Replace `if head != task.base_sha` with `if False` | **RED** — wrong SHA was accepted; workspace guard detects it |
| New workspace must be clean | Replace `if status.strip()` with `if False` | **RED** — dirty status was accepted; guard test detects it |
| Command receipts bind the exact task base SHA | Remove the pre/post `rev-parse HEAD` checks | **RED** — a no-op command on the wrong commit returns a passing receipt |
| Patch receipts bind the exact task base SHA | Remove the patch `rev-parse HEAD` check | **RED** — a patch can be applied while the receipt names another base commit |
| Fixed command authority is immutable | Retain the caller-owned argv list instead of copying to a tuple | **RED** — post-registration list mutation changes the executable arguments |
| Pre-staged command workspaces are rejected | Remove `cached` from the clean-state boolean | **RED** — the marker command starts despite a staged index mutation |
| Git metadata is isolated from commands | Execute against the real `.git` entry instead of the disposable overlay | **RED** — injected remote and hook persist despite a clean worktree |
| Git metadata participates in receipt evidence | Omit the overlay fingerprint from the combined receipt fingerprint | **RED** — config/hook mutations can return positive evidence |
| Real metadata restoration is transactional | Remove rollback between the two `.git` renames | **RED** — activation failure can leave the real metadata displaced |
| Host Git context cannot redirect commands | Preserve inherited `GIT_DIR` in `SubprocessRunner` | **RED** — a host value redirects Git away from the task repository |
| Templates cannot override Git isolation | Permit `GIT_*`, `HOME` or `XDG_CONFIG_HOME` in template env | **RED** — a registered command can bypass overlay/config isolation |
| Raw task paths remain unambiguous | Validate only `PurePosixPath.parts` after normalization | **RED** — dot, duplicate-separator or trailing-separator authority is silently accepted |
| DC-L01 cannot import DC-L09/DC-L05 product code | Add `trusted_git_runtime` or `app.windows_job` import | **RED** — future/product-import assertion detects it |
| Default registry grants no command | Register `python.unittest` in the default registry | **RED** — empty-registry assertion detects it |
| Escaped POSIX sessions remain inside the boundary | Replace descendant scan with leader-only `killpg` | **RED** — `start_new_session=True` descendant survives the timeout regression |
| Termination evidence requires positive quiescence acknowledgement | Force `_terminate_tree()` to return `False`/simulate supervisor exit `125` | **RED** — bounded execution raises and returns no receipt |
| Command ignored artifacts count as mutations | Remove `--ignored` or replace `git clean -ffdx` with `git clean -fd` | **RED** — command regression observes wrong receipt flags or a surviving ignored artifact |
| Patch ignored artifacts invalidate evidence | Remove the ignored scan or replace patch reset `git clean -ffdx` with `git clean -fd` | **RED** — patch regression returns positive evidence or leaves the hidden artifact behind |
| Nested Git repositories are physically removed | Replace `git clean -ffdx` with `git clean -fdx` | **RED** — command and patch regressions leave the nested repository and dirty status behind |
| Reset success requires clean-state proof | Remove the post-reset staged/unstaged/untracked/ignored verification | **RED** — a surviving artifact can be reported as successfully reset |
| Snapshot failures reset before propagation | Move the post-command `_snapshot()` outside the reset-on-error block | **RED** — an oversized tracked diff raises while leaving the workspace modified |

The unmodified candidate passed the focused harness for workspace, command and
patch exact-SHA rejection; immutable command argv; staged, unstaged, untracked
and ignored workspace rejection; Git metadata overlay isolation and combined
receipt fingerprinting; byte-identical real config restoration; injected remote
and hook removal; forbidden template Git context; inherited `GIT_DIR`
sanitization; ambiguous raw task-path rejection; no future/product import; empty
default registry; escaped-session termination; negative acknowledgement handling;
executable ignored-artifact and nested-Git cleanup on command and patch paths;
verified clean-state reset; and reset before propagation of oversized
post-command snapshot failures.

The source tests additionally exercise protected-path precedence, boolean budget
rejection, patch mode/rename/binary rejection, mutation reset, timeout and
combined-output process-tree termination. Their exact-head execution is required
by `exact-head-validation.md`; this document does not substitute for the GitHub
checks on the reviewed commit.
