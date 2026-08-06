# Candidate 1.58.150 — physical validation head

This file marks the head that the 1.58.150 physical campaign is validated
against. It is deleted when the release is tagged.

## Why the candidate lives on a branch

`candidate_freeze_check` requires four workflows green on the candidate's
**exact head**: `ci`, `agent3-diagnostics`, `agent3-full-diagnostics`, `codeql`.

Two of them run only on `pull_request`, and `codeql` has no `workflow_dispatch`
at all — so on `main` they can only be satisfied by a push, and every later
merge moves the head out from under the evidence.

That is not hypothetical. While this candidate was being prepared, four runs
went green on `cf00fc77`; then #372 landed and they described a commit that was
no longer the head. All four had to start over.

A candidate branch with an open PR settles it: every workflow triggers on
`pull_request`, against a head no later merge can move.

The freeze additionally requires that the candidate **contains** current
`origin/main`. So while a physical run is in progress, `main` must stand still
— if it advances, the candidate no longer contains it and the freeze refuses,
taking every candidate-bound proof with it.

## What this candidate carries

Ten fixes, all found on the physical rig, none reachable by CI.

**Product**

| Fix | PR |
|---|---|
| capability receipt binds a finished run to the approved plan | #373 (fixes #371) |
| supervisor: restart decision no longer read through a data race | #374 |
| supervisor: records how a child died instead of a bare line | #374 |
| supervisor: a UTF-8 BOM cannot swallow the first env var | #376 |
| supervisor: owns children as a process tree via Job Objects | #379 |

**Tooling**

| Fix | PR |
|---|---|
| Stage B measures trials on the candidate, not the release before it | #369 |
| `--root` honoured by every git call; the campaign accepts it too | #370 |
| pilot no longer dirties the tree it then requires clean | #375 |
| error classes name the cause instead of the nearest keyword | #377 |
| reboot trial stops reporting a number it never measured | #378 |

## Known and accepted

The updater does not distribute itself: an installation keeps its own updater
indefinitely, so a fix to the updater cannot reach a rig through the updater.
Confirmed acceptable while this rig is the only installation — and blocking the
moment there is a second.

## Sequence

1. Stage A (7 proofs) against this head, with `main` held still
2. Promote — `v1.58.150`. After the tag, `main` may move freely
3. Stage B (5 trials), 20/20 read-only pilot, task_ui → 8/8
