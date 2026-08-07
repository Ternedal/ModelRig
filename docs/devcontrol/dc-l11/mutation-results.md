# DC-L11 mutation results

**Status:** load-bearing mutations encoded; implementation candidate green.

## Required red states

| Mutation | Detecting contract |
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
| Add DC-L11 files to the v7 execution bundle | explicit bundle-exclusion gate |
| Land L12 authorization/replay/recovery or L13 materialization | future-module gates |
| Omit any of the 39 landed test modules | exact workflow coverage inventory |

## Observed integration states

The raw fourteen-file source import at
`7b842e1c47d7085dd9922118ff75b2737760f409` was executed before progressive
integration. CodeQL run 2203, Agent3 Diagnostics run 1343 and Agent3 Full
Diagnostics run 2425 succeeded. CI run 3187 reached the repository test loop
after backend build, vet, backend tests, Python lint and PowerShell syntax had
all succeeded. The only failing contract was `tests/workflow_test_coverage.py`:
it still required the exact thirty-five-module DC-L01–L10 inventory and still
required DC-L11 readiness/publisher modules to remain absent. The result was
28 passed and 2 failed coverage assertions. Product code, Windows containment
and platform gates did not produce the red state.

The progressive integration advances the exact inventory from 35 to 39 modules,
adds the dedicated `DC-L11 draft readiness and publisher dry-run` workflow gate,
records L11 as landed in the foundation inventory, and keeps L12 authorization,
replay/recovery and L13 materialization fail-closed. It does not bypass or weaken
a product or DevControl test.

The first complete 26-path implementation candidate at
`ebc08c7b56122114692a572607dcb0eb24d3dc76` passed CI run 3188, CodeQL run 2204,
Agent3 Diagnostics run 1344 and Agent3 Full Diagnostics run 2426. All 39
DevControl modules and the existing repository, security-analysis and platform
gates passed.

Green evidence remains valid only when the final documentation head also passes
all four required workflows unchanged.
