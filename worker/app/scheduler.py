"""Scheduled tasks, built on the JobStore (dormant behind KALIV_SCHEDULER).

The benchmark's cheapest category by far -- and the hard parts were paid for
already: the JobStore knows terminal truth, cancellation and restart honesty,
so this file is the two things it does not know: WHEN to run, and WHETHER it is
allowed to at all.

The second one is the real design problem, and it is not cron. The tool gate's
promise is "Anders approves anything that writes". At 03:00 there is nobody to
approve. Three answers were possible:

  * refuse every write -- honest, and turns the feature into an alarm clock
  * park writes for confirmation -- honest, and they expire before morning, so
    the schedule silently does nothing forever
  * approve ONCE, at schedule time, with the arguments frozen

The third is the only one that keeps the promise and does something. Anders
approving "append this exact text every morning" IS Anders approving the write;
what he did not approve is a DIFFERENT write appearing under that approval. So
the approval is bound to a fingerprint of (tool, args): change an argument and
the approval dies with it. That is the gate's immutable-argument invariant,
extended along the time axis.

Two rules follow from the same place and are absolute:
  * `desktop` actions can never be scheduled. A click at 03:00 lands in
    whatever window happens to be there, and screenshot binding cannot save it:
    the screen it was planned against no longer exists.
  * schedules are created by Anders, never by a model. There is no
    model-visible tool here, on purpose -- a model that can create schedules
    can launder a write past its own confirmation card by asking for it later.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass

# "every:900" -> every 900 seconds. "daily:03:00" -> at 03:00 local time.
_EVERY = re.compile(r"^every:(\d+)$")
_DAILY = re.compile(r"^daily:([01]\d|2[0-3]):([0-5]\d)$")

MIN_INTERVAL_S = 60

# A standing grant is the thing to be afraid of here. The gate's confirmation
# card expires after minutes precisely because a stale approval is dangerous,
# and a schedule removes that expiry BY DESIGN: "approve once, at creation,
# with the arguments frozen" quietly means "approve once, forever". You
# approved it in March; in July it still runs and you have forgotten it exists.
# So every approval carries a horizon: schedules expire, and they carry a run
# budget. Renewing is one decision; never being asked again is not a decision
# at all.
DEFAULT_TTL_DAYS = 90
DEFAULT_MAX_RUNS = 0  # 0 = no budget, only the TTL bounds it


class ScheduleError(ValueError):
    """A schedule that cannot be honoured. Never silently downgraded."""


def enabled() -> bool:
    """Dormant by default. Nothing ticks until Anders says so."""
    return os.getenv("KALIV_SCHEDULER", "").strip().lower() in ("1", "true", "on")


def fingerprint(tool: str, args: dict) -> str:
    """What exactly was approved. Sort keys so argument order cannot change it."""
    blob = json.dumps({"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Cadence:
    kind: str          # "every" | "daily"
    seconds: int = 0   # for "every"
    hour: int = 0      # for "daily"
    minute: int = 0


def parse_cadence(spec: str) -> Cadence:
    m = _EVERY.match(spec or "")
    if m:
        secs = int(m.group(1))
        if secs < MIN_INTERVAL_S:
            # Not a safety rail so much as an honesty one: a 5-second schedule
            # is a busy loop wearing a calendar's clothes.
            raise ScheduleError(
                f"interval {secs}s er under minimum {MIN_INTERVAL_S}s"
            )
        return Cadence("every", seconds=secs)
    m = _DAILY.match(spec or "")
    if m:
        return Cadence("daily", hour=int(m.group(1)), minute=int(m.group(2)))
    raise ScheduleError(
        f"ukendt kadence {spec!r} — brug 'every:<sekunder>' eller 'daily:HH:MM'"
    )


def next_run(cadence: Cadence, after: float) -> float:
    """The next moment this should fire, strictly after `after`."""
    if cadence.kind == "every":
        return after + cadence.seconds
    if cadence.kind != "daily":
        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")
    lt = time.localtime(after)
    candidate = time.mktime((
        lt.tm_year, lt.tm_mon, lt.tm_mday,
        cadence.hour, cadence.minute, 0, 0, 0, -1,
    ))
    if candidate <= after:
        candidate = time.mktime((
            lt.tm_year, lt.tm_mon, lt.tm_mday + 1,
            cadence.hour, cadence.minute, 0, 0, 0, -1,
        ))
    return candidate


def catch_up(cadence: Cadence, due_at: float, now: float) -> tuple[int, float]:
    """How many runs were MISSED while the rig was off, and when to fire next.

    Returns (missed, next_due). The count is reported, never executed: a rig
    that was off for a week must not wake up and run seven days of work at
    once, and it must not pretend nothing was skipped either. Intervals use
    arithmetic rather than replaying one timestamp per minute: a year offline
    is still constant-time work at startup.
    """
    if now < due_at:
        return 0, due_at
    if cadence.kind == "every":
        occurrences = int((now - due_at) // cadence.seconds) + 1
        return max(0, occurrences - 1), due_at + occurrences * cadence.seconds
    if cadence.kind != "daily":
        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")
    missed = 0
    due = due_at
    while due <= now:
        due = next_run(cadence, due)
        missed += 1
    # The one we are firing now is not a miss.
    return max(0, missed - 1), due


def refusal(tool_risk: str, approved_fingerprint: str | None,
            current_fingerprint: str, *, now: float | None = None,
            expires_at: float | None = None, runs_used: int = 0,
            max_runs: int = DEFAULT_MAX_RUNS, tools_enabled: bool = True,
            tool_disabled: bool = False) -> str | None:
    """Why this scheduled task must not run, or None.

    Pure: the policy is a fact about (risk, approval, arguments, time), not
    about whatever the caller happens to have in scope at 03:00.
    """
    now = time.time() if now is None else now

    # The kill-switch is not advisory. If Anders switched tools off, a schedule
    # is exactly the thing that must not keep going in the background -- it is
    # the one caller he cannot see refusing.
    if not tools_enabled:
        return "tools er slået fra — planlagte kørsler stopper også"
    if tool_disabled:
        return "dette tool er slået fra — planen venter til det er slået til igen"

    if expires_at is not None and now >= expires_at:
        return (
            "planen er udløbet: en godkendelse holder ikke evigt, og det er "
            "meningen — opret den igen hvis du stadig vil have den"
        )
    if max_runs and runs_used >= max_runs:
        return (
            f"planen har brugt sit budget ({runs_used}/{max_runs} kørsler) — "
            "godkend den igen hvis den skal fortsætte"
        )

    if tool_risk == "desktop":
        return (
            "skrivebordshandlinger kan ikke planlægges: et klik kl. 03:00 lander "
            "i det vindue der tilfældigvis er der, og screenshot-bindingen kan "
            "ikke redde det — skærmen det blev planlagt mod findes ikke længere"
        )
    if tool_risk == "read":
        return None
    if tool_risk != "write":
        return f"ukendt tool-risk {tool_risk!r}; planen er afvist fail-closed"
    if not approved_fingerprint:
        return (
            "planlagte skrivninger kræver at du godkendte dem da du oprettede "
            "planen — der er ingen at spørge kl. 03:00"
        )
    if approved_fingerprint != current_fingerprint:
        return (
            "argumenterne er ændret siden du godkendte planen; godkendelsen "
            "gjaldt den handling, ikke denne"
        )
    return None


@dataclass(frozen=True)
class Schedule:
    """One standing approval, with a horizon on it."""

    schedule_id: str
    tool: str
    args: dict
    cadence: str
    approved_fingerprint: str | None  # None = never approved (reads only)
    expires_at: float
    max_runs: int
    runs_used: int
    due_at: float
    missed: int
    enabled: bool


@dataclass(frozen=True)
class ScheduleClaim:
    """One due occurrence consumed atomically before execution.

    Consuming first gives scheduled writes at-most-once semantics: if the worker
    dies after the claim, the occurrence is skipped rather than potentially
    repeated after a restart. Duplicate writes are worse than a visible miss.

    claim_id ties this occurrence to its durable ledger row (F-902/F-903), so
    job, audit, outcome and recovery all reference the same thing.
    """

    schedule: Schedule
    occurrence_due_at: float
    missed_this_claim: int
    claim_id: str
    # The user-intent revision this claim was taken under (T-013). If the
    # schedule's revision differs at execution time, the grant was paused,
    # resumed or renewed after the claim, and the stale occurrence must not run.
    revision: int = 0


class ScheduleStore:
    """Schedules on disk, next to the jobs they create.

    Same shape as the JobStore on purpose: one connection, one lock, and the
    truth survives a restart. A scheduler whose state lives in memory forgets
    what it promised the moment the rig reboots -- which is the one time you
    most need it to remember.
    """

    def __init__(self, path: str | None = None) -> None:
        import sqlite3
        import threading

        from . import paths as _paths

        self._lock = threading.RLock()
        self.path = path or _paths.resolve("./kaliv-schedules.db", env="KALIV_SCHEDULES_DB")
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS schedules (
                       id TEXT PRIMARY KEY,
                       tool TEXT NOT NULL,
                       args TEXT NOT NULL,
                       cadence TEXT NOT NULL,
                       approved_fingerprint TEXT,
                       expires_at REAL NOT NULL,
                       max_runs INTEGER NOT NULL DEFAULT 0,
                       runs_used INTEGER NOT NULL DEFAULT 0,
                       due_at REAL NOT NULL,
                       missed INTEGER NOT NULL DEFAULT 0,
                       enabled INTEGER NOT NULL DEFAULT 1,
                       created REAL NOT NULL)"""
            )
            # The occurrence-ledger (F-902/F-903). Before this, a claim advanced
            # due_at and lived only in memory: a crash between the claim commit
            # and job creation left an invisible skip -- due_at already past it,
            # no job, no audit, no recovery -- and the run budget was only spent
            # AFTER execution, so a long run or a restart could exceed max_runs.
            #
            # Now every claim writes a durable occurrence row IN THE SAME
            # TRANSACTION that advances due_at, and reserves the budget slot
            # there too. status moves reserved -> executed on success, or
            # reserved -> released (slot returned) on refusal/failure, or
            # reserved -> abandoned (slot returned) at startup recovery for a
            # claim whose worker died in the gap. So the execution truth is
            # durable from the instant the occurrence is taken, not from the
            # instant it finishes.
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS occurrences (
                       claim_id TEXT PRIMARY KEY,
                       schedule_id TEXT NOT NULL,
                       occurrence_due_at REAL NOT NULL,
                       status TEXT NOT NULL,
                       created REAL NOT NULL,
                       resolved REAL)"""
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS occurrences_reserved "
                "ON occurrences (status) WHERE status='reserved'"
            )
            # Migration (T-012): job_id binds the occurrence to its JobStore row
            # so recovery can reconcile a dangling job to a terminal state. The
            # occurrences table shipped in 1.58.116; any DB created by it lacks
            # the column.
            cols = {r[1] for r in self._conn.execute(
                "PRAGMA table_info(occurrences)")}
            if "job_id" not in cols:
                self._conn.execute(
                    "ALTER TABLE occurrences ADD COLUMN job_id TEXT")
            # Migration (T-013): revision counts USER-INTENT mutations -- pause,
            # resume, renewal -- so an in-flight claim can detect that the grant
            # it was taken under no longer exists as claimed. Runner bookkeeping
            # (due_at advance, runs_used, refunds) deliberately does NOT bump it:
            # the runner's own accounting must not invalidate its own claims.
            scols = {r[1] for r in self._conn.execute(
                "PRAGMA table_info(schedules)")}
            if "revision" not in scols:
                self._conn.execute(
                    "ALTER TABLE schedules ADD COLUMN "
                    "revision INTEGER NOT NULL DEFAULT 0")
            # Approval receipts (T-014). The backend token carries WHO approved
            # (device_id) and WHEN (issued_at); before this, verification threw
            # all of it away at the moment of consumption and kept only the
            # fingerprint. A schedule that fires in three weeks could not answer
            # "when did I approve this, and from where?". Each consumed approval
            # -- create or renew -- persists one receipt row, in the same
            # transaction as the grant it authorises.
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS approval_receipts (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       schedule_id TEXT NOT NULL,
                       kind TEXT NOT NULL,
                       fingerprint TEXT NOT NULL,
                       device_id TEXT NOT NULL,
                       nonce TEXT NOT NULL,
                       issued_at INTEGER NOT NULL,
                       consumed_at REAL NOT NULL,
                       revision INTEGER NOT NULL)"""
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(self, tool: str, args: dict, cadence: str, *,
               approve_write: bool = False, ttl_days: int = DEFAULT_TTL_DAYS,
               max_runs: int = DEFAULT_MAX_RUNS, now: float | None = None,
               receipt: dict | None = None) -> Schedule:
        """Record a schedule AND the approval it was created with.

        `approve_write=True` is Anders saying "yes, this exact action, on this
        cadence". It is stored as a fingerprint of (tool, args), so it cannot
        be stretched to cover a different action later.
        """
        import uuid

        now = time.time() if now is None else now
        cad = parse_cadence(cadence)          # raises before anything is stored
        if ttl_days <= 0:
            raise ScheduleError("en plan skal have et udløb — det er hele pointen")
        fp = fingerprint(tool, args) if approve_write else None
        if receipt is not None and fp is None:
            raise ScheduleError(
                "en approval-receipt uden en godkendt write giver ikke mening")
        sched = Schedule(
            schedule_id=uuid.uuid4().hex[:12],
            tool=tool, args=args, cadence=cadence,
            approved_fingerprint=fp,
            expires_at=now + ttl_days * 86400,
            max_runs=max_runs, runs_used=0,
            due_at=next_run(cad, now), missed=0, enabled=True,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO schedules (id, tool, args, cadence, approved_fingerprint,"
                " expires_at, max_runs, runs_used, due_at, missed, enabled, created)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                (sched.schedule_id, tool, json.dumps(args, ensure_ascii=False), cadence,
                 fp, sched.expires_at, max_runs, 0, sched.due_at, 0, now),
            )
            try:
                if receipt is not None:
                    # Same transaction as the grant (T-014): a schedule that
                    # claims human approval without a receipt, or a receipt
                    # without its schedule, must not be able to exist. If this
                    # insert fails the whole create rolls back -- the consumed
                    # token stays burned ("consume before persistence"), and
                    # the user confirms again.
                    self._conn.execute(
                        "INSERT INTO approval_receipts (schedule_id, kind,"
                        " fingerprint, device_id, nonce, issued_at, consumed_at,"
                        " revision) VALUES (?,?,?,?,?,?,?,0)",
                        (sched.schedule_id, "create", fp,
                         receipt["device_id"], receipt["nonce"],
                         int(receipt["issued_at"]),
                         float(receipt["consumed_at"])),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return sched

    def get(self, schedule_id: str) -> Schedule | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
        return self._row(row) if row else None

    def list_all(self) -> list[Schedule]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM schedules ORDER BY due_at").fetchall()
        return [self._row(r) for r in rows]

    def due(self, now: float | None = None, limit: int = 100) -> list[Schedule]:
        """Read-only preview. Runners must use :meth:`claim_due`, not this."""
        now = time.time() if now is None else now
        n = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM schedules WHERE enabled=1 AND due_at<=? "
                "ORDER BY due_at LIMIT ?", (now, n),
            ).fetchall()
        return [self._row(r) for r in rows]

    def claim_due(self, now: float | None = None, limit: int = 20) -> list[ScheduleClaim]:
        """Consume due occurrences exactly once across competing worker processes.

        ``BEGIN IMMEDIATE`` serialises claimers. ``due_at`` is advanced in the
        same transaction that returns each claim, so another process sees the
        future occurrence, not the one already taken. A malformed on-disk
        cadence disables only that schedule fail-closed; it cannot block the
        healthy schedules behind it.
        """
        now = time.time() if now is None else now
        n = max(1, min(int(limit), 100))
        claims: list[ScheduleClaim] = []
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                rows = self._conn.execute(
                    "SELECT * FROM schedules WHERE enabled=1 AND due_at<=? "
                    "ORDER BY due_at LIMIT ?", (now, n),
                ).fetchall()
                for row in rows:
                    schedule = self._row(row)
                    try:
                        cadence = parse_cadence(schedule.cadence)
                        missed, next_due = catch_up(cadence, schedule.due_at, now)
                    except ScheduleError:
                        self._conn.execute(
                            "UPDATE schedules SET enabled=0 WHERE id=?",
                            (schedule.schedule_id,),
                        )
                        continue
                    # Reserve the budget slot AT CLAIM, not after execution
                    # (F-902): the slot is spent the instant the occurrence is
                    # taken, so a long run or a restart cannot exceed max_runs.
                    # An already-exhausted schedule is NOT silently skipped here
                    # -- it is claimed WITHOUT reserving a further slot, so it
                    # still flows through the runner's refusal path, which
                    # disables it and writes the audit the user needs to see why
                    # it stopped. Only a schedule with budget left gets a fresh
                    # reservation.
                    has_budget = (not schedule.max_runs
                                  or schedule.runs_used < schedule.max_runs)
                    reserve = 1 if has_budget else 0
                    cur = self._conn.execute(
                        "UPDATE schedules SET due_at=?, missed=missed+?, "
                        "runs_used=runs_used+? "
                        "WHERE id=? AND enabled=1 AND due_at=?",
                        (next_due, missed, reserve,
                         schedule.schedule_id, schedule.due_at),
                    )
                    if cur.rowcount != 1:
                        continue
                    # Durable occurrence row in the SAME transaction as the
                    # due_at advance and the reservation (F-903). A crash after
                    # this commit leaves a row that startup recovery resolves,
                    # instead of an invisible skip. A claim that reserved no slot
                    # is marked 'reserved_noslot' so recovery does not refund a
                    # slot it never took.
                    claim_id = uuid.uuid4().hex
                    self._conn.execute(
                        "INSERT INTO occurrences "
                        "(claim_id, schedule_id, occurrence_due_at, status, created) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (claim_id, schedule.schedule_id, schedule.due_at,
                         "reserved" if reserve else "reserved_noslot", now),
                    )
                    claimed = Schedule(
                        schedule_id=schedule.schedule_id,
                        tool=schedule.tool,
                        args=schedule.args,
                        cadence=schedule.cadence,
                        approved_fingerprint=schedule.approved_fingerprint,
                        expires_at=schedule.expires_at,
                        max_runs=schedule.max_runs,
                        runs_used=schedule.runs_used + reserve,
                        due_at=next_due,
                        missed=schedule.missed + missed,
                        enabled=True,
                    )
                    claims.append(ScheduleClaim(
                        schedule=claimed,
                        occurrence_due_at=schedule.due_at,
                        missed_this_claim=missed,
                        claim_id=claim_id,
                        revision=row["revision"],
                    ))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return claims

    def record_claim_result(self, schedule_id: str, *, ran: bool,
                            claim_id: str | None = None) -> Schedule | None:
        """Resolve a reserved occurrence after execution (F-902/F-903).

        The budget slot was reserved at claim time, so success needs no further
        increment: the occurrence is marked executed and the count stands. A run
        that did NOT happen -- refused, failed to start, blocked -- returns the
        slot: runs_used is decremented and the occurrence marked released, both
        in one transaction, so a schedule is never charged for a run it did not
        make. Without a claim_id (older callers) the budget effect is preserved
        for compatibility but no ledger row is resolved.
        """
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                if ran:
                    # Budget already spent at claim; just record the outcome.
                    # Either an actual reservation or a no-slot claim (a run past
                    # budget that still executed) is resolved to executed.
                    if claim_id is not None:
                        self._conn.execute(
                            "UPDATE occurrences SET status='executed', resolved=? "
                            "WHERE claim_id=? AND status IN "
                            "('reserved','reserved_noslot')",
                            (time.time(), claim_id),
                        )
                    cur = self._conn.execute(
                        "SELECT 1 FROM schedules WHERE id=?", (schedule_id,))
                    exists = cur.fetchone() is not None
                else:
                    # Return the reserved slot -- but only if this occurrence is
                    # still 'reserved', so a double call cannot refund twice.
                    released = 0
                    if claim_id is not None:
                        # Refund only a real reservation.
                        c = self._conn.execute(
                            "UPDATE occurrences SET status='released', resolved=? "
                            "WHERE claim_id=? AND status='reserved'",
                            (time.time(), claim_id),
                        )
                        released = c.rowcount
                        # A no-slot claim that did not run: resolve it so
                        # recovery ignores it, but there is nothing to refund.
                        self._conn.execute(
                            "UPDATE occurrences SET status='released', resolved=? "
                            "WHERE claim_id=? AND status='reserved_noslot'",
                            (time.time(), claim_id),
                        )
                    # Decrement only when we actually flipped a reserved row (or
                    # when there is no ledger row to guard, for old callers),
                    # and never below zero.
                    if claim_id is None or released == 1:
                        self._conn.execute(
                            "UPDATE schedules SET runs_used=MAX(runs_used-1, 0) "
                            "WHERE id=?",
                            (schedule_id,),
                        )
                    exists = self._conn.execute(
                        "SELECT 1 FROM schedules WHERE id=?", (schedule_id,)
                    ).fetchone() is not None
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            if not exists:
                return None
        return self.get(schedule_id)

    def bind_job(self, claim_id: str, job_id: str) -> None:
        """Tie a claimed occurrence to its JobStore row (T-012).

        The job lives in a separate database, so this cannot be part of the
        claim transaction. It runs immediately after job creation, before
        execution; the residual window (job created, not yet bound) is cosmetic
        -- nothing has executed yet, so recovery still resolves the occurrence
        correctly, and the claim_id stamped in the job detail keeps the row
        forensically traceable.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE occurrences SET job_id=? "
                "WHERE claim_id=? AND status IN ('reserved','reserved_noslot')",
                (job_id, claim_id),
            )
            self._conn.commit()

    def reserved_occurrences(self) -> list[dict]:
        """Every occurrence still awaiting resolution, for recovery (T-012)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT claim_id, schedule_id, job_id, status FROM occurrences "
                "WHERE status IN ('reserved','reserved_noslot')"
            ).fetchall()
        return [dict(r) for r in rows]

    def resolve_recovered(self, claim_id: str, *, executed: bool,
                          now: float | None = None) -> str | None:
        """Resolve one interrupted occurrence with evidence in hand (T-012).

        executed=True: the audit proves ToolGate ran the side effect before the
        crash, so the occurrence becomes 'executed' and the reserved slot STAYS
        SPENT -- refunding a run that happened is how max_runs gets exceeded
        via crash. executed=False: nothing ran; 'abandoned', and the slot is
        refunded -- but only when this claim actually reserved one ('reserved',
        not 'reserved_noslot'), and never below zero. Returns the prior status,
        or None if the occurrence was already resolved (idempotent).
        """
        now = time.time() if now is None else now
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT schedule_id, status FROM occurrences "
                    "WHERE claim_id=? AND status IN "
                    "('reserved','reserved_noslot')",
                    (claim_id,),
                ).fetchone()
                if row is None:
                    self._conn.commit()
                    return None
                new_status = "executed" if executed else "abandoned"
                self._conn.execute(
                    "UPDATE occurrences SET status=?, resolved=? "
                    "WHERE claim_id=?",
                    (new_status, now, claim_id),
                )
                if not executed and row["status"] == "reserved":
                    self._conn.execute(
                        "UPDATE schedules SET runs_used=MAX(runs_used-1, 0) "
                        "WHERE id=?",
                        (row["schedule_id"],),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return row["status"]

    def record_run(self, schedule_id: str, *, ran: bool,
                   now: float | None = None) -> Schedule | None:
        """Atomically advance one known schedule and record the outcome.

        Kept for direct/manual callers. A ticking runner that enumerates all due
        work must use ``claim_due`` plus ``record_claim_result`` so two worker
        processes cannot both execute the same occurrence.
        """
        now = time.time() if now is None else now
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT * FROM schedules WHERE id=?", (schedule_id,),
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    return None
                schedule = self._row(row)
                cadence = parse_cadence(schedule.cadence)
                missed, due = catch_up(cadence, schedule.due_at, now)
                self._conn.execute(
                    "UPDATE schedules SET runs_used=runs_used+?, "
                    "missed=missed+?, due_at=? WHERE id=?",
                    (1 if ran else 0, missed, due, schedule_id),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.get(schedule_id)

    def set_enabled(self, schedule_id: str, enabled: bool,
                    now: float | None = None) -> bool:
        """Persist pause/resume; resume starts at a fresh future occurrence."""
        now = time.time() if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT enabled, cadence FROM schedules WHERE id=?",
                (schedule_id,),
            ).fetchone()
            if row is None:
                return False
            current = bool(row["enabled"])
            if current == enabled:
                return True
            if enabled:
                due = next_run(parse_cadence(row["cadence"]), now)
                self._conn.execute(
                    "UPDATE schedules SET enabled=1, due_at=?, "
                    "revision=revision+1 WHERE id=?",
                    (due, schedule_id),
                )
            else:
                self._conn.execute(
                    "UPDATE schedules SET enabled=0, revision=revision+1 "
                    "WHERE id=?",
                    (schedule_id,),
                )
            self._conn.commit()
        return True

    def approval_receipts(self, schedule_id: str) -> list[dict]:
        """Every consumed approval behind this grant, oldest first (T-014)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, fingerprint, device_id, nonce, issued_at,"
                " consumed_at, revision FROM approval_receipts"
                " WHERE schedule_id=? ORDER BY id",
                (schedule_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def current_guard(self, schedule_id: str) -> dict | None:
        """The live facts a claimed occurrence must re-check before ToolGate (T-013).

        The claim is a snapshot; the batch executes sequentially, so minutes can
        pass between claim and execution. This one read answers: does the grant
        still exist, is it still enabled, and is it still the SAME grant (same
        revision, same approval) the claim was taken under? None means deleted.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT enabled, revision, approved_fingerprint "
                "FROM schedules WHERE id=?",
                (schedule_id,),
            ).fetchone()
        if row is None:
            return None
        return {"enabled": bool(row["enabled"]), "revision": row["revision"],
                "approved_fingerprint": row["approved_fingerprint"]}

    def delete(self, schedule_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
            self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row(row) -> Schedule:
        return Schedule(
            schedule_id=row["id"], tool=row["tool"], args=json.loads(row["args"]),
            cadence=row["cadence"], approved_fingerprint=row["approved_fingerprint"],
            expires_at=row["expires_at"], max_runs=row["max_runs"],
            runs_used=row["runs_used"], due_at=row["due_at"], missed=row["missed"],
            enabled=bool(row["enabled"]),
        )
