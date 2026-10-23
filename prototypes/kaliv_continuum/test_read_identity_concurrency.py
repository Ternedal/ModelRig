"""Concurrent rotation must consume the old credential only once."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import tempfile
import unittest
from pathlib import Path

from read_identity import ReadIdentity

class ConcurrentRotationTests(unittest.TestCase):
    def test_only_one_rotation_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tokens.sqlite"
            identity = ReadIdentity(db)
            old = identity.issue("alice")
            def rotate(_):
                try:
                    return identity.rotate(old)
                except PermissionError:
                    return None
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(rotate, range(16)))
            winners = [token for token in results if token is not None]
            self.assertEqual(len(winners), 1)
            self.assertEqual(identity.resolve(winners[0]), "alice")
            with self.assertRaises(PermissionError):
                identity.resolve(old)
            with sqlite3.connect(db) as conn:
                active = conn.execute("""SELECT count(*) FROM read_identities
                    WHERE revoked=0""").fetchone()[0]
            self.assertEqual(active, 1)

if __name__ == "__main__":
    unittest.main()
