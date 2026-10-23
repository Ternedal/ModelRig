"""End-to-end isolated Continuum dry-run pipeline tests; no external actions."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from approval_store import ApprovalStore
from continuum_state import State
from dry_run_worker import DryRunWorker
from swarm_plan import Plan, Step
from swarm_simulator import simulate
from task_store import TaskStore

class PipelineTests(unittest.TestCase):
    def test_approved_plan_to_single_dry_run_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "continuum.sqlite"
            store = TaskStore(db_path)
            grants = ApprovalStore(db_path)
            worker = DryRunWorker(db_path, allowed_capabilities={"nas.read"})
            plan = Plan((Step("inspect", "nas.read"),))
            receipts = simulate(plan, allowed_capabilities={"nas.read"})
            self.assertEqual(receipts[0].status, "planned_only")
            task = store.create("pipeline-1")
            task = store.move(task.task_id, State.PLANNING, task.revision)
            task = store.move(task.task_id, State.AWAITING_APPROVAL, task.revision)
            with self.assertRaises(PermissionError):
                store.reserve_execution(task_id=task.task_id, expected_revision=task.revision,
                    actor_id="owner", capability="nas.read", token="forged", operation_id="op-pipeline-1")
            self.assertEqual(store.get(task.task_id).state, State.AWAITING_APPROVAL)
            token = grants.issue(task_id=task.task_id, actor_id="owner",
                                 capability="nas.read", revision=task.revision)
            task = store.reserve_execution(task_id=task.task_id, expected_revision=task.revision,
                actor_id="owner", capability="nas.read", token=token, operation_id="op-pipeline-1")
            self.assertEqual(task.state, State.EXECUTING)
            receipt = worker.run_once()
            self.assertEqual(receipt.operation_id, "op-pipeline-1")
            self.assertEqual(receipt.status, "simulated")
            self.assertIsNone(worker.run_once())
            self.assertIsNone(DryRunWorker(db_path, allowed_capabilities={"nas.read"}).run_once())
            with sqlite3.connect(db_path) as db:
                self.assertEqual(db.execute("SELECT status FROM command_outbox WHERE operation_id=?",
                    ("op-pipeline-1",)).fetchone()[0], "simulated")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM dry_run_receipts WHERE operation_id=?",
                    ("op-pipeline-1",)).fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT consumed_at IS NOT NULL FROM continuum_approvals").fetchone()[0], 1)
            self.assertEqual(store.events(task.task_id)[-1], (3, "executing"))

    def test_unapproved_plan_never_reaches_outbox(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "continuum.sqlite"
            store = TaskStore(db_path)
            worker = DryRunWorker(db_path)
            plan = Plan((Step("inspect", "nas.read"),
                         Step("erase", "nas.delete", ("inspect",))))
            with self.assertRaises(PermissionError):
                simulate(plan, allowed_capabilities={"nas.read"})
            self.assertIsNone(worker.run_once())
            with sqlite3.connect(db_path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM command_outbox").fetchone()[0], 0)

if __name__ == "__main__":
    unittest.main()
