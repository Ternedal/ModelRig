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
            mismatch = conn.execute(
                "SELECT COUNT(*) FROM voice_timer_proposals p "
                "LEFT JOIN voice_timer_state_ledger l ON l.timer_id=p.proposal_id "
                "WHERE (p.status='pending' AND "
                "(l.timer_id IS NULL OR l.state!='pending')) "
                "OR (p.status IN ('expired','cancelled') AND "
                "l.timer_id IS NOT NULL AND l.state!=p.status)"
            
            ).fetchone()[0]
            orphan = conn.execute(
                "SELECT COUNT(*) FROM voice_timer_state_ledger l "
                "LEFT JOIN voice_timer_proposals p ON p.proposal_id=l.timer_id "
                "WHERE l.state='pending' AND p.proposal_id IS NULL"
            ).fetchone()[0]
            if mismatch or orphan:
                raise ValueError("proposal/ledger state mismatch")
            due = conn.execute(
                "UPDATE voice_timer_state_ledger SET state='expired', "
                "revision=revision+1 WHERE state='pending' AND timer_id IN "
                "(SELECT proposal_id FROM voice_timer_proposals "
                "WHERE status='pending' AND expires_at<=?)", (current,)
            ).rowcount
            expired = conn.execute(
                "UPDATE voice_timer_proposals SET status='expired' "
                "WHERE status='pending' AND expires_at<=?", (current,)
            ).rowcount
            if due != expired:
                raise ValueError("proposal/ledger expiry count mismatch")
            conn.execute(
                "DELETE FROM voice_timer_proposals WHERE status IN ('expired','cancelled') "
                "AND expires_at<=?", (current-TERMINAL_RETENTION_SECONDS,)
            )
            conn.execute(
                "DELETE FROM voice_timer_state_ledger WHERE "
                "state IN ('expired','cancelled') AND timer_id NOT IN "
                "(SELECT proposal_id FROM voice_timer_proposals)"
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

    def expire_pending(self, *, now: float | None = None) -> int:
        """Expire both pending tables together, or roll back on mismatch.

        Unlike the legacy proposal-only expiry method, this is the canonical
        bridge operation for paired records. It never starts an alarm.
        """
        current = time.time() if now is None else float(now)
        conn = sqlite3.connect(self._path, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            inconsistent = conn.execute(
                "SELECT COUNT(*) FROM voice_timer_proposals p "
                "LEFT JOIN voice_timer_state_ledger l ON l.timer_id=p.proposal_id "
                "WHERE (p.status='pending' AND "
                "(l.timer_id IS NULL OR l.state!='pending')) "
                "OR (p.status IN ('expired','cancelled') AND "
                "l.timer_id IS NOT NULL AND l.state!=p.status)"
            
            ).fetchone()[0]
            orphan = conn.execute(
                "SELECT COUNT(*) FROM voice_timer_state_ledger l "
                "LEFT JOIN voice_timer_proposals p ON p.proposal_id=l.timer_id "
                "WHERE l.state='pending' AND p.proposal_id IS NULL"
            ).fetchone()[0]
            if inconsistent or orphan:
                raise ValueError("proposal/ledger state mismatch")
            updated = conn.execute(
                "UPDATE voice_timer_state_ledger SET state='expired',revision=revision+1 "
                "WHERE state='pending' AND timer_id IN "
                "(SELECT proposal_id FROM voice_timer_proposals "
                "WHERE status='pending' AND expires_at<=?)", (current,)
            )
            result = conn.execute(
                "UPDATE voice_timer_proposals SET status='expired' "
                "WHERE status='pending' AND expires_at<=?", (current,)
            )
            if updated.rowcount != result.rowcount:
                raise ValueError("proposal/ledger expiry count mismatch")
            conn.commit()
            return result.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def cancel_pending(self, proposal_id: str, *, now: float | None = None) -> bool:
        """Atomically cancel both records, or expire both at the deadline.

        Returns true only when a still-valid pending proposal and its ledger
        were cancelled together. A mismatched ledger is an error, not success.
        """
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise ValueError("proposal id must be nonempty text")
        current = time.time() if now is None else float(now)
        conn = sqlite3.connect(self._path, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status,expires_at FROM voice_timer_proposals WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return False
            ledger = conn.execute(
                "SELECT state FROM voice_timer_state_ledger WHERE timer_id=?",
                (proposal_id,),
            ).fetchone()
            if ledger is None or ledger[0] != row[0]:
                raise ValueError("proposal/ledger state mismatch")
            if row[0] != "pending":
                conn.rollback()
                return False
            target = "expired" if row[1] <= current else "cancelled"
            conn.execute(
                "UPDATE voice_timer_proposals SET status=? WHERE proposal_id=? "
                "AND status='pending'", (target, proposal_id),
            )
            updated = conn.execute(
                "UPDATE voice_timer_state_ledger SET state=?,revision=revision+1 "
                "WHERE timer_id=? AND state='pending'", (target, proposal_id),
            )
            if updated.rowcount != 1:
                raise ValueError("concurrent or inconsistent ledger update")
            conn.commit()
            return target == "cancelled"
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def inspect_pending(self, proposal_id: str, *, now: float | None = None) -> dict | None:
        """Read consistent timer status without modifying either table.

        A pending timer is actionable only before its proposal deadline.
        Missing or mismatched ledger data is a corruption error, never a
        successful or active timer. This does not authorize activation.
        """
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise ValueError("proposal id must be nonempty text")
        current = time.time() if now is None else float(now)
        conn = sqlite3.connect(self._path, timeout=5)
        try:
            row = conn.execute(
                "SELECT p.proposal_id,p.duration_seconds,p.status,p.expires_at,"
                "l.state,l.revision FROM voice_timer_proposals p "
                "LEFT JOIN voice_timer_state_ledger l ON l.timer_id=p.proposal_id "
                "WHERE p.proposal_id=?", (proposal_id,)
            ).fetchone()
            if row is None:
                return None
            identifier, duration, status, expiry, ledger_state, revision = row
            if ledger_state is None or ledger_state != status:
                raise ValueError("proposal/ledger state mismatch")
            return {
                "proposal_id": identifier,
                "duration_seconds": duration,
                "status": status,
                "revision": revision,
                "can_request_confirmation": status == "pending" and current < expiry,
                "timer_started": False,
            }
        finally:
            conn.close()
