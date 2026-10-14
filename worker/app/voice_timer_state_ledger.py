"""Dormant durable one-shot timer execution state ledger.

A transition requires an existing row and expected revision. This ledger has
NO permission to activate timers: the authenticated operator boundary must
provide a trusted grant and a registered delivery transport in a future layer.
No alarms are dispatched from this module.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

STATES = ("pending", "active", "due", "delivered", "cancelled", "expired")
TRANSITIONS = {
    "pending": frozenset(("cancelled", "expired")),
    "active": frozenset(("due", "cancelled")),
    "due": frozenset(("delivered", "cancelled")),
    "delivered": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}


@dataclass(frozen=True)
class TimerRecord:
    timer_id: str
    state: str
    revision: int


class TimerStateLedger:
    """Transactional compare-and-swap transitions, not a timer executor."""

    def __init__(self, path: str):
        if not path:
            raise ValueError("database path required")
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS voice_timer_state_ledger (
                timer_id TEXT PRIMARY KEY,
                state TEXT NOT NULL CHECK(state IN (
                    'pending','active','due','delivered','cancelled','expired'
                )),
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0)
            )
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "TimerStateLedger":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def register_pending(self, timer_id: str) -> TimerRecord:
        if not timer_id or not timer_id.strip():
            raise ValueError("timer id is required")
        with self.db:
            self.db.execute(
                "INSERT INTO voice_timer_state_ledger(timer_id,state,revision) "
                "VALUES (?,'pending',0)", (timer_id,)
            )
        return TimerRecord(timer_id, "pending", 0)

    def get(self, timer_id: str) -> TimerRecord | None:
        row = self.db.execute(
            "SELECT timer_id,state,revision FROM voice_timer_state_ledger "
            "WHERE timer_id=?", (timer_id,)
        ).fetchone()
        return TimerRecord(*row) if row else None

    def transition(self, timer_id: str, *, expected_revision: int, target: str) -> TimerRecord:
        if target not in STATES or target == "active":
            # Activating needs a trusted operator execution path, not this ledger.
            raise ValueError("active timer activation is not available")
        with self.db:
            current = self.get(timer_id)
            if current is None or current.revision != expected_revision:
                raise ValueError("unknown timer or stale revision")
            if target not in TRANSITIONS[current.state]:
                raise ValueError("invalid or terminal timer transition")
            updated = self.db.execute(
                "UPDATE voice_timer_state_ledger SET state=?, revision=revision+1 "
                "WHERE timer_id=? AND revision=? AND state=?",
                (target, timer_id, expected_revision, current.state),
            )
            if updated.rowcount != 1:
                raise ValueError("concurrent timer transition")
        return TimerRecord(timer_id, target, expected_revision+1)
