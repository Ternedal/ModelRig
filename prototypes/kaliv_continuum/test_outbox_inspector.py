"""Read-only outbox status inspection tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from task_store import TaskStore
from outbox_inspector import OutboxInspector

class OutboxInspectorTests(unittest.TestCase):
    def test_read_status_and_task_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            TaskStore(path)
            with sqlite3.connect(path) as db:
                db.execute("""INSERT INTO command_outbox
                    (operation_id,task_id,revision,capability,actor_id,status)
                    VALUES ('op-1','task-1',3,'nas.read','owner','simulated')""")
            inspector = OutboxInspector(path)
            self.assertEqual(inspector.get("op-1").status, "simulated")
            self.assertEqual(len(inspector.list_for_task("task-1")), 1)
            self.assertEqual(inspector.list_for_task("other"), ())
            with self.assertRaises(KeyError):
                inspector.get("missing")

if __name__ == "__main__":
    unittest.main()
