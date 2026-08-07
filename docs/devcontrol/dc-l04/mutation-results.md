# DC-L04 mutation results

**Status:** planned; red/green evidence pending final implementation.

Load-bearing mutations for this slice:

1. Remove one mandatory probe: report construction must reject.
2. Duplicate a probe name: report construction must reject.
3. Mark one probe failed: verification must reject without erasing the failure.
4. Reuse the collector as approver: report construction must reject.
5. Keep the reboot markers equal: report construction must reject.
6. Change task/base/catalog/toolchain identity: exact attestation binding must reject.
7. Sign with the wrong or untrusted key: signature verification must reject.
8. Supply stale or future evidence: freshness validation must reject.
9. Add a duplicate matching evidence file: ambiguity must reject.
10. Supply pretty/non-canonical JSON: loading must reject.
11. Supply a symlink, FIFO, oversized file or replace a path during reading: the
    stable bounded regular-file reader must reject.
12. Attempt to materialize a non-empty catalog after valid physical verification:
    DC-L03's fail-closed execution deferral must still reject.
13. Race durable evidence publication: exactly one writer must win and no temporary
    sibling may remain.
14. Inject durable publication failure: no final artifact may remain.
15. Resolve an operator symlink in the CLI before validation: the mutation must
    demonstrate why preserving the original absolute path is required.

Each mutation will be executed against the exact candidate head and linked to the
corresponding passing regression before the PR leaves draft.
