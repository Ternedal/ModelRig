# Candidate 1.58.151 — physical validation head (r2)

This file marks the exact head that the 1.58.151 physical campaigns are validated against. It is deleted when the release is tagged.

## Qualification and immutability

`candidate_freeze_check` requires four workflows green on the candidate's **exact head**: `ci`, `agent3-diagnostics`, `agent3-full-diagnostics`, and `codeql`.

The open pull request causes those workflows to run; it does not make the branch immutable. No physical evidence may be collected while review or CI is still changing the candidate head.

After one exact head has all four workflows green and final exact-head review has no actionable findings, that SHA is the freeze point. From that moment until release or explicit abandonment:

- do not push, rebase, force-push, merge, amend or otherwise move this branch;
- do not edit this marker or add unrelated commits;
- any head change invalidates every freeze receipt and every physical report and requires complete exact-head CI and review qualification again.

Every campaign and final gate that consumes a freeze receipt refetches `origin/main`, requires the current remote SHA to equal the recorded anchor, and rechecks that the anchor is contained by the candidate. Any movement of `main` or fetch failure invalidates the receipt and requires a new candidate freeze before evidence may be collected or accepted.

## Exact base

- version: `1.58.151`
- branch: `agent/unified-candidate-1.58.151-r2`
- inherited main commit: `87334ce8e002dfe5bac7b7746b519f4eaeee6c3a`
- supersedes candidate PR: `#405`
- production activation: `false`

## Included completion work

This candidate includes the complete updater series and the executable Stage B authority merged through PR #407:

- recovery before appliance startup;
- release-bound updater self-update support;
- atomic Windows replacement and committed-update orchestration;
- Go-compatible watcher flag parsing;
- exact 1.58.150 → 1.58.151 source/target enforcement;
- target-release checksum and provenance binding for the bootstrap updater;
- new-transaction mid-swap interruption plus offline `-recover` proof;
- strict hash-bound Stage B evidence, duplicate-key rejection, checkpoint binding and stale-receipt invalidation;
- crash-order and adversarial mutation coverage for the retained operator path.

## Physical evidence required before promoting 1.58.151

Hosted CI proves software contracts and Windows API behavior, not the installed rig, Task Scheduler state, antivirus/file-lock behavior, interruption timing, Tailscale reachability, Ollama behavior or Android interaction.

The campaign must use the final qualified exact head and record candidate-bound evidence for:

1. Stage A and the remaining Agent 3/scheduler/device pilots;
2. the verified one-time updater bootstrap and the normal appliance update, rollback and interruption matrix that can truthfully be exercised for this release;
3. every other open physical gate that explicitly requires the frozen 1.58.151 release candidate.

No old 1.58.150 report and no report bound to #405 or any earlier invalidated 1.58.151 head may satisfy this candidate.

## Automatic updater self-update is deferred

`1.58.151` is the first signed release intended to contain self-update support. A pre-support updater cannot retroactively contain that path and requires one manual/bootstrap replacement. The verified self-update command also installs only a release newer than its compiled version.

Therefore 1.58.151 cannot truthfully prove automatic signed-release-to-signed-release self-update from 1.58.150 or from 1.58.151 to itself. Issue #401 remains open for the genuine proof using signed 1.58.151 as source and a later signed release greater than 1.58.151 as target. #401 is not a promotion blocker for 1.58.151.

## Sequence

1. Keep this PR open and do not merge it.
2. Collect no physical evidence until all four exact-head workflows are green and final review has no actionable findings.
3. Declare that reviewed exact SHA as the freeze point and prohibit every branch mutation listed above.
4. Create a fresh freeze receipt on the frozen SHA immediately before each campaign or final gate; receipt consumption fails if `main` moves.
5. Run only the 1.58.151 promotion requirements against the frozen exact SHA.
6. Promote after those reports are green and independently checked; do not wait for the deferred automatic proof in #401.
7. Tag `v1.58.151`, then remove the candidate marker through the normal release process.
8. Use signed 1.58.151 as the source for #401 when a later signed target exists.
