"""Durable alarm delivery outbox; inert until a trusted executor supplies jobs.

Enqueueing is not activation, and claiming a job is not delivery. Only a
transport with a valid claim token can acknowledge a leased job. The client
must deduplicate by timer_id because a lost acknowledgement can cause retries.
"""
from __future__ import annotations

import math
import sqlite3
import time
import uuid
from dataclasses import dataclass

from .voice_timer_state_ledger import TimerStateLedger


@dataclass(frozen=True)
class AlarmClaim:
    timer_id: str
    delivery_token: str
    lease_until: float
    attempts: int


def _finite_time(now: float | None) -> float:
    if now is None:
        return time.time()
    if isinstance(now, bool) or not isinstance(now, (float, int)) or not math.isfinite(now):
        raise ValueError("finite timestamp required")
    return float(now)


class TimerAlarmOutbox:
    def __init__(self, path: str):
        if not isinstance(path, str) or not path.strip():
            raise ValueError("explicit database path required")
        self.path = path
        # Shared ledger must exist even when no timer was registered yet.
        # This creates schema only; it never creates a due timer.
        with TimerStateLedger(path):
            pass
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS voice_timer_alarm_outbox ("
                "timer_id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                "lease_token TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0)"
            )

    def enqueue_due(self, timer_id: str) -> bool:
        """Enqueue only an already-due timer recorded in the shared ledger."""
        if not isinstance(timer_id, str) or not timer_id.strip():
            raise ValueError("invalid timer id")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            # Fail closed if no trusted lifecycle has recorded a due timer.
            # The same SQLite transaction locks the ledger check and outbox
            # insertion so cancellation cannot race between them.
            row = db.execute(
                "SELECT state FROM voice_timer_state_ledger WHERE timer_id=?",
                (timer_id,),
            ).fetchone()
            if row is None or row[0] != "due":
                return False
            result = db.execute(
                "INSERT OR IGNORE INTO voice_timer_alarm_outbox"
                "(timer_id,status) VALUES (?,'queued')", (timer_id,)
            )
            return result.rowcount == 1

    def claim(self, timer_id: str, *, now: float | None = None, lease_seconds: int = 30) -> AlarmClaim | None:
        if not isinstance(timer_id, str) or not timer_id.strip():
            raise ValueError("invalid timer id")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ValueError("invalid lease length")
        current = _finite_time(now)
        token = str(uuid.uuid4())
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute(
                "SELECT state FROM voice_timer_state_ledger WHERE timer_id=?",
                (timer_id,),
            ).fetchone()
            if state is None or state[0] != "due":
                return None
            update = db.execute(
                "UPDATE voice_timer_alarm_outbox SET status='leased', "
                "lease_token=?, lease_until=?, attempts=attempts+1 "
                "WHERE timer_id=? AND (status='queued' OR "
                "(status='leased' AND lease_until<=?))",
                (token, current+lease_seconds, timer_id, current),
            )
            if update.rowcount != 1:
                return None
            attempts = db.execute(
                "SELECT attempts FROM voice_timer_alarm_outbox WHERE timer_id=?",
                (timer_id,),
            ).fetchone()[0]
            return AlarmClaim(timer_id, token, current+lease_seconds, attempts)

    def claim_next(self, *, now: float | None = None, lease_seconds: int = 30) -> AlarmClaim | None:
        """Atomically lease one eligible due alarm without caller-supplied ID.

        This only reserves a database item: no transport or device is called.
        Cancelled/missing timers are excluded even if old outbox rows remain.
        """
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ValueError("invalid lease length")
        current = _finite_time(now)
        token = str(uuid.uuid4())
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT o.timer_id FROM voice_timer_alarm_outbox o "
                "JOIN voice_timer_state_ledger l ON l.timer_id=o.timer_id "
                "WHERE l.state='due' AND (o.status='queued' OR "
                "(o.status='leased' AND o.lease_until<=?)) "
                "ORDER BY o.attempts ASC, o.timer_id ASC LIMIT 1",
                (current,),
            ).fetchone()
            if row is None:
                return None
            timer_id = row[0]
            result = db.execute(
                "UPDATE voice_timer_alarm_outbox SET status='leased', "
                "lease_token=?, lease_until=?, attempts=attempts+1 "
                "WHERE timer_id=? AND (status='queued' OR "
                "(status='leased' AND lease_until<=?))",
                (token, current+lease_seconds, timer_id, current),
            )
            if result.rowcount != 1:
                raise RuntimeError("outbox claim lost while holding write lock")
            attempts = db.execute(
                "SELECT attempts FROM voice_timer_alarm_outbox WHERE timer_id=?",
                (timer_id,),
            ).fetchone()[0]
            return AlarmClaim(timer_id, token, current+lease_seconds, attempts)

    def acknowledge(self, claim: AlarmClaim, *, now: float | None = None) -> bool:
        if not isinstance(claim, AlarmClaim):
            raise ValueError("valid claim required")
        current = _finite_time(now)
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute(
                "SELECT state FROM voice_timer_state_ledger WHERE timer_id=?",
                (claim.timer_id,),
            ).fetchone()
            if state is None or state[0] != "due":
                return False
            update = db.execute(
                "UPDATE voice_timer_alarm_outbox SET status='delivered',"
                "lease_token=NULL, lease_until=NULL "
                "WHERE timer_id=? AND status='leased' AND lease_token=? "
                "AND lease_until>?",
                (claim.timer_id, claim.delivery_token, current),
            )
            if update.rowcount != 1:
                return False
            changed = db.execute(
                "UPDATE voice_timer_state_ledger SET state='delivered', "
                "revision=revision+1 WHERE timer_id=? AND state='due'",
                (claim.timer_id,),
            )
            if changed.rowcount != 1:
                raise RuntimeError("alarm acknowledgement/ledger mismatch")
            return True

    def cancel_due(self, timer_id: str) -> bool:
        """Cancel a due timer and suppress its queued/leased alarm atomically.

        An already delivered timer cannot be cancelled retroactively. No
        network recall is promised for alarms already sent to a client.
        """
        if not isinstance(timer_id, str) or not timer_id.strip():
            raise ValueError("invalid timer id")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute(
                "SELECT state FROM voice_timer_state_ledger WHERE timer_id=?",
                (timer_id,),
            ).fetchone()
            if state is None or state[0] != "due":
                return False
            outbox = db.execute(
                "SELECT status FROM voice_timer_alarm_outbox WHERE timer_id=?",
                (timer_id,),
            ).fetchone()
            if outbox is not None and outbox[0] == "delivered":
                return False
            update = db.execute(
                "UPDATE voice_timer_state_ledger SET state='cancelled', "
                "revision=revision+1 WHERE timer_id=? AND state='due'",
                (timer_id,),
            )
            if update.rowcount != 1:
                raise RuntimeError("due timer cancellation lost")
            db.execute(
                "UPDATE voice_timer_alarm_outbox SET status='cancelled', "
                "lease_token=NULL, lease_until=NULL "
                "WHERE timer_id=? AND status IN ('queued','leased')",
                (timer_id,),
            )
            return True

    def status(self, timer_id: str) -> str | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT status FROM voice_timer_alarm_outbox WHERE timer_id=?",
                (timer_id,),
            ).fetchone()
            return row[0] if row else None
