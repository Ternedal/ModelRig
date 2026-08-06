# DC-L03 exact-head validation

Status: **candidate committed; exact-head checks pending**

Implementation candidate: `6c1e2d79684e1a15ce8f9932684a9dbd863533e6`.

The implementation candidate contains the complete 16-path allowlist and includes
sealed Linux executable-object pinning, strict catalog environment policy,
fixed-host GET-only GitHub reads, Git-blob verification, concrete integer receipt
status validation, and a pathname-swap regression that launches only the sealed
verified bytes. This evidence update intentionally changes the branch head; all
final conclusions must bind to the resulting exact head, not the implementation
candidate above.

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
