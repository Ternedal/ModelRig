"""Durable due-time promotion for already-active timers; no activation authority.

The trusted activation service must write an ACTIVE ledger row and register its
deadline in the SAME transaction before this module can be enabled in a worker.
This module cannot create an active timer, send a notification or assert receipt.
"""
from __future__ import annotations

import math
import sqlite3
import time

from .voice_timer_state_ledger import TimerStateLedger
from .voice_timer_alarm_outbox import TimerAlarmOutbox


class TimerDueSweeper:
    def __init__(self, path: str):
        if not isinstance(path, str) or not path.strip():
            raise ValueError("shared database path required")
        self.path = path
        with TimerStateLedger(path):
            pass
        TimerAlarmOutbox(path)
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS voice_timer_deadlines ("
                "timer_id TEXT PRIMARY KEY, due_at REAL NOT NULL)"
            )

    def register_active_deadline(self, timer_id: str, *, due_at: float) -> bool:
        """Record deadline only for an already ACTIVE timer, once.

        This is not authorization: activating ledger rows remains impossible
        through this class and requires a separate authenticated executor.
        """
        if not isinstance(timer_id, str) or not timer_id.strip():
            raise ValueError("invalid timer id")
        if isinstance(due_at, bool) or not isinstance(due_at, (int, float)) or not math.isfinite(due_at):
            raise ValueError("finite deadline required")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM voice_timer_state_ledger WHERE timer_id=?", (timer_id,)
            ).fetchone()
            if row is None or row[0] != "active":
                return False
            result = db.execute(
                "INSERT OR IGNORE INTO voice_timer_deadlines(timer_id,due_at) "
                "VALUES (?,?)", (timer_id, float(due_at))
            )
            return result.rowcount == 1

    def cancel_active(self, timer_id: str) -> bool:
        """Atomically cancel an active timer and discard its deadline.

        This is an internal state operation, not a public command endpoint.
        It cannot cancel an already-due or delivered timer.
        """
        if not isinstance(timer_id, str) or not timer_id.strip():
            raise ValueError("invalid timer id")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM voice_timer_state_ledger WHERE timer_id=?",
                (timer_id,),
            ).fetchone()
            if row is None or row[0] != "active":
                return False
            alarm = db.execute(
                "SELECT status FROM voice_timer_alarm_outbox WHERE timer_id=?",
                (timer_id,),
            ).fetchone()
            if alarm is not None:
                raise ValueError("active timer has unexpected alarm")
            changed = db.execute(
                "UPDATE voice_timer_state_ledger SET state='cancelled', "
                "revision=revision+1 WHERE timer_id=? AND state='active'",
                (timer_id,),
            )
            if changed.rowcount != 1:
                raise RuntimeError("active cancellation state mismatch")
            db.execute("DELETE FROM voice_timer_deadlines WHERE timer_id=?", (timer_id,))
            return True

    def sweep_due(self, *, now: float | None = None, limit: int = 32) -> int:
        """Atomically promote ACTIVE timers to DUE and queue notifications.

        Re-running after a restart is idempotent. Unknown, cancelled or
        delivered timers cannot be made due by this sweep.
        """
        current = time.time() if now is None else float(now)
        if not math.isfinite(current):
            raise ValueError("finite time required")
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("invalid sweep limit")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT d.timer_id FROM voice_timer_deadlines d "
                "JOIN voice_timer_state_ledger l ON l.timer_id=d.timer_id "
                "WHERE l.state='active' AND d.due_at<=? "
                "ORDER BY d.due_at ASC, d.timer_id ASC LIMIT ?",
                (current, limit),
            ).fetchall()
            for (timer_id,) in rows:
                existing = db.execute(
                    "SELECT status FROM voice_timer_alarm_outbox WHERE timer_id=?",
                    (timer_id,),
                ).fetchone()
                if existing is not None:
                    raise ValueError("active timer already has alarm outbox record")
                changed = db.execute(
                    "UPDATE voice_timer_state_ledger SET state='due', "
                    "revision=revision+1 WHERE timer_id=? AND state='active'",
                    (timer_id,),
                )
                if changed.rowcount != 1:
                    raise RuntimeError("due-state promotion mismatch")
                db.execute(
                    "INSERT INTO voice_timer_alarm_outbox "
                    "(timer_id,status) VALUES (?,'queued')", (timer_id,)
                )
                # The durable outbox now owns delivery. Release the deadline
                # in the same transaction so long-running rigs do not retain
                # every completed timer forever.
                db.execute(
                    "DELETE FROM voice_timer_deadlines WHERE timer_id=?",
                    (timer_id,),
                )
            return len(rows)
