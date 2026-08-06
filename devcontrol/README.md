# Kaliv Development Control — DC-L01 foundation

DC-L01 is the dependency-minimal, dormant foundation defined by
`docs/devcontrol/ADR-DC-001_DEVCONTROL_AUTHORITY_BOUNDARY.md` and the landed
DC-L00 decomposition contract.

## Included authority

- immutable development-task contracts with human-only merge authority;
- canonical repository-relative task paths, command working directories and
  budget policy;
- bounded UTF-8 reads and literal search inside approved paths;
- fail-closed non-binary unified-diff parsing, application and staged receipts;
- fixed command templates selected only from an immutable registry;
- Linux streaming subprocess containment through a subreaper supervisor that
  terminates descendants even when they create a new session;
- command execution in a bounded independent exact-HEAD repository created from a
  temporary bundle, with the bundle and origin removed before execution;
- Linux Landlock ABI 3+ write confinement inherited by command descendants,
  allowing persistent filesystem mutation only below the disposable sandbox root,
  with `/dev/null` as the sole non-persistent sink exception;
- an inherited seccomp filter that denies chmod, chown, extended-attribute and
  timestamp mutation syscall families which Landlock cannot mediate;
- no object alternate or real Git-metadata backup exposed to command code;
- combined sandbox worktree and metadata receipt fingerprints plus isolated
  command context;
- exact-HEAD and clean-state checks before and after command execution;
- patch preconditions that reject and verified-reset staged, unstaged, untracked,
  ignored, assume-unchanged and skip-worktree state before any `git apply` call;
- verified double-force cleanup for patch artifacts and nested repositories; and
- exact-SHA detached-worktree verification through an injected local Git
  protocol.

## Deliberately absent

DC-L01 ships no command catalog, no registered default command, no concrete Git
runner, no publication and no activation path. `default_registry()` is empty.
`WorkspaceManager` cannot do anything until a later reviewed slice injects a
compatible runner.

Windows command containment deliberately fails closed in DC-L01. Linux command
execution also fails closed when Landlock ABI 3+, the supported seccomp audit
architecture or seccomp installation is unavailable. Commands requiring denied
host metadata mutation fail closed. The native Windows Job Object boundary belongs
to DC-L05 and is not imported early.

Product code must not import `kaliv_dev_control`.

## Validation

```bash
PYTHONPATH=devcontrol/src python -m unittest discover -s devcontrol/tests -v
PYTHONPATH=devcontrol/src python -m kaliv_dev_control validate-task task.json
```

The review and exact-head evidence for this slice live under
`docs/devcontrol/dc-l01/` and in the PR checks bound to the exact head SHA.
