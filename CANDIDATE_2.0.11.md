# Candidate 2.0.11 — physical validation head (2.0.11)

This file marks the exact head that the 2.0.11 physical campaigns are validated against. It is deleted through the normal release process after the release is tagged.

## Qualification and immutability

`candidate_freeze_check` requires four workflows green on the candidate's **exact head**: `ci`, `agent3-diagnostics`, `agent3-full-diagnostics`, and `codeql`.

The open pull request causes those workflows to run; it does not make the branch immutable. No physical evidence may be collected while review or CI is still changing the candidate head.

After one exact head has all four workflows green and final exact-head review has no actionable findings, that SHA is the freeze point. From that moment until release or explicit abandonment:

- do not push, rebase, force-push, merge, amend or otherwise move this branch;
- do not edit this marker or add unrelated commits;
- any head change invalidates every freeze receipt and every physical report and requires complete exact-head CI and review qualification again.

Every campaign and final gate that consumes a freeze receipt refetches `origin/main`, requires the current remote SHA to equal the recorded anchor, and rechecks that the anchor is contained by the candidate. Any movement of `main` or fetch failure invalidates the receipt and requires a new candidate freeze before evidence may be collected or accepted.

## Exact base

- version: `2.0.11`
- branch: `agent/unified-candidate-2.0.11-r2`
- inherited main commit: `218019fd47ea90b046a334253ab5fd84485f772a`
- supersedes candidate PR: `#405`
- supersedes candidate head: `904eba01b2e2bea0c5990a7207d6107e844ab53b`
- production activation: `false`

The superseded head and every receipt, report or qualification bound to it are invalid and may not be reused.

## Included completion work

This candidate includes the complete updater series, the executable Stage B authority merged through PR #407, and the physical-operator alignment merged through PR #413:

- recovery before appliance startup;
- release-bound updater self-update support;
- atomic Windows replacement and committed-update orchestration;
- Go-compatible watcher flag parsing;
- exact 2.0.10 → 2.0.11 source/target enforcement;
- target-release checksum and provenance binding for the bootstrap updater;
- new-transaction mid-swap interruption plus offline `-recover` proof;
- strict hash-bound Stage B evidence, duplicate-key rejection, checkpoint binding and stale-receipt invalidation;
- crash-order and adversarial mutation coverage for the retained operator path;
- Stage A, Agent 3 and scheduler physical operators pinned to this r2 branch;
- authoritative staged-promotion and rig-day runbooks pinned to this r2 branch and PR #412.

## Physical evidence required before promoting 2.0.11

Hosted CI proves software contracts and Windows API behavior, not the installed rig, Task Scheduler state, antivirus/file-lock behavior, interruption timing, Tailscale reachability, Ollama behavior or Android interaction.

The campaign must use the final qualified exact head and record candidate-bound evidence in two ordered phases:

1. **Stage A, before publication:** rig preflight, Agent 3 appliance validation, plan-only model evaluation, voice baseline including the typed Pixel matrix, RAG baselines, scheduler pilot and the interactive browser/peer proof.
2. **Stage B, only after publication:** the verified one-time updater bootstrap and the normal appliance update, reboot, supervisor restart, invalid-update handling, rollback/interruption recovery and preservation matrix that can truthfully be exercised against the published signed 2.0.11 release.

No old 2.0.10 report and no report bound to #405 or any earlier invalidated 2.0.11 head may satisfy this candidate.

## Automatic updater self-update is deferred

`2.0.11` is the first signed release intended to contain self-update support. A pre-support updater cannot retroactively contain that path and requires one manual/bootstrap replacement. The verified self-update command also installs only a release newer than its compiled version.

Therefore 2.0.11 cannot truthfully prove automatic signed-release-to-signed-release self-update from 2.0.10 or from 2.0.11 to itself. Issue #401 remains open for the genuine proof using signed 2.0.11 as source and a later signed release greater than 2.0.11 as target. #401 is not a promotion blocker for 2.0.11.

## Sequence

1. Keep this PR open and do not merge it.
2. Collect no physical evidence until all four exact-head workflows are green and final review has no actionable findings.
3. Declare that reviewed exact SHA as the freeze point and prohibit every branch mutation listed above.
4. Run Stage A against the frozen unpublished candidate. Create a fresh freeze receipt immediately before every Stage A campaign or final gate; receipt consumption fails if `main` moves.
5. After Stage A is green, require a separate explicit release decision. Fast-forward `main` to the exact frozen candidate SHA, tag that same SHA as `v2.0.11`, and publish the complete signed release set. Any SHA change invalidates Stage A.
6. Only after the signed release exists, run Stage B against published 2.0.11 and collect the updater/lifecycle evidence.
7. Verify the final Stage B receipt, including all eight physical proofs, exact release identity, complete cleanup and `production_activation=false`.
8. Complete the release/promotion decision only after Stage A and Stage B are independently green and checked. Remove this candidate marker through the normal release process; do not merge this freeze PR as an ordinary code PR.
9. Use signed 2.0.11 as the source for issue #401 when a later signed target exists.
