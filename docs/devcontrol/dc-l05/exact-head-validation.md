# DC-L05 exact-head validation

Status: **pending on the final frozen head**

The seed commit `89a20b3c2674cb4184f05bcf818640bc82111ad5`
contains only the 15 locked source files and is not merge evidence.

The final head must prove:

- exactly the 26 paths in `exact-path-allowlist.json` differ from
  `main @ a1fe16f05ba312e719b1254bba9919809bab4215`;
- branch distance is 0 commits behind current `main`;
- product modules contain no `kaliv_dev_control` import;
- native Job Object, AppContainer, environment and ToolHost contracts pass on a
  real Windows runner;
- the later DevControl bounded-subprocess, catalog/closure and Git-aware receipt
  support programs are not activated by this slice;
- portable repository and DevControl tests remain green;
- CodeQL and both diagnostics workflows pass; and
- all review threads are resolved.

Workflow run IDs and the exact final SHA are recorded in the pull-request body
after the branch stops changing. A green ancestor does not satisfy this gate.
