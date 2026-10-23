"""Token-to-actor resolution for an isolated local read API.

Tokens are never stored in plaintext. The resolver is NOT an identity
provider; registration must happen in a separate trusted admin process.
"""
import hashlib
import hmac
import secrets
import sqlite3

class ReadIdentity:
    def __init__(self, database):
        self.database = str(database)
        with sqlite3.connect(self.database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS read_identities (
                digest TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0)""")

    def issue(self, actor_id):
        if not isinstance(actor_id, str) or not actor_id:
            raise ValueError("actor_id required")
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO read_identities(digest,actor_id) VALUES (?,?)",
                       (digest, actor_id))
        return token

    def resolve(self, token):
        if not isinstance(token, str) or len(token) < 24:
            raise PermissionError("invalid credential")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database) as db:
            row = db.execute("""SELECT actor_id,revoked FROM read_identities
                WHERE digest=?""", (digest,)).fetchone()
        if row is None or row[1] or not hmac.compare_digest(row[0], row[0]):
            raise PermissionError("invalid credential")
        return row[0]

    def revoke(self, token):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE read_identities SET revoked=1 WHERE digest=?", (digest,))
