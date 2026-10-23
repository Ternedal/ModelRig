"""Fail-closed simulation tests."""
import unittest
from swarm_plan import Plan, Step
from swarm_simulator import simulate

class SwarmSimulatorTests(unittest.TestCase):
    def test_receipts_are_planned_only(self):
        plan = Plan((Step("disk", "nas.read"), Step("report", "report.preview", ("disk",))))
        receipts = simulate(plan, allowed_capabilities={"nas.read", "report.preview"})
        self.assertEqual([r.wave for r in receipts], [0, 1])
        self.assertTrue(all(r.status == "planned_only" for r in receipts))

    def test_unauthorized_capability_rejected_before_any_receipt(self):
        plan = Plan((Step("read", "nas.read"), Step("delete", "nas.delete", ("read",))))
        with self.assertRaises(PermissionError):
            simulate(plan, allowed_capabilities={"nas.read"})

    def test_empty_allowlist_denies(self):
        with self.assertRaises(PermissionError):
            simulate(Plan((Step("a", "nas.read"),)), allowed_capabilities=set())

if __name__ == "__main__":
    unittest.main()
