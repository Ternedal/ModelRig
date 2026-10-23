"""Dry-run outbox worker tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from task_store import TaskStore
from dry_run_worker import DryRunWorker

class WorkerTests(unittest.TestCase):
    def test_exactly_one_dry_run_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            TaskStore(path)
            with sqlite3.connect(path) as db:
                db.execute("""INSERT INTO command_outbox
                    (operation_id,task_id,revision,capability,actor_id)
                    VALUES ('op-1','task-1',3,'nas.read','owner')""")
            worker = DryRunWorker(path, allowed_capabilities={"nas.read"})
            receipt = worker.run_once()
            self.assertEqual(receipt.status, "simulated")
            self.assertIsNone(worker.run_once())
            self.assertIsNone(DryRunWorker(path).run_once())
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM dry_run_receipts").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT status FROM command_outbox").fetchone()[0], "simulated")

    def test_default_denies_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            TaskStore(path)
            with sqlite3.connect(path) as db:
                db.execute("""INSERT INTO command_outbox
                    (operation_id,task_id,revision,capability,actor_id)
                    VALUES ('op-2','task-2',3,'nas.delete','owner')""")
            with self.assertRaises(PermissionError):
                DryRunWorker(path).run_once()
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT status FROM command_outbox").fetchone()[0], "reserved")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM dry_run_receipts").fetchone()[0], 0)

    def test_no_commands_is_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            TaskStore(path)
            self.assertIsNone(DryRunWorker(path).run_once())

if __name__ == "__main__":
    unittest.main()
