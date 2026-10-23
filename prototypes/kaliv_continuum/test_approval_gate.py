"""Local approval gate tests; no external capability execution."""
import tempfile
import unittest
from pathlib import Path

from approval_gate import ApprovalGate
from continuum_state import State
from task_access import TaskAccess
from task_store import TaskStore

class ApprovalGateTests(unittest.TestCase):
    def test_approver_must_have_approve_acl_and_matching_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            store = TaskStore(db)
            task = store.create("demo")
            gate = ApprovalGate(db)
            acl = TaskAccess(db)
            task = store.move("demo", State.PLANNING, task.revision)
            task = store.move("demo", State.AWAITING_APPROVAL, task.revision)
            acl.grant("demo", "reader", "read")
            for actor in ("reader", "unknown"):
                with self.assertRaises(PermissionError):
                    gate.issue_for_checkpoint(task_id="demo", approver_id=actor,
                        executor_id="worker", capability="nas.read",
                        expected_revision=task.revision)
            acl.grant("demo", "approver", "approve")
            with self.assertRaises(PermissionError):
                gate.issue_for_checkpoint(task_id="demo", approver_id="approver",
                    executor_id="worker", capability="nas.read",
                    expected_revision=task.revision - 1)
            token = gate.issue_for_checkpoint(task_id="demo", approver_id="approver",
                executor_id="worker", capability="nas.read",
                expected_revision=task.revision)
            self.assertTrue(isinstance(token, str) and len(token) >= 24)
            updated = store.reserve_execution(task_id="demo", expected_revision=task.revision,
                actor_id="worker", capability="nas.read", token=token, operation_id="op-demo")
            self.assertEqual(updated.state, State.EXECUTING)
            with self.assertRaises(PermissionError):
                gate.issue_for_checkpoint(task_id="demo", approver_id="approver",
                    executor_id="worker", capability="nas.read",
                    expected_revision=task.revision)

if __name__ == "__main__":
    unittest.main()
