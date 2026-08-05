# DC-L01 independent review verdict contract

This file is a stable review contract, not a self-authored verdict.

A qualifying verdict must:

- be submitted by an identity different from the PR author;
- name or be mechanically bound to the exact pull-request head;
- inspect the complete 28-path diff against ADR-DC-001 and DC-L00;
- confirm the eight exact-copy blobs and twelve documented projections;
- confirm command templates freeze argv into immutable tuples;
- confirm command and patch execution bind evidence to the exact task base SHA
  and return no passing receipt from a mismatched workspace HEAD;
- confirm the Linux subreaper terminates descendants that create new sessions;
- confirm termination proof is emitted only after the supervisor positively
  acknowledges tree quiescence, and an unacknowledged/fallback path returns no
  successful result;
- confirm Windows containment fails closed pending DC-L05;
- confirm ignored files count as mutations for both command and patch evidence,
  cannot coexist with a positive receipt and are physically removed by
  `git clean -fdx` during reset;
- confirm no future-slice import, concrete Git runner, non-empty default command
  registry, network write, GitHub mutation, publication or activation authority;
- confirm all required GitHub checks are green on that exact head; and
- return either actionable findings or an explicit no-findings/approval signal.

Any commit after the verdict makes it stale. The authoritative verdict is the
GitHub review or review-bot no-findings signal attached to the exact head; this
artifact deliberately remains true before and after that external event.
