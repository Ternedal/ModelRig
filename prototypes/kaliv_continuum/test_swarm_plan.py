"""Pure planning tests: no tools or external side effects."""
import unittest
from swarm_plan import Plan, Step, schedule

class SwarmPlanTests(unittest.TestCase):
    def test_dependency_waves(self):
        plan = Plan((Step("observe", "nas.read"), Step("verify", "report.verify", ("observe",)),
                     Step("summarize", "report.write", ("verify",))))
        self.assertEqual(schedule(plan), (("observe",), ("verify",), ("summarize",)))

    def test_parallel_independent_steps(self):
        plan = Plan((Step("a", "read.a"), Step("b", "read.b"),
                     Step("c", "combine", ("a", "b"))))
        self.assertEqual(schedule(plan), (("a", "b"), ("c",)))

    def test_cycle_rejected(self):
        with self.assertRaises(ValueError):
            schedule(Plan((Step("a", "read.a", ("b",)), Step("b", "read.b", ("a",)))))

    def test_budget_rejected(self):
        with self.assertRaises(ValueError):
            schedule(Plan((Step("a", "read.a", estimated_cost=101),)))

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            schedule(Plan((Step("a", "read.a"), Step("a", "read.b"))))

    def test_unknown_dependency_rejected(self):
        with self.assertRaises(ValueError):
            schedule(Plan((Step("a", "read.a", ("missing",)),)))

if __name__ == "__main__":
    unittest.main()
