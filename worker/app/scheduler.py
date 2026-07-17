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
    """

    schedule: Schedule
    occurrence_due_at: float
    missed_this_claim: int


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
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(self, tool: str, args: dict, cadence: str, *,
               approve_write: bool = False, ttl_days: int = DEFAULT_TTL_DAYS,
               max_runs: int = DEFAULT_MAX_RUNS, now: float | None = None) -> Schedule:
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
            self._conn.commit()
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
                    cur = self._conn.execute(
                        "UPDATE schedules SET due_at=?, missed=missed+? "
                        "WHERE id=? AND enabled=1 AND due_at=?",
                        (next_due, missed, schedule.schedule_id, schedule.due_at),
                    )
                    if cur.rowcount != 1:
                        continue
                    claimed = Schedule(
                        schedule_id=schedule.schedule_id,
                        tool=schedule.tool,
                        args=schedule.args,
                        cadence=schedule.cadence,
                        approved_fingerprint=schedule.approved_fingerprint,
                        expires_at=schedule.expires_at,
                        max_runs=schedule.max_runs,
                        runs_used=schedule.runs_used,
                        due_at=next_due,
                        missed=schedule.missed + missed,
                        enabled=True,
                    )
                    claims.append(ScheduleClaim(
                        schedule=claimed,
                        occurrence_due_at=schedule.due_at,
                        missed_this_claim=missed,
                    ))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return claims

    def record_claim_result(self, schedule_id: str, *, ran: bool) -> Schedule | None:
        """Record whether an already-consumed claim actually executed."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE schedules SET runs_used=runs_used+? WHERE id=?",
                (1 if ran else 0, schedule_id),
            )
            self._conn.commit()
            if cur.rowcount != 1:
                return None
        return self.get(schedule_id)

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
                    "UPDATE schedules SET enabled=1, due_at=? WHERE id=?",
                    (due, schedule_id),
                )
            else:
                self._conn.execute(
                    "UPDATE schedules SET enabled=0 WHERE id=?",
                    (schedule_id,),
                )
            self._conn.commit()
        return True

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
