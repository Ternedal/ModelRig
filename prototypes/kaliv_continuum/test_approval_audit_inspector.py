"""Redacted approval audit inspector regression."""
import tempfile
import unittest
from pathlib import Path

from approval_audit_inspector import ApprovalAuditInspector
from approval_gate import ApprovalGate
from continuum_state import State
from task_access import TaskAccess
from task_store import TaskStore

class AuditInspectorTests(unittest.TestCase):
    def test_inspector_exposes_metadata_not_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "tasks.sqlite"
            store = TaskStore(db)
            task = store.create("task")
            task = store.move("task", State.PLANNING, task.revision)
            task = store.move("task", State.AWAITING_APPROVAL, task.revision)
            gate = ApprovalGate(db)
            TaskAccess(db).grant("task", "approver", "approve")
            token = gate.issue_for_checkpoint(task_id="task", approver_id="approver",
                executor_id="worker", capability="nas.read", expected_revision=task.revision)
            inspector = ApprovalAuditInspector(db)
            rows = inspector.list_for_task("task")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["approver_id"], "approver")
            self.assertEqual(rows[0]["executor_id"], "worker")
            self.assertEqual(rows[0]["capability"], "nas.read")
            self.assertNotIn("digest", rows[0])
            self.assertNotIn("token", rows[0])
            self.assertNotIn(token, str(rows))
            self.assertEqual(inspector.list_for_task("other"), [])
            store.reserve_execution(task_id="task", expected_revision=task.revision,
                actor_id="worker", capability="nas.read", token=token, operation_id="op-1")
            self.assertIsNotNone(inspector.list_for_task("task")[0]["consumed_at"])

if __name__ == "__main__":
    unittest.main()
