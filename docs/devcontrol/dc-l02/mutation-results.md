# DC-L02 mutation results

Status: **executed successfully on implementation candidate**

Implementation candidate: `952da3c1409c6f5a34833b248cdb7c498e97d1f8`
CI: #2916 successful

Load-bearing mutation coverage:

1. A matching live lock identity remains locked and cannot be reclaimed.
2. A provably dead owner lock is reclaimed.
3. The persistent per-campaign kernel guard prevents a second contender from entering the reclaim/critical window.
4. Two concurrent stale-lock reclaimers produce exactly one successful creator.
5. A Linux zombie owner is classified as dead and recoverable.
6. Windows directory durability opens a directory handle with backup-semantics/write-through flags and calls `FlushFileBuffers`.
7. POSIX atomic replacement syncs the parent directory.
8. Each newly created nested store directory causes its parent to be synchronized.
9. Malformed lock JSON fails closed.
10. A malformed persisted `task_id` fails reload verification.
11. Campaign save accepts exactly one valid append and rejects stale or divergent compare-and-swap state.

The complete DC-L01–L02 unittest discovery and final-boundary regressions passed in CI #2916.
