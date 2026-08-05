# Kaliv Development Control — DC-L01 foundation

DC-L01 is the dependency-minimal, dormant foundation defined by
`docs/devcontrol/ADR-DC-001_DEVCONTROL_AUTHORITY_BOUNDARY.md` and the landed
DC-L00 decomposition contract.

## Included authority

- immutable development-task contracts with human-only merge authority;
- canonical repository-relative path and budget policy;
- bounded UTF-8 reads and literal search inside approved paths;
- fail-closed non-binary unified-diff parsing, application and staged receipts;
- fixed command templates selected only from an immutable registry;
- Linux streaming subprocess containment through a subreaper supervisor that
  terminates descendants even when they create a new session;
- transactional command execution behind a bounded disposable Git metadata
  overlay, so config, hook, ref and object mutations cannot reach the real repo;
- combined worktree and metadata receipt fingerprints plus rejection of inherited
  or template-provided Git-context overrides;
- clean-state evidence that includes staged, ignored and nested-Git artifacts,
  resets with `git clean -ffdx`, and verifies physical cleanliness afterward;
- post-command verification failures reset before they propagate; and
- exact-SHA detached-worktree verification through an **injected local Git
  protocol**.

## Deliberately absent

DC-L01 ships no command catalog, no registered default command, no concrete Git
runner, no GitHub adapter, no HTTP client, no credential loader, no physical
evidence, no process-launch authority for Tier A, no publication and no
activation path. `default_registry()` is empty. `WorkspaceManager` cannot do
anything until a later reviewed slice injects a compatible runner.

Windows command containment deliberately fails closed in DC-L01. The native Job
Object boundary belongs to DC-L05 and is not imported early.

Product code must not import `kaliv_dev_control`.

## Validation

```bash
PYTHONPATH=devcontrol/src python -m unittest discover -s devcontrol/tests -v
PYTHONPATH=devcontrol/src python -m kaliv_dev_control validate-task task.json
```

The review and exact-head evidence for this slice live under
`docs/devcontrol/dc-l01/` and in the PR checks bound to the exact head SHA.
