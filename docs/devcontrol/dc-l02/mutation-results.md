# DC-L02 mutation results

Status: **tests authored; exact-head CI execution pending**

Load-bearing mutations:

1. Replace the stale lock's dead-owner identity with a matching live identity.
   Expected result: recovery test fails because the lock must remain.
2. Remove the stale-lock reclaim path.
   Expected result: dead-owner recovery test fails.
3. Remove the per-campaign kernel guard or release it before the campaign critical
   section ends. Expected result: guard serialization/concurrent creator tests fail.
4. Treat a Linux zombie as a live owner.
   Expected result: zombie-owner recovery test fails.
5. Replace the Windows directory flush with a no-op.
   Expected result: Windows handle-open/flush regression fails.
6. Remove parent `fsync` after POSIX atomic replace.
   Expected result: durable replacement regression fails.
7. Stop syncing each newly created store parent.
   Expected result: nested-parent durability regression fails.
8. Accept malformed lock JSON as stale.
   Expected result: malformed-lock fail-closed test fails.
9. Accept a malformed persisted `task_id`.
   Expected result: campaign reload validation test fails.
10. Permit two-event or divergent campaign saves.
    Expected result: compare-and-swap/one-append tests fail.
