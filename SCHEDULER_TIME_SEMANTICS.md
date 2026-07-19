# Scheduler time semantics — T-017 reference contract

**Status: design + executable reference oracle only. Not wired into the worker, API, database or Android client.**

This document freezes the intended civil-time behavior before the scheduler's
runtime/storage migration begins. The executable reference is
`scripts/scheduler_time_oracle.py`; `tests/scheduler_time_oracle.py` proves the
edge cases. Until the later integration PR is merged, production behavior remains
the current process-local `time.localtime` / `time.mktime` implementation.

## Why the current representation is insufficient

A persisted value such as `daily:08:00` does not identify an instant. It needs a
civil timezone and a policy for clock gaps, overlaps and downtime. Today the
worker:

- stores only the cadence string and absolute `due_at`;
- recomputes future daily runs in whatever timezone the process currently uses;
- relies on `mktime` to decide spring-forward and fall-back behavior;
- coalesces downtime implicitly, without persisting a named policy;
- does not bind timezone/misfire semantics into the preview approval.

That means a Windows timezone change, DST transition or client/server assumption
can change the promise after it was approved. T-017 makes every one of those
choices explicit and version-bound.

## Frozen policy decisions

### 1. Every schedule has an explicit IANA timezone

New schedule create/renew requests carry `timezone`, for example
`Europe/Copenhagen`. The worker validates it with `zoneinfo.ZoneInfo`; aliases
accepted by the installed IANA database are allowed, but empty, Windows display
names and unknown names are rejected.

The timezone is persisted with the standing grant and included in preview,
approval-token binding, approval receipt, list/detail response and audit summary.
A later change of the rig's system timezone does not change an existing schedule.

Windows Python must have an available IANA database. The integration phase must
pin the `tzdata` package rather than depend on a particular host image.

### 2. Interval cadence is absolute time

`every:<seconds>` means an absolute duration between scheduled instants. DST and
civil-time offset changes do not shorten or lengthen it. The timezone is retained
for consistent display and contract shape, but does not participate in interval
arithmetic.

### 3. Daily cadence is civil time in the persisted zone

`daily:HH:MM` means that wall-clock label in the persisted IANA zone.
The server is the sole calculator of `due_at`; clients display server-returned
UTC and local representations and never recalculate a competing instant.

### 4. Spring-forward gap: skip the nonexistent civil date

When `HH:MM` does not exist because the clock moves forward, that day's occurrence
is skipped. The next candidate is the same wall time on the next date where it
exists.

This is intentionally conservative for standing writes: the user approved an
exact civil label, not “some time after the gap”. The skip is visible in the
occurrence/missed accounting and consumes no run-budget slot.

Example for `Europe/Copenhagen` in 2026:

- `daily:02:30` has no occurrence on 29 March 2026;
- the next occurrence is 30 March 2026 at 02:30 local.

### 5. Fall-back overlap: first occurrence, exactly once

When `HH:MM` occurs twice, the earlier UTC instant (`fold=0`) is selected. The
second fold is not emitted as another daily occurrence.

Example for `Europe/Copenhagen` on 25 October 2026:

- the chosen 02:30 is 00:30 UTC (summer offset);
- the repeated 02:30 at 01:30 UTC is not another run.

### 6. Misfire policy: `coalesce_once`

The initial supported policy is named and persisted as `coalesce_once`.
If one or more occurrences became due during sleep, reboot or downtime:

- at most one occurrence becomes claimable when the scheduler resumes;
- that claim keeps the oldest overdue `occurrence_due_at` for audit truth;
- all additional overdue occurrences increment `missed`;
- `next_due_at` advances to the first future occurrence;
- only the one coalesced claim reserves a run-budget slot;
- skipped occurrences never execute later as a burst.

A paused schedule that is explicitly resumed/renewed keeps the existing behavior:
start from a fresh future occurrence, not from accumulated downtime.

### 7. Clock rollback cannot replay an occurrence

`due_at` remains an absolute UTC epoch and is advanced transactionally with the
occurrence ledger. After a claim, a backwards wall-clock adjustment sees the
persisted next future due instant; it cannot recreate the consumed local label.

The integration migration must additionally enforce a unique database constraint
on `(schedule_id, occurrence_due_at)` so a duplicate absolute occurrence cannot
be inserted even if a future code path regresses.

## Versioned contract changes required in the integration phase

### Storage

Add to `schedules`:

- `timezone TEXT NOT NULL` containing a validated IANA name;
- `misfire_policy TEXT NOT NULL` initially restricted to `coalesce_once`.

Add a unique index to `occurrences(schedule_id, occurrence_due_at)`.
Keep `due_at` and occurrence timestamps as UTC epoch values.

Legacy migration must not guess a daily timezone from the host clock:

- legacy `every:*` rows may migrate to `Etc/UTC` while preserving `due_at`;
- legacy `daily:*` rows require an explicit, validated
  `KALIV_SCHEDULER_LEGACY_ZONE` during migration;
- if daily rows exist and that setting is absent/invalid, scheduler startup fails
  with a concrete migration error and performs no claims.

### Preview and approval

Increment the standing-grant approval schema version. The approval fingerprint and
single-use approval token must bind at least:

- operation and schedule id;
- tool and immutable args;
- cadence;
- timezone;
- misfire policy;
- TTL and run budget;
- requested enabled state.

Changing timezone or misfire policy therefore requires a new preview and approval.

### API response

Preview and schedule detail/list responses return server-derived:

- `timezone`;
- `misfire_policy`;
- `due_at` as UTC epoch;
- `due_at_utc` as an ISO-8601 string;
- `due_at_local` including numeric offset;
- resolution information where useful (`normal`, `ambiguous_earlier`, or a
  skipped-gap counter/reason).

Android displays these fields. It may format the returned instant for presentation,
but it does not derive a different next run from `daily:HH:MM` locally.

## Integration test matrix

The later runtime PR is not complete until tests cover:

1. valid and invalid IANA names, including Windows with pinned `tzdata`;
2. normal daily resolution in at least two zones;
3. Copenhagen spring-forward gap: skipped date and next valid date;
4. Copenhagen fall-back overlap: earlier instant exactly once;
5. interval cadence spanning both DST transitions without duration drift;
6. one and many overdue occurrences under `coalesce_once`;
7. run-budget reservation: one slot for one coalesced claim;
8. paused/resumed schedule starts in the future;
9. system timezone change does not change persisted-zone output;
10. backwards clock movement does not produce a second occurrence;
11. migration with explicit legacy zone;
12. migration refusal when daily rows exist and legacy zone is unavailable;
13. preview/token mismatch when timezone or misfire changes;
14. API and Android display the server's zone and next instant;
15. occurrence-ledger uniqueness under concurrent/fault-injected claims.

## Rollout order

1. Merge this design/reference only after the physical validation freeze is lifted.
2. Add database migration and fail-closed legacy-zone handling.
3. Replace worker time arithmetic with the reviewed oracle behavior.
4. Bind timezone/misfire into preview, approval token and receipts.
5. Update Go passthrough models and Android display/input.
6. Run unit, migration, occurrence-ledger and fault-injection suites.
7. Run the physical scheduler pilot before promoting Scheduler.

No step in this document enables `KALIV_SCHEDULER` or changes production routing.
