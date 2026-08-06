# DC-L01 independent review verdict contract

This file is a stable review contract, not a self-authored verdict.

A qualifying verdict must:

- be submitted by an identity different from the PR author;
- name or be mechanically bound to the exact pull-request head;
- inspect the complete 28-path diff against ADR-DC-001 and DC-L00;
- confirm the six exact-copy blobs and fourteen documented projections;
- confirm command templates freeze argv, reject reserved environment overrides
  and reject non-canonical raw cwd authority before path normalization;
- confirm command and patch execution bind evidence to the exact task base SHA;
- confirm staged, unstaged, untracked and ignored source state is rejected before
  a registered command starts;
- confirm staged, unstaged, untracked, ignored, assume-unchanged and skip-worktree
  patch state is rejected and verified-reset before any `git apply` invocation;
- confirm hidden index flags are explicitly cleared before reset and verified
  absent after reset and successful patch application;
- confirm registered commands execute only inside a bounded independent exact-HEAD
  Git repository created through a temporary bundle;
- confirm the bundle and origin are removed before execution, no object alternate
  or source path is exposed, and the sandbox has isolated command context;
- confirm Linux Landlock ABI 3+ handles persistent filesystem write, create,
  delete, truncate and refer operations before the reviewed argv starts, granting
  those rights only below the disposable sandbox root, with `/dev/null` as the
  sole non-persistent sink exception;
- confirm Landlock ABI below 3 and unavailable Landlock fail closed;
- confirm an inherited architecture-checked seccomp filter denies chmod, chown,
  extended-attribute and timestamp mutation syscall families not mediated by
  Landlock, and unsupported architectures/filter installation fail closed;
- confirm descendants cannot modify host content, mode, ownership, xattrs or
  timestamps outside the sandbox and the executable regressions prove the host
  target remains unchanged;
- confirm receipts bind both sandbox worktree state and complete bounded sandbox
  Git-metadata state;
- confirm metadata and worktree writes remain confined to the disposable sandbox,
  invalidate positive command evidence and are removed on sandbox destruction;
- confirm mandatory sandbox cleanup and final exact-HEAD/clean-state verification
  prove the source repository remains unchanged before a receipt is returned;
- confirm ambiguous raw task paths are rejected before normalization;
- confirm the Linux subreaper terminates descendants that create new sessions and
  emits proof only after positive quiescence acknowledgement;
- confirm unsupported platform containment fails closed;
- confirm ignored files, hidden index flags and nested repositories count as patch
  mutations and are removed by verified reset;
- confirm no future-slice implementation, non-empty default command registry,
  publication, merge, release, deployment or activation authority exists;
- confirm all required GitHub checks are green on that exact head; and
- return either actionable findings or an explicit no-findings/approval signal.

Any commit after the verdict makes it stale. The authoritative verdict is the
GitHub review or review-bot no-findings signal attached to the exact head; this
artifact deliberately remains true before and after that external event.
