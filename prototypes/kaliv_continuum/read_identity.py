"""Revocable, expiring actor tokens for isolated read-only HTTP API.

Tokens are stored only as SHA-256 digests. Issuance/rotation must be called
by a trusted local administrator; this is not an identity provider.
"""
import hashlib
import secrets
import sqlite3
import time

class ReadIdentity:
    def __init__(self, database):
        self.database = str(database)
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS read_identities (
                digest TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER)""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(read_identities)")}
            if "expires_at" not in columns:
                db.execute("ALTER TABLE read_identities ADD COLUMN expires_at INTEGER")

    def issue(self, actor_id, *, ttl_seconds=3600):
        if not isinstance(actor_id, str) or not actor_id:
            raise ValueError("actor_id required")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 86400:
            raise ValueError("ttl_seconds must be 1..86400")
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database) as db:
            db.execute("""INSERT INTO read_identities(digest,actor_id,expires_at)
                VALUES (?,?,?)""", (digest, actor_id, int(time.time()) + ttl_seconds))
        return token

    def resolve(self, token):
        if not isinstance(token, str) or len(token) < 24:
            raise PermissionError("invalid credential")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database) as db:
            row = db.execute("""SELECT actor_id,revoked,expires_at FROM read_identities
                WHERE digest=?""", (digest,)).fetchone()
        if row is None or row[1] or row[2] is None or row[2] <= int(time.time()):
            raise PermissionError("invalid credential")
        return row[0]

    def revoke(self, token):
        if not isinstance(token, str):
            raise ValueError("token required")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE read_identities SET revoked=1 WHERE digest=?", (digest,))

    def rotate(self, token, *, ttl_seconds=3600):
        """Atomically revoke an active token and issue a new one for its actor."""
        if not isinstance(token, str) or len(token) < 24:
            raise PermissionError("invalid credential")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 86400:
            raise ValueError("ttl_seconds must be 1..86400")
        old_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        new_token = secrets.token_urlsafe(32)
        new_digest = hashlib.sha256(new_token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database) as db:
            row = db.execute("""SELECT actor_id FROM read_identities WHERE digest=?
                AND revoked=0 AND expires_at>?""", (old_digest, int(time.time()))).fetchone()
            if row is None:
                raise PermissionError("invalid credential")
            db.execute("UPDATE read_identities SET revoked=1 WHERE digest=?", (old_digest,))
            db.execute("""INSERT INTO read_identities(digest,actor_id,expires_at)
                VALUES (?,?,?)""", (new_digest, row[0], int(time.time()) + ttl_seconds))
        return new_token
