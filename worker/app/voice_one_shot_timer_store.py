"""Dormant durable one-shot timer proposals; NO alarm or scheduling capability.

Timer proposals are not grants. An authenticated operator flow and a real
notification transport must be integrated before an alarm can become active.
This SQLite store cannot claim or dispatch alarms by design.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredTimerProposal:
    proposal_id: str
    duration_seconds: int
    created_at: float
    expires_at: float
    status: str


MAX_PENDING_PROPOSALS = 32
TERMINAL_RETENTION_SECONDS = 7 * 86400


class OneShotTimerProposalStore:
    """Persistent, restart-safe proposals with no execution interface."""

    def __init__(self, path: str):
        if not path:
            raise ValueError("explicit proposal database path required")
        self._db = sqlite3.connect(path, timeout=5)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS voice_timer_proposals (
                proposal_id TEXT PRIMARY KEY,
                duration_seconds INTEGER NOT NULL
                    CHECK(duration_seconds BETWEEN 1 AND 3600),
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','expired','cancelled'))
            )
        """)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "OneShotTimerProposalStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def propose(self, duration_seconds: int, *, now: float | None = None) -> StoredTimerProposal:
        if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int):
            raise ValueError("duration must be an integer")
        if not 1 <= duration_seconds <= 3600:
            raise ValueError("duration outside permitted range")
        current = time.time() if now is None else float(now)
        # Proposals must be confirmed promptly and must never become an alarm
        # merely because the process restarted.
        proposal = StoredTimerProposal(
            str(uuid.uuid4()), duration_seconds, current, current + 180, "pending"
        )
        with self._db:
            self._db.execute(
                "UPDATE voice_timer_proposals SET status=\'expired\' "
                "WHERE status=\'pending\' AND expires_at<=?", (current,)
            )
            # Completed proposals are retained briefly for diagnostics, not forever.
            self._db.execute(
                "DELETE FROM voice_timer_proposals "
                "WHERE status IN ('expired','cancelled') AND expires_at<=?",
                (current - TERMINAL_RETENTION_SECONDS,),
            )
            pending = self._db.execute(
                "SELECT COUNT(*) FROM voice_timer_proposals WHERE status=\'pending\'"
            ).fetchone()[0]
            if pending >= MAX_PENDING_PROPOSALS:
                raise ValueError("too many outstanding timer proposals")
            self._db.execute(
                "INSERT INTO voice_timer_proposals VALUES (?,?,?,?,?)",
                (proposal.proposal_id, proposal.duration_seconds,
                 proposal.created_at, proposal.expires_at, proposal.status),
            )
        return proposal

    def expire(self, *, now: float | None = None) -> int:
        current = time.time() if now is None else float(now)
        with self._db:
            result = self._db.execute(
                "UPDATE voice_timer_proposals SET status='expired' "
                "WHERE status='pending' AND expires_at<=?", (current,)
            )
        return result.rowcount

    def purge_terminal(self, *, now: float | None = None) -> int:
        """Bound stored terminal history without deleting pending proposals."""
        current = time.time() if now is None else float(now)
        with self._db:
            result = self._db.execute(
                "DELETE FROM voice_timer_proposals "
                "WHERE status IN ('expired','cancelled') AND expires_at<=?",
                (current - TERMINAL_RETENTION_SECONDS,),
            )
        return result.rowcount

    def cancel(self, proposal_id: str) -> bool:
        with self._db:
            result = self._db.execute(
                "UPDATE voice_timer_proposals SET status='cancelled' "
                "WHERE proposal_id=? AND status='pending'", (proposal_id,)
            )
        return result.rowcount == 1

    def get(self, proposal_id: str, *, now: float | None = None) -> StoredTimerProposal | None:
        self.expire(now=now)
        row = self._db.execute(
            "SELECT proposal_id,duration_seconds,created_at,expires_at,status "
            "FROM voice_timer_proposals WHERE proposal_id=?", (proposal_id,)
        ).fetchone()
        return StoredTimerProposal(*row) if row else None
