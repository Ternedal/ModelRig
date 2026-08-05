# DC-L01 independent review verdict contract

This file is a stable review contract, not a self-authored verdict.

A qualifying verdict must:

- be submitted by an identity different from the PR author;
- name or be mechanically bound to the exact pull-request head;
- inspect the complete 28-path diff against ADR-DC-001 and DC-L00;
- confirm the twelve exact-copy blobs and eight documented projections;
- confirm no future-slice import, concrete Git runner, non-empty default command
  registry, network write, GitHub mutation, publication or activation authority;
- confirm all required GitHub checks are green on that exact head; and
- return either actionable findings or an explicit no-findings/approval signal.

Any commit after the verdict makes it stale. The authoritative verdict is the
GitHub review or review-bot no-findings signal attached to the exact head; this
artifact deliberately remains true before and after that external event.
