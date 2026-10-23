"""Persistence smoke tests; run with python -m unittest discover."""
import tempfile
import unittest
from pathlib import Path
from task_store import TaskStore
from continuum_state import State

class StoreTests(unittest.TestCase):
    def test_restart_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            store = TaskStore(path)
            store.create("task-1")
            store.move("task-1", State.PLANNING, 0)
            reopened = TaskStore(path)
            self.assertEqual(reopened.get("task-1").revision, 1)
            self.assertEqual(reopened.events("task-1"),
                             [(0, "queued"), (1, "planning")])

    def test_approval_gate_and_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TaskStore(Path(folder) / "tasks.sqlite")
            store.create("task-2")
            store.move("task-2", State.PLANNING, 0)
            store.move("task-2", State.AWAITING_APPROVAL, 1)
            with self.assertRaises(PermissionError):
                store.move("task-2", State.EXECUTING, 2)
            self.assertEqual(store.get("task-2").revision, 2)
            store.move("task-2", State.EXECUTING, 2, approval_token="ok")
            with self.assertRaises(ValueError):
                store.move("task-2", State.VERIFYING, 2)

if __name__ == "__main__":
    unittest.main()
