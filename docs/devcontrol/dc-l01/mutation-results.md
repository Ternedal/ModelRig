# DC-L01 mutation results

Focused controlled mutations were executed against the projected DC-L01 seams
before publication. Each mutation was applied alone and the corresponding guard
was required to turn red.

| Load-bearing property | Controlled mutation | Result |
|---|---|---|
| Workspace binds exact task base SHA | Replace `if head != task.base_sha` with `if False` | **RED** — wrong SHA was accepted; guard test detects it |
| New workspace must be clean | Replace `if status.strip()` with `if False` | **RED** — dirty status was accepted; guard test detects it |
| DC-L01 cannot import DC-L09 | Add `from .trusted_git_runtime ...` to the foundation | **RED** — future-import assertion detects it |
| Default registry grants no command | Register `python.unittest` in the default registry | **RED** — empty-registry assertion detects it |

The unmodified candidate passed the focused harness for wrong-SHA rejection,
dirty-workspace rejection, no future import and empty default registry.

The byte-identical source tests additionally exercise protected-path precedence,
boolean budget rejection, patch mode/rename/binary rejection, mutation reset,
timeout and combined-output process-tree termination. Their exact-head execution
is required by `exact-head-validation.md`; this document does not substitute for
the GitHub checks on the reviewed commit.
