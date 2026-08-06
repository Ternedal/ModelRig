# DC-L01 independent review verdict contract

This file is a stable review contract, not a self-authored verdict.

A qualifying verdict must:

- be submitted by an identity different from the PR author;
- name or be mechanically bound to the exact pull-request head;
- inspect the complete 28-path diff against ADR-DC-001 and DC-L00;
- confirm the five exact-copy blobs and fifteen documented projections;
- confirm command templates freeze argv and reject non-canonical raw cwd authority;
- confirm explicit `LD_*` command environment authority is rejected before spawn
  and inherited loader/Git context is stripped;
- confirm file reads and search reads enforce their byte caps during I/O;
- confirm raw stdout/stderr hashes and byte counts survive lossy display decoding;
- confirm command and patch evidence binds to the exact task base SHA;
- confirm command source snapshots inspect `git ls-files -v -z`, reject staged,
  unstaged, untracked, ignored, assume-unchanged and skip-worktree state before
  execution and include hidden index state in final source verification;
- confirm staged, unstaged, untracked, ignored, assume-unchanged and skip-worktree
  patch state is rejected and verified-reset before `git apply`;
- confirm hidden patch index flags are explicitly cleared and verified absent;
- confirm commands execute only inside independent exact-HEAD bundle-created Git
  repositories with no origin, bundle, alternate, source path or real metadata
  backup exposed;
- confirm Linux Landlock ABI 3+ grants persistent filesystem mutation rights only
  below the disposable sandbox, with `/dev/null` as the sole non-persistent sink;
- confirm inherited seccomp denies direct and alternate host metadata mutation,
  including xattr-at, io_uring and x86_64 x32 syscall variants;
- confirm receipts bind sandbox worktree, hidden index state and complete bounded
  Git-metadata state;
- confirm mandatory cleanup and final exact-HEAD/clean-state verification preserve
  the source repository;
- confirm the Linux subreaper terminates escaped-session descendants only with
  positive quiescence acknowledgement;
- confirm unsupported containment fails closed;
- confirm ignored files, hidden index flags and nested repositories count as patch
  mutations and are removed by verified reset;
- confirm no future-slice implementation, non-empty default command registry,
  publication, merge, release, deployment or activation authority exists;
- confirm all required GitHub checks are green on that exact head; and
- return either actionable findings or an explicit no-findings/approval signal.

Any commit after the verdict makes it stale. The authoritative verdict is the
GitHub review or review-bot no-findings signal attached to the exact head; this
artifact deliberately remains true before and after that external event.
