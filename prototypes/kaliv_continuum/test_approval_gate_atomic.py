"""Atomic approval issuance regression tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from approval_gate import ApprovalGate
from continuum_state import State
from task_access import TaskAccess
from task_store import TaskStore

class AtomicApprovalTests(unittest.TestCase):
    def test_failed_issuance_leaves_no_grant(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            store = TaskStore(db)
            task = store.create("task")
            task = store.move("task", State.PLANNING, task.revision)
            task = store.move("task", State.AWAITING_APPROVAL, task.revision)
            gate = ApprovalGate(db)
            acl = TaskAccess(db)
            acl.grant("task", "approver", "approve")
            acl.revoke("task", "approver", "approve")
            with self.assertRaises(PermissionError):
                gate.issue_for_checkpoint(task_id="task", approver_id="approver",
                    executor_id="worker", capability="nas.read", expected_revision=task.revision)
            acl.grant("task", "approver", "approve")
            with self.assertRaises(PermissionError):
                gate.issue_for_checkpoint(task_id="task", approver_id="approver",
                    executor_id="worker", capability="nas.read", expected_revision=task.revision + 1)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM continuum_approvals").fetchone()[0], 0)
            token = gate.issue_for_checkpoint(task_id="task", approver_id="approver",
                executor_id="worker", capability="nas.read", expected_revision=task.revision)
            self.assertTrue(token)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM continuum_approvals").fetchone()[0], 1)

if __name__ == "__main__":
    unittest.main()
