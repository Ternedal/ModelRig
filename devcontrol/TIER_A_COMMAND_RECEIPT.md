# Tier-A Git-aware command receipt

Slice 10G joins one verified Tier-A execution result to deterministic Git
before/after/reset evidence. The control plane remains dormant and fail closed.
This layer does not add a process launcher, a caller-selected command surface,
GitHub writes, branch push, merge, release, deployment or runtime activation.

## Public orchestration boundary

The only new orchestration entrypoint is:

```python
run_single_verified_tier_a_command_with_receipt(...)
```

It deliberately has no `command_id` or argument-vector parameter. The exact
command is derived from a validated `kaliv-development-task/v1`, and the task must
contain exactly one `allowed_command_id` with the identical single entry in
`required_tests`. Multi-command or optional-command ambiguity fails before Tier-A
is called.

The orchestration function invokes only the existing
`run_verified_tier_a_command`. It cannot call `subprocess` for project execution,
construct a second launch plan, bypass the signed physical report, replace the
runtime closure, alter arguments, choose cwd or weaken the AppContainer/Job Object
boundary.

## Accepted workspace state

The workspace must be an absolute, link-free Git worktree whose top-level path is
exactly the supplied workspace root. Before execution:

- `HEAD` must equal the task's exact `base_sha`;
- an optional staged patch is allowed;
- unstaged tracked changes are rejected;
- untracked files are rejected;
- Git commands are fixed argument vectors with `shell=False`;
- external diff, text-conversion, rename detection and color are disabled;
- Git stdout/stderr is bounded.

This keeps the pre-execution authority to one reviewed base plus one already
staged candidate patch. The model cannot smuggle additional unstaged or untracked
input into the command.

## Canonical Git snapshot

`kaliv-development-git-workspace-snapshot/v1` records:

- exact `HEAD` SHA;
- SHA-256 and byte count of deterministic staged binary/full-index diff output;
- SHA-256 and byte count of deterministic unstaged binary/full-index diff output;
- SHA-256 and count of NUL-delimited untracked paths.

The snapshot is canonical JSON and has its own SHA-256 identity. It records
identities and bounded sizes, not unrestricted repository contents.

## Execution and staging cleanup

The sequence is fixed:

1. validate the one-command task and exact Git worktree;
2. capture `workspace_before`;
3. call `run_verified_tier_a_command` with the task-derived command ID;
4. preserve a typed timeout's canonical `TierAExecutionResult`;
5. after Job Object completion and lifetime-guard release, remove only the
   deterministic `.kaliv/runtime-closures/<tool>/<manifest>` staging subtree;
6. capture `workspace_after`;
7. if before and after differ, reset the whole worktree to the exact task base and
   capture `workspace_reset`;
8. emit one canonical receipt only when a canonical Tier-A result exists.

On Windows, staged runtime files remain removable after the Job Object ends. The
DOS read-only attribute is not treated as a security control; lifetime
immutability is provided by the protected DACL and deny-write/delete-sharing
handles acquired before process creation. Unix staging retains mode `0555`.

## Mutation and reset semantics

Any difference between the canonical before and after snapshots makes the receipt
non-passing. The orchestrator then runs fixed:

```text
git reset --hard <task.base_sha>
git clean -fd
```

It captures a final reset snapshot and requires:

- `HEAD == task.base_sha`;
- zero staged patch bytes;
- zero unstaged patch bytes;
- zero untracked paths.

Failure to prove exact-base cleanliness is a typed execution failure. A reset is
never represented as a passing receipt, even when the command itself returned
zero.

If execution fails before producing a canonical result, the same cleanup,
after-snapshot and reset policy still applies, but no synthetic command receipt is
invented.

## Complete receipt

`kaliv-development-tier-a-command-receipt/v1` contains:

- task ID and canonical task SHA-256;
- exact base SHA and task-derived command ID;
- the complete nested `kaliv-development-tier-a-execution-result/v1`;
- canonical Git before and after snapshots;
- optional exact-base reset snapshot;
- consistent `workspace_unchanged`, `workspace_reset_performed` and `passed`
  flags.

A receipt passes only when all three conditions hold:

1. the nested Tier-A result passes;
2. before and after Git snapshot identities are equal;
3. no reset was required.

Timeout results remain fully auditable but non-passing. Extra fields, inconsistent
flags, mismatched task/command identities or a non-clean reset snapshot fail
canonical reload.

## Authority identity

`tier_a_toolhost_sha256` v6 includes the command-receipt orchestrator and therefore
invalidates all v5-or-earlier physical reports. The selected rig needs a new full
I0b campaign for authority bundle v6 before production execution can be approved.

## Proofs

Portable tests prove:

- exact staged patch preservation;
- deterministic runtime-staging cleanup;
- canonical receipt round-trip;
- mutation capture followed by exact-base reset;
- timeout evidence preservation;
- rejection of multi-command tasks;
- rejection of unstaged and untracked input;
- reset after an execution error that mutated the workspace.

The real-Windows gate additionally creates a temporary Git repository, compiles a
static helper, issues synthetic signed eleven-probe evidence, signs a one-file
runtime closure and invokes the receipt orchestrator through the real
AppContainer, Job Object, lifetime guard and bounded-output path. It proves that
the staged patch survives byte-for-byte, runtime staging is absent before the
after snapshot and the complete receipt round-trips canonically.

Synthetic CI evidence proves software wiring only. It does not replace an
independent physical campaign on the selected ModelRig host.

## Deliberate limits

Slice 10G does not provide:

- automatic transitive PE/DLL, Python or Go runtime discovery;
- resistance against a separate administrator or kernel component;
- semantic review of command output or code changes;
- command selection outside the exact one-command task;
- arbitrary Git commands or repository history rewriting beyond exact-base reset;
- branch push, pull-request write, merge, release, settings or deployment
  authority;
- registered ModelRig tool or unattended self-development activation.
