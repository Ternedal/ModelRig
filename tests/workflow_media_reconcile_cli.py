"""Contract tests for the read-only media reconciliation command."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("media_reconcile_cli", ROOT / "scripts" / "media_reconcile.py")
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


class MediaReconcileCliTests(unittest.TestCase):
    def test_read_only_store_cannot_write_or_create_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "jobs.sqlite"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE image_jobs (id TEXT)")
                db.execute("INSERT INTO image_jobs VALUES ('original')")
            before = db_path.read_bytes()
            store = cli.ReadOnlyImageJobStore(db_path)
            with store._db() as db:
                self.assertEqual(db.execute("SELECT id FROM image_jobs").fetchone()[0],
                                 "original")
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("INSERT INTO image_jobs VALUES ('new')")
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("CREATE TABLE diagnostic_mutation (id TEXT)")
            self.assertEqual(db_path.read_bytes(), before)

    def test_missing_database_is_rejected_without_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.sqlite"
            with patch("sys.stderr"):
                with self.assertRaises(SystemExit) as error:
                    cli.main(["--jobs-db", str(db_path),
                              "--volume-root", tmp, "--media-root", tmp])
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
