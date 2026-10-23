"""Expiry, migration and rotation regression tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from read_identity import ReadIdentity

class TokenLifecycleTests(unittest.TestCase):
    def test_expiry_and_atomic_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = ReadIdentity(Path(folder) / "tokens.sqlite")
            with patch("read_identity.time.time", return_value=1000):
                old = registry.issue("alice", ttl_seconds=10)
                new = registry.rotate(old, ttl_seconds=20)
                self.assertEqual(registry.resolve(new), "alice")
                with self.assertRaises(PermissionError):
                    registry.resolve(old)
                with self.assertRaises(PermissionError):
                    registry.rotate(old)
            with patch("read_identity.time.time", return_value=1020):
                with self.assertRaises(PermissionError):
                    registry.resolve(new)

    def test_legacy_rows_fail_closed_and_migrate(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "legacy.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("""CREATE TABLE read_identities (
                    digest TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0)""")
                conn.execute("INSERT INTO read_identities VALUES ('legacy','alice',0)")
            registry = ReadIdentity(db)
            with sqlite3.connect(db) as conn:
                self.assertIn("expires_at", [r[1] for r in conn.execute("PRAGMA table_info(read_identities)")])
                self.assertIsNone(conn.execute("SELECT expires_at FROM read_identities").fetchone()[0])
            with self.assertRaises(PermissionError):
                registry.resolve("legacy")

    def test_ttl_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = ReadIdentity(Path(folder) / "tokens.sqlite")
            for value in (0, -1, 86401, True, 1.5):
                with self.assertRaises(ValueError):
                    registry.issue("alice", ttl_seconds=value)

if __name__ == "__main__":
    unittest.main()
