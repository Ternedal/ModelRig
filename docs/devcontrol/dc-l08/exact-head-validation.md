# DC-L08 exact-head validation

**Status:** pending final head freeze and workflow completion.

## Required head

Validation is accepted only when all evidence below names the same final commit
as the DC-L08 pull request and the branch is zero commits behind `main`.

## Required workflows

| Workflow | Run | Conclusion |
|---|---:|---|
| `ci` | pending | pending |
| `codeql` | pending | pending |
| `agent3-diagnostics` | pending | pending |
| `agent3-full-diagnostics` | pending | pending |

## Required structural checks

- exact diff equals the 18 paths in `exact-path-allowlist.json`;
- all twenty-eight DC-L01–DC-L08 test modules are reached by CI;
- all three locked source paths have only the projections recorded in
  `source-provenance.json` and `source-path-disposition.json`;
- the modern executor requires a signed runtime closure and closure verifier;
- package root, compatibility core and authority surface export no executor;
- static package import does not import the native `app.windows_*` substrate;
- final `tier_a_execution.py`, command receipt and trusted-Git modules remain absent;
- both v6 bundle tuples are identical and include each private executor once;
- the real-Windows closure-bound AppContainer, Job Object, bounded-output,
  timeout, cwd and runtime-lifetime contract passes;
- the generic bounded-subprocess and command-receipt Windows contracts remain
  deferred rather than being claimed by DC-L08;
- unresolved review-thread count is zero; and
- the independent verdict names the same frozen head.

This document must not be changed to `success` from queued, partial, stale-head or
locally inferred evidence.
