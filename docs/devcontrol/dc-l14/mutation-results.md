# DC-L14 mutation results

## Raw red state

The 11 source-exact paths were imported atomically at `cab3004a3fc2bae6588113179e20647ceb3a86c2`. Product, Windows and diagnostics surfaces remained green. The focused source contracts reported one stale 38-file inventory, a malformed JSON path containing Python facade text, an obsolete 12-file/v2 toolhost expectation, and publisher assertions tied to rejected `_compatibility_v1` code.

## Progressive green state

The projection regenerated the 50-file authority lock/report, produced a valid v10 import-only split contract, updated protocol ownership to the recursive supported tree, physically excluded `_compatibility_v1`, and added a deterministic local artifact builder. Sixteen focused inventory, split, toolhost, protocol, closure and packaging tests passed, including byte-identical wheel and normalized sdist builds.

## Final freeze state

The candidate is restricted to the exact 25-path allowlist, contains no temporary generator or workflow helper, remains zero commits behind its recorded base, and grants no remote publication or terminal mutation authority. Any head mutation requires a fresh run of `ci`, `codeql`, `agent3-diagnostics` and `agent3-full-diagnostics`; the checks attached to the current PR head are the authoritative validation record.
