"""Prototype scoped approval grants. Not integrated with task transitions yet.

Tokens are opaque one-use random secrets. Store only SHA-256 digests. A grant is
bound to task, actor, capability, task revision and expiry; consume atomically.
This is a local prototype, not a replacement for ModelRig's capability policy.
"""
import hashlib
import secrets
import sqlite3
import time

class ApprovalStore:
    def __init__(self, database):
        self.database = str(database)
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS continuum_approvals (
                digest TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                revision INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            )""")

    def issue(self, *, task_id, actor_id, capability, revision, ttl_seconds=300):
        if not all(isinstance(x, str) and x.strip() for x in (task_id, actor_id, capability)):
            raise ValueError("task, actor and capability required")
        if type(revision) is not int or revision < 0:
            raise ValueError("invalid revision")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError("invalid TTL")
        secret = secrets.token_urlsafe(32)
        digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO continuum_approvals VALUES (?,?,?,?,?,?,NULL)",
                       (digest, task_id, actor_id, capability, revision,
                        int(time.time()) + ttl_seconds))
        return secret

    def consume(self, token, *, task_id, actor_id, capability, revision):
        if not isinstance(token, str) or not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = int(time.time())
        with sqlite3.connect(self.database, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""UPDATE continuum_approvals
                SET consumed_at=?
                WHERE digest=? AND task_id=? AND actor_id=? AND capability=?
                  AND revision=? AND expires_at>? AND consumed_at IS NULL""",
                (now, digest, task_id, actor_id, capability, revision, now))
            return cursor.rowcount == 1
