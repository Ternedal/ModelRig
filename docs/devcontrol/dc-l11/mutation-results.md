# DC-L11 mutation results

**Status:** load-bearing mutations encoded; exact-head execution pending.

## Required red states

| Mutation | Expected gate |
|---|---|
| Change task, patch, receipt, semantic request, signed verdict or execution-authority identity | readiness verification and model tests |
| Let caller select repository, proposed branch, title, body, operations or merge authority | constructor-signature and deterministic presentation tests |
| Use developer or reviewer as publisher | publisher actor-separation tests |
| Change publisher key, actor, nonce, request hash or signature | publisher verifier tests |
| Remove or reorder one of the five dry-run operations | deterministic plan tests |
| Set any executed/write/commit/branch/push/PR/review/merge/release/deploy flag true | dry-run receipt fail-closed tests |
| Overwrite, symlink or publish through a non-durable path | create-once durable publication tests |
| Add Git, HTTP, GitHub, credential or subprocess adapter | explicit L11 workflow and coverage boundary |
| Export readiness/publisher symbols from package root or Tier-A facade | explicit L11 workflow boundary |
| Add DC-L11 files to the v7 execution bundle | explicit bundle exclusion gate |
| Land L12 authorization/replay/recovery or L13 materialization | future-module gates |
| Omit any of the 39 landed test modules | exact workflow coverage inventory |

The raw fourteen-file import is intentionally tested before and after progressive integration. Any concrete red state observed in CI is recorded in the pull-request body. Green evidence is valid only for one unchanged exact head.
