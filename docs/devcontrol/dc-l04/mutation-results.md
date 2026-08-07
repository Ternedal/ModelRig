# DC-L04 mutation results

**Status:** implemented in focused regressions; final exact-head workflow evidence pending.

Load-bearing mutations for this slice:

1. Remove one mandatory probe: report construction rejects.
2. Duplicate a probe name: report construction rejects.
3. Mark one probe failed: verification rejects without erasing the failure.
4. Reuse the collector as approver: report construction rejects.
5. Keep the reboot markers equal: report construction rejects.
6. Change task/base/catalog/toolchain identity: exact attestation binding rejects.
7. Sign with the wrong or untrusted key: signature verification rejects.
8. Supply stale or future evidence: freshness validation rejects.
9. Add a duplicate matching evidence file: ambiguity rejects.
10. Supply pretty/non-canonical JSON: loading rejects.
11. Supply a symlink, junction/reparse-like component, FIFO, oversized file or
    replace a path during reading: the stable bounded regular-file reader rejects.
12. Attempt to materialize a non-empty catalog after valid physical verification:
    DC-L03's fail-closed execution deferral still rejects.
13. Race durable evidence publication: exactly one writer wins and no temporary
    sibling remains.
14. Inject durable publication failure: no final artifact remains.
15. Resolve an operator symlink in the CLI before validation: the regression proves
    why preserving the original absolute path is required.
16. Weaken operator key ownership, permissions, hard-link count or parent custody:
    key loading rejects; Windows remains fail-closed until native ACL verification.
17. Mutate the supplied isolation attestation during candidate loading: verification
    stays bound to the private canonical snapshot.
18. Reintroduce a future-slice import into the landed foundation: the progressive
    dependency gate rejects DC-L05+ authority while permitting landed DC-L03/DC-L04.
19. Omit a DC-L04 test module from repository discovery: workflow coverage rejects.

Focused DC-L04 tests, complete DevControl discovery, repository workflow coverage
and all exact-head workflows must pass on the final frozen head before merge.
