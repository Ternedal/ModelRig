# DC-L04 exact-head validation

**Status:** pending on the final candidate head.

The seed commit `5064c74e35237fdd42feb01a53b7f7ebb20fef3c`
contains only the seven locked source files and is not merge evidence.

The final exact head must prove:

- changed paths equal the 19-path allowlist;
- branch base is the merged DC-L03 main commit
  `b717055790947ea848418964e7ebd78c39c39ee3` or a documented later current-main
  synchronization;
- Python syntax and undefined-name checks pass;
- full DevControl unittest discovery passes;
- repository workflow coverage passes;
- complete repository CI, CodeQL, agent3 diagnostics and full diagnostics pass;
- the default catalog remains empty and non-empty materialization remains
  fail-closed; and
- no unresolved exact-head review thread remains.

Workflow run IDs and the final head SHA will be recorded after the candidate stops
changing. A green ancestor does not satisfy this gate.
