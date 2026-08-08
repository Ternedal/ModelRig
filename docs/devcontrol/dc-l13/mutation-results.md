# DC-L13 mutation results

## Raw import red state

The six locked source blobs were imported atomically on `ae00850f1569b5a6f0bc15d028ba387a069154cf`.

Expected integration failures were observed:

- the landed facade referenced a rejected legacy helper file;
- the repository inventory still expected 49 DC-L01–L12 modules; and
- prior-slice gates still required DC-L13 modules to be absent.

CodeQL, ordinary diagnostics and product/platform containment remained unaffected by the raw import.

## Security projection

The rejected dynamic helper was replaced with a static internal package. Mutation checks proved that removing or reintroducing the following boundaries changes the result from green to red:

- legacy process runner or executable materialize/verify entrypoints;
- dynamic `globals().update` proxying;
- `_compatibility_v1` distribution;
- remote/push/credential/signing command strings;
- package-root, Tier-A or ToolHost exports;
- closed-schema true/false receipt claims; and
- the exact 51-module workflow inventory.

## Progressive validation

Before exact-head freeze:

- workflow coverage: **44 passed, 0 failed**;
- dedicated DC-L13 plus foundation tests: **29 passed, 0 failed**;
- YAML parse and `git diff --check`: passed; and
- temporary projection files were removed in the verified workflow commit.

Final repository-wide results must be supplied by the unchanged exact-head workflows named in `exact-head-validation.md`.
