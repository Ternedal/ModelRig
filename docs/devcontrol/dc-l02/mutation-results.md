# DC-L02 mutation results

Status: **tests authored; CI execution pending**

Load-bearing mutations:

1. Replace the stale lock's dead-owner identity with a matching live identity.
   Expected result: recovery test fails because the lock must remain.
2. Remove the stale-lock reclaim path.
   Expected result: dead-owner recovery test fails.
3. Remove parent `fsync` after POSIX atomic replace.
   Expected result: durable replacement regression fails.
4. Stop syncing each newly created store parent.
   Expected result: nested-parent durability regression fails.
5. Accept malformed lock JSON as stale.
   Expected result: malformed-lock fail-closed test fails.
6. Permit two-event or divergent campaign saves.
   Expected result: compare-and-swap/one-append tests fail.
