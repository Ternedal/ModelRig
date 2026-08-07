# DC-L07 exact-head validation

**Status:** pending final head freeze and workflow completion.

## Required head

Validation is accepted only when all evidence below names the same final commit
as PR #387 and the branch is zero commits behind `main`.

## Required workflows

| Workflow | Run | Conclusion |
|---|---:|---|
| `ci` | pending | pending |
| `codeql` | pending | pending |
| `agent3-diagnostics` | pending | pending |
| `agent3-full-diagnostics` | pending | pending |

## Required structural checks

- exact diff equals the 44 paths in `exact-path-allowlist.json`;
- all twenty-seven DC-L01–DC-L07 test modules are reached by CI;
- no executor, command receipt, trusted-Git, publisher or remote-authority module is present;
- prepared permission metadata is flushed before create-once publication;
- Windows permission repair is flushed before positive staging evidence;
- unresolved review-thread count is zero; and
- the independent verdict names the same frozen head.

This document must not be changed to `success` from queued, partial, stale-head or
locally inferred evidence.
