# DC-L03 exact-head validation

Status: **pending**

Candidate head: not yet committed.

Required gates:

- diff equals the 16-path allowlist;
- branch is based on the declared fresh `main` head;
- all five locked source paths have one projection disposition and provenance;
- package import remains dormant;
- `default_registry()` remains empty;
- no product code imports `kaliv_dev_control`;
- no GitHub write, non-GET HTTP, remote Git or activation authority appears;
- all nine landed DevControl test modules are reached by CI;
- full CI, CodeQL, agent3-diagnostics and agent3-full-diagnostics succeed on the
  exact candidate head;
- independent reviewer different from the author returns no actionable finding.
