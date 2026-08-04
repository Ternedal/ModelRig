# Tier-A Git-aware command receipt

Slice 10G joins one verified Tier-A execution result to deterministic Git
before/after/reset evidence. H2 hardens that evidence by requiring the shared
complete trusted Git runtime rather than selecting `git` through host `PATH`.

The control plane remains dormant and fail closed. This boundary adds no second
project-command launcher, GitHub write, branch push, reviewer request,
ready-for-review conversion, merge, release, deployment or activation authority.

## Public orchestration boundary

The only orchestration entrypoint is:

```python
run_single_verified_tier_a_command_with_receipt(..., git_runner=...)
```

The task must contain exactly one allowed command and the identical one required
test. The function derives the command ID from the validated task and exposes no
caller-selected Git argv, project argv, cwd or command ID.

`git_runner` is mandatory and must be a `TrustedGitRunner`. The production receipt
module contains no direct subprocess Git invocation and has no fallback to a bare
`git` command or inherited host `PATH`.

## Accepted workspace state

The workspace must be an absolute link-free Git worktree whose top-level path is
exactly the supplied workspace root. Before execution:

- `HEAD` equals the task's exact base SHA;
- an optional staged patch is allowed;
- unstaged tracked changes are rejected;
- untracked files are rejected; and
- Git output remains bounded.

Git diff evidence uses fixed binary/full-index command shapes with color,
external diff, text conversion and rename detection disabled.

## Complete Git runtime evidence

The receipt embeds `kaliv-development-trusted-git-runtime-evidence/v1`, binding:

- complete runtime manifest SHA-256;
- complete runtime file count and bytes;
- executable SHA-256;
- observed Git version;
- exact helper path;
- exact runtime PATH directories; and
- exact runtime library directories.

Runtime evidence is captured before workspace inspection and again after Tier-A
execution and cleanup. Any runtime identity change fails closed and triggers the
same exact-base reset protection used for workspace mutation.

The runner itself reverifies every staged runtime file and all isolation
locations before and after each Git command.

## Canonical Git snapshot

`kaliv-development-git-workspace-snapshot/v1` records:

- exact HEAD SHA;
- staged binary/full-index diff SHA-256 and bytes;
- unstaged binary/full-index diff SHA-256 and bytes; and
- NUL-delimited untracked-path SHA-256 and count.

The snapshot is canonical JSON and contains bounded identities rather than an
unrestricted repository export.

## Execution, cleanup and reset

The fixed sequence is:

1. validate the one-command task and trusted Git runner;
2. capture complete Git runtime evidence;
3. validate the exact worktree and capture `workspace_before`;
4. invoke only the existing verified Tier-A command path;
5. preserve typed timeout evidence when present;
6. remove only the deterministic staged project-runtime closure;
7. capture `workspace_after`;
8. reset to the exact base if the snapshots differ;
9. capture complete Git runtime evidence again; and
10. emit a receipt only when a canonical result exists and runtime identity is
    unchanged.

Mutation reset uses fixed `reset --hard <base>` and `clean -fd` operations through
the same trusted runtime. A reset can never produce a passing receipt.

## Canonical receipt

`kaliv-development-tier-a-command-receipt/v1` contains:

- task, base and command identity;
- complete trusted Git runtime evidence;
- complete nested Tier-A result;
- before and after snapshots;
- optional reset snapshot; and
- consistent unchanged/reset/passed flags.

A receipt passes only when the nested execution result passes, the Git snapshots
are identical, no reset was required and the trusted Git runtime identity did not
change.

Because semantic review, readiness, publisher intent and authorization embed or
hash the complete receipt, the runtime identity propagates into every later
authority artifact without adding a new write boundary.

## Native Windows proof

The Windows contract builds a temporary repository, compiles the native helper,
stages a fresh Git-for-Windows runtime package, hashes its executable and helper
closure and uses the same `TrustedGitRunner` for repository setup, snapshots and
receipt orchestration. It then invokes the real AppContainer, Job Object,
lifetime guard and bounded-output path.

This proves software wiring on the CI host. It does not replace a selected-rig
physical I0b campaign.

## Authority identity and limits

Trusted-Git modules are included in the Tier-A authority bundle and H1 verifies
recursive import closure. The changed authority digest invalidates older physical
reports fail closed.

This boundary still does not provide streaming output capture, crash recovery,
asymmetric signing, Git remote configuration, network writes, push, pull-request
mutation, reviewer requests, ready conversion, merge, release, settings,
deployment or unattended activation.
