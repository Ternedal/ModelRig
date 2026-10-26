"""Task snapshot projection tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from task_store import TaskStore
from task_snapshot import snapshot

class SnapshotTests(unittest.TestCase):
    def test_combined_task_events_and_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            store = TaskStore(path)
            store.create("snapshot-1")
            with sqlite3.connect(path) as db:
                db.execute("""INSERT INTO command_outbox
                    (operation_id,task_id,revision,capability,actor_id,status)
                    VALUES ('op-1','snapshot-1',0,'nas.read','owner','simulated')""")
            result = snapshot(path, "snapshot-1")
            self.assertEqual(result["task_id"], "snapshot-1")
            self.assertEqual(result["revision"], 0)
            self.assertEqual(result["commands"][0]["status"], "simulated")
            self.assertIsInstance(result["events"], list)

    def test_unknown_task_is_not_found(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            TaskStore(path)
            with self.assertRaises(KeyError):
                snapshot(path, "missing")

if __name__ == "__main__":
    unittest.main()
