"""Atomic proposal + state-ledger registration, without timer activation.

The two existing SQLite stores must use the SAME database file for this bridge.
A proposal is inert; success here only means a pending record was stored.
"""
from __future__ import annotations

import sqlite3
import time
import uuid

from .voice_one_shot_timer_store import (
    MAX_PENDING_PROPOSALS, TERMINAL_RETENTION_SECONDS, StoredTimerProposal,
    OneShotTimerProposalStore,
)
from .voice_timer_state_ledger import TimerStateLedger


class TimerProposalLedgerBridge:
    def __init__(self, db_path: str):
        if not isinstance(db_path, str) or not db_path.strip():
            raise ValueError("explicit shared timer database path required")
        self._path = db_path

    def create_pending(self, duration_seconds: int, *, now: float | None = None) -> StoredTimerProposal:
        if type(duration_seconds) is not int or not 1 <= duration_seconds <= 3600:
            raise ValueError("duration must be between 1 and 3600 seconds")
        current = time.time() if now is None else float(now)
        proposal_id = str(uuid.uuid4())
        # Initialise both schemas, without creating any timer executor.
        with OneShotTimerProposalStore(self._path):
            pass
        with TimerStateLedger(self._path):
            pass
        conn = sqlite3.connect(self._path, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE voice_timer_proposals SET status='expired' "
                "WHERE status='pending' AND expires_at<=?", (current,)
            )
            conn.execute(
                "DELETE FROM voice_timer_proposals WHERE status IN ('expired','cancelled') "
                "AND expires_at<=?", (current-TERMINAL_RETENTION_SECONDS,)
            )
            pending = conn.execute(
                "SELECT COUNT(*) FROM voice_timer_proposals WHERE status='pending'"
            ).fetchone()[0]
            if pending >= MAX_PENDING_PROPOSALS:
                raise ValueError("too many outstanding timer proposals")
            conn.execute(
                "INSERT INTO voice_timer_proposals VALUES (?,?,?,?,?)",
                (proposal_id, duration_seconds, current, current+180, "pending"),
            )
            conn.execute(
                "INSERT INTO voice_timer_state_ledger(timer_id,state,revision) "
                "VALUES (?,'pending',0)", (proposal_id,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return StoredTimerProposal(proposal_id, duration_seconds, current, current+180, "pending")
