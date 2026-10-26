"""Isolated Continuum transition tests."""
import unittest
from continuum_state import Task, State, transition

class ContinuumTests(unittest.TestCase):
    def test_requires_verified_approval(self):
        t = transition(Task("one"), State.PLANNING, expected_revision=0)
        t = transition(t, State.AWAITING_APPROVAL, expected_revision=1)
        with self.assertRaises(PermissionError):
            transition(t, State.EXECUTING, expected_revision=2)
        with self.assertRaises(TypeError):
            transition(t, State.EXECUTING, expected_revision=2, approval_token="anything")
        t = transition(t, State.EXECUTING, expected_revision=2, verified_approval=True)
        self.assertEqual(t.revision, 3)

    def test_rejects_stale_revision(self):
        with self.assertRaises(ValueError):
            transition(Task("two"), State.PLANNING, expected_revision=9)

    def test_terminal(self):
        t = transition(Task("three"), State.CANCELLED, expected_revision=0)
        with self.assertRaises(ValueError):
            transition(t, State.PLANNING, expected_revision=1)

if __name__ == "__main__":
    unittest.main()
