"""Approval issuance audit is atomic and does not store secret tokens."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from approval_gate import ApprovalGate
from continuum_state import State
from task_access import TaskAccess
from task_store import TaskStore

class ApprovalAuditTests(unittest.TestCase):
    def test_audit_tracks_success_only_and_uses_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            store = TaskStore(db)
            task = store.create("demo")
            task = store.move("demo", State.PLANNING, task.revision)
            task = store.move("demo", State.AWAITING_APPROVAL, task.revision)
            gate = ApprovalGate(db)
            acl = TaskAccess(db)
            with self.assertRaises(PermissionError):
                gate.issue_for_checkpoint(task_id="demo", approver_id="alice",
                    executor_id="worker", capability="nas.read",
                    expected_revision=task.revision)
            acl.grant("demo", "alice", "approve")
            token = gate.issue_for_checkpoint(task_id="demo", approver_id="alice",
                executor_id="worker", capability="nas.read",
                expected_revision=task.revision)
            with sqlite3.connect(db) as conn:
                audit = conn.execute("""SELECT approver_id,executor_id,capability,
                    revision,grant_digest FROM approval_issue_audit""").fetchall()
                grants = conn.execute("SELECT digest FROM continuum_approvals").fetchall()
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0][:4], ("alice", "worker", "nas.read", task.revision))
            self.assertEqual(audit[0][4], hashlib.sha256(token.encode("ascii")).hexdigest())
            self.assertEqual(grants, [(audit[0][4],)])
            self.assertNotIn(token, str(audit))

if __name__ == "__main__":
    unittest.main()
