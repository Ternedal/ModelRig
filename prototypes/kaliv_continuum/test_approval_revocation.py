"""Revoking an approver invalidates unconsumed approvals in same transaction."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from approval_gate import ApprovalGate
from continuum_state import State
from task_access import TaskAccess
from task_store import TaskStore

class ApprovalRevocationTests(unittest.TestCase):
    def test_revoked_approver_cannot_leave_usable_grant(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            store = TaskStore(db)
            task = store.create("demo")
            task = store.move("demo", State.PLANNING, task.revision)
            task = store.move("demo", State.AWAITING_APPROVAL, task.revision)
            gate = ApprovalGate(db)
            acl = TaskAccess(db)
            acl.grant("demo", "alice", "approve")
            token = gate.issue_for_checkpoint(task_id="demo", approver_id="alice",
                executor_id="worker", capability="nas.read",
                expected_revision=task.revision)
            acl.revoke("demo", "alice", "approve")
            with sqlite3.connect(db) as conn:
                self.assertIsNotNone(conn.execute("""SELECT consumed_at
                    FROM continuum_approvals""").fetchone()[0])
            with self.assertRaises(PermissionError):
                store.reserve_execution(task_id="demo", expected_revision=task.revision,
                    actor_id="worker", capability="nas.read", token=token,
                    operation_id="should-not-execute")
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM command_outbox").fetchone()[0], 0)

if __name__ == "__main__":
    unittest.main()
