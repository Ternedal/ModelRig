"""Transactional local approval gate (not an authenticated policy authority).

The ACL, task checkpoint and grant insertion are checked within a single
SQLite write transaction to prevent time-of-check/time-of-use races.
"""
import hashlib
import secrets
import sqlite3
import time

from continuum_state import State
from task_access import TaskAccess
from task_store import TaskStore
from approval_store import ApprovalStore

class ApprovalGate:
    def __init__(self, database):
        self.database = str(database)
        self.store = TaskStore(database)
        self.access = TaskAccess(database)
        self.approvals = ApprovalStore(database)
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS approval_issue_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL, approver_id TEXT NOT NULL,
                executor_id TEXT NOT NULL, capability TEXT NOT NULL,
                revision INTEGER NOT NULL, grant_digest TEXT NOT NULL UNIQUE,
                issued_at INTEGER NOT NULL)""")

    def issue_for_checkpoint(self, *, task_id, approver_id, executor_id,
                             capability, expected_revision, ttl_seconds=300):
        """Issue an executor-scoped grant only at a matching authorized checkpoint.

        Caller identity is not authenticated here. Never expose this method
        directly as a remote API or connect it to real capabilities.
        """
        if not all(isinstance(x, str) and x.strip()
                   for x in (task_id, approver_id, executor_id, capability)):
            raise ValueError("missing approval scope")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("invalid revision")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError("invalid TTL")
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        with sqlite3.connect(self.database, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            acl = db.execute("""SELECT 1 FROM task_acl
                WHERE task_id=? AND actor_id=? AND permission='approve'""",
                (task_id, approver_id)).fetchone()
            if acl is None:
                raise PermissionError("approval access denied")
            task = db.execute("SELECT state,revision FROM tasks WHERE task_id=?",
                              (task_id,)).fetchone()
            if (task is None or task[0] != State.AWAITING_APPROVAL.value or
                    task[1] != expected_revision):
                raise PermissionError("checkpoint mismatch")
            issued_at = int(time.time())
            db.execute("""INSERT INTO continuum_approvals
                (digest,task_id,actor_id,capability,revision,expires_at,consumed_at)
                VALUES (?,?,?,?,?,?,NULL)""",
                (digest, task_id, executor_id, capability, expected_revision,
                 issued_at + ttl_seconds))
            db.execute("""INSERT INTO approval_issue_audit
                (task_id,approver_id,executor_id,capability,revision,grant_digest,issued_at)
                VALUES (?,?,?,?,?,?,?)""",
                (task_id, approver_id, executor_id, capability,
                 expected_revision, digest, issued_at))
        return token
