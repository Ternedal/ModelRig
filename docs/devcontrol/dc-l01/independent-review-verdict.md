# DC-L01 independent review verdict contract

This file is a stable review contract, not a self-authored verdict.

A qualifying verdict must:

- be submitted by an identity different from the PR author;
- name or be mechanically bound to the exact pull-request head;
- inspect the complete 28-path diff against ADR-DC-001 and DC-L00;
- confirm the six exact-copy blobs and fourteen documented projections;
- confirm command templates freeze argv and reject `GIT_*`, `HOME` and
  `XDG_CONFIG_HOME` isolation overrides;
- confirm inherited `GIT_*` context is removed from generic command execution;
- confirm command and patch execution bind evidence to the exact task base SHA
  and return no passing receipt from a mismatched workspace HEAD;
- confirm staged, unstaged, untracked and ignored source-workspace state is
  rejected before a registered command starts;
- confirm registered commands execute only inside a bounded independent
  exact-HEAD Git repository created through a temporary bundle;
- confirm the bundle and origin are removed before execution, no object alternate
  or source path is exposed, and the sandbox has isolated HOME/XDG/TMP/Git config;
- confirm receipts bind both sandbox worktree state and the complete bounded
  sandbox Git-metadata fingerprint;
- confirm config, hook, ref, object, ignored-file and nested-repository writes
  remain confined to the disposable sandbox, invalidate positive command evidence
  and are physically removed when the sandbox is destroyed;
- confirm mandatory sandbox cleanup and a final exact-HEAD/clean-state check prove
  that the source repository remains unchanged before a receipt is returned;
- confirm ambiguous raw task paths are rejected before filesystem path
  normalization can alter their authority;
- confirm the Linux subreaper terminates descendants that create new sessions;
- confirm termination proof is emitted only after the supervisor positively
  acknowledges tree quiescence, and an unacknowledged/fallback path returns no
  successful result;
- confirm Windows containment fails closed pending DC-L05;
- confirm ignored files and nested Git repositories count as patch mutations,
  cannot coexist with a positive patch receipt and are physically removed by
  `git clean -ffdx` during patch reset;
- confirm patch reset verifies exact HEAD plus zero staged, unstaged, untracked
  and ignored residual state before success is claimed;
- confirm a command snapshot/output-limit failure cannot expose or dirty the
  source repository because execution remains inside the disposable sandbox;
- confirm no future-slice import, concrete Git runner, non-empty default command
  registry, network write, GitHub mutation, publication or activation authority;
- confirm all required GitHub checks are green on that exact head; and
- return either actionable findings or an explicit no-findings/approval signal.

Any commit after the verdict makes it stale. The authoritative verdict is the
GitHub review or review-bot no-findings signal attached to the exact head; this
artifact deliberately remains true before and after that external event.
