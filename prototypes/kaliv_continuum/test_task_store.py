"""Persistence and atomic approval reservation tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from task_store import TaskStore
from approval_store import ApprovalStore
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
            self.assertEqual(reopened.events("task-1"), [(0, "queued"), (1, "planning")])

    def test_atomic_approval_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.sqlite"
            store = TaskStore(path)
            store.create("task-2")
            store.move("task-2", State.PLANNING, 0)
            store.move("task-2", State.AWAITING_APPROVAL, 1)
            with self.assertRaises(PermissionError):
                store.move("task-2", State.EXECUTING, 2, approval_token="fake")
            grants = ApprovalStore(path)
            token = grants.issue(task_id="task-2", actor_id="owner",
                                 capability="nas.read", revision=2)
            with self.assertRaises(PermissionError):
                store.reserve_execution(task_id="task-2", expected_revision=2,
                    actor_id="other", capability="nas.read", token=token, operation_id="op-1")
            self.assertEqual(store.get("task-2").revision, 2)
            store.reserve_execution(task_id="task-2", expected_revision=2,
                actor_id="owner", capability="nas.read", token=token, operation_id="op-1")
            self.assertEqual(store.get("task-2").state, State.EXECUTING)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM command_outbox").fetchone()[0], 1)
            with self.assertRaises(PermissionError):
                store.reserve_execution(task_id="task-2", expected_revision=2,
                    actor_id="owner", capability="nas.read", token=token, operation_id="op-2")

if __name__ == "__main__":
    unittest.main()
