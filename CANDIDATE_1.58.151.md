# Candidate 1.58.151 — physical validation head

This file marks the exact head that the 1.58.151 physical campaigns are
validated against. It is deleted when the release is tagged.

## Qualification and immutability

`candidate_freeze_check` requires four workflows green on the candidate's
**exact head**: `ci`, `agent3-diagnostics`, `agent3-full-diagnostics`, and
`codeql`.

The open pull request causes those workflows to run; it does not make the branch
immutable. No physical evidence may be collected while review or CI is still
changing the candidate head.

After one exact head has all four workflows green and final exact-head review has
no actionable findings, that SHA is the freeze point. From that moment until
release or explicit abandonment:

- do not push, rebase, force-push, merge, amend or otherwise move this branch;
- do not edit this marker or add unrelated commits;
- any head change invalidates every freeze receipt and every physical report and
  requires full exact-head CI and review qualification again.

Every campaign and final gate that consumes a freeze receipt refetches
`origin/main`, requires the current remote SHA to equal the recorded anchor, and
rechecks that the anchor is contained by the candidate. Any movement of `main`
or fetch failure invalidates the receipt and requires a new candidate freeze
before evidence may be collected or accepted.

## Exact base

- version: `1.58.151`
- branch: `agent/unified-candidate-1.58.151`
- inherited main commit: `87334ce8e002dfe5bac7b7746b519f4eaeee6c3a`
- superseded candidate head: `97c50f5dc269567233e75bb6d1a4d4199f458daa`
- production activation: `false`

The superseded head is permanently invalid for physical evidence. No report,
receipt or review qualification from that head may be reused.

## What changed after the quarantined candidate

PR #407 landed the fail-closed 1.58.151 physical validation authority on `main`.
The rebuilt candidate therefore inherits:

- executable Stage A and Stage B runbooks bound to 1.58.151;
- exact source appliance `1.58.150` and target `1.58.151`;
- verified one-time updater bootstrap because 1.58.150 has no self-update path;
- live updater checksum and provenance binding to the target release;
- strict duplicate-key rejection for authority-bearing JSON;
- durable invalidation of stale final receipts and cached lifecycle proof;
- interruption/recovery evidence bound to one observed transaction, exact
  source/target identity, launched updater PID and completed swap state;
- offline recovery requirements proving readiness, all live executables and no
  remaining updater journal;
- exact evidence-key cardinality and strict report hash binding;
- retained crash-order and mutation regression coverage;
- `production_activation=false` as a hard invariant.

## Candidate identity already present on main

The candidate also inherits every 1.58.151 version and update change already
landed before PR #407:

- all established backend, worker, Android, desktop, generated-status, Stage A,
  scheduler, Agent 3 and T-022 bindings report `1.58.151`;
- Android `versionCode` is `278`;
- recovery runs before appliance startup;
- the updater can replace itself using release-bound checksum and provenance;
- Windows executable replacement preserves a valid live file across failure;
- successful committed appliance updates launch updater self-update as a
  non-gating follow-up;
- watcher argument observation mirrors Go flag spelling, value, repetition and
  parsing-boundary semantics;
- every freeze-receipt consumer refetches current `origin/main` and rejects a
  stale anchor before physical evidence can be collected or accepted.

## Physical evidence required before promoting 1.58.151

Hosted CI proves contracts and Windows API behavior, not the installed rig,
Task Scheduler state, antivirus/file-lock behavior, interruption timing,
Tailscale reachability, Ollama behavior or Android interaction.

The 1.58.151 campaign must use the final qualified exact head and record fresh,
candidate-bound evidence for:

1. T-004 rig preflight;
2. T-005 Agent 3 appliance validation;
3. T-007 plan-only model evaluation;
4. T-040 voice baseline, including the typed Pixel stop/barge-in matrix;
5. T-043 RAG baselines at exactly 1,000 and 10,000 chunks;
6. T-019 scheduler pilot with read, approved write, pause and crash recovery;
7. the interactive browser/peer proof;
8. Stage B update, reboot, supervisor restart, invalid-update handling,
   interruption/recovery and preservation of data, credentials and schedules.

No old 1.58.150 report and no report bound to an earlier invalidated 1.58.151
head may satisfy this candidate.

## Automatic updater self-update is deferred

`1.58.151` is the first signed release intended to contain self-update support.
A pre-support updater cannot retroactively contain that path and requires one
verified manual/bootstrap replacement. The verified self-update command also
installs only a release newer than its compiled version.

Therefore 1.58.151 cannot truthfully prove automatic signed-release-to-signed-
release self-update from 1.58.150 or from 1.58.151 to itself. Issue #401 remains
open for the genuine proof using signed 1.58.151 as the self-update-capable
source and a later signed release greater than 1.58.151 as the target. #401 is
not a promotion blocker for 1.58.151.

## Sequence

1. Keep this PR open and do not merge it.
2. Collect no physical evidence until all four exact-head workflows are green
   and final exact-head review has no actionable findings.
3. Declare that reviewed exact SHA as the freeze point and prohibit every branch
   mutation listed above.
4. Create a fresh freeze receipt on the frozen SHA immediately before each
   campaign or final gate; receipt consumption fails if `main` moves.
5. Run only the 1.58.151 promotion requirements against the frozen exact SHA.
6. Promote after those reports are green and independently checked; do not wait
   for the deferred automatic proof in #401.
7. Tag `v1.58.151`, then remove the candidate marker through the normal release
   process.
8. Use signed 1.58.151 as the source for #401 when a later signed target exists.
