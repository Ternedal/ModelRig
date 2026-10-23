"""Presentation hints are exhaustive and never grant authorization."""
import unittest
from continuum_state import State
from task_presentation import present

class PresentationTests(unittest.TestCase):
    def test_all_states_supported(self):
        for state in State:
            with self.subTest(state=state):
                result = present(state)
                self.assertIsInstance(result["phase"], str)
                self.assertIsInstance(result["terminal"], bool)

    def test_approval_is_ui_hint_only(self):
        result = present(State.AWAITING_APPROVAL)
        self.assertTrue(result["awaiting_approval"])
        self.assertTrue(result["can_request_approval"])
        self.assertFalse(result["is_running"])

    def test_terminal_and_running(self):
        self.assertTrue(present(State.COMPLETED)["terminal"])
        self.assertTrue(present(State.TERMINAL_FAILED)["terminal"])
        self.assertTrue(present(State.CANCELLED)["terminal"])
        self.assertTrue(present(State.EXECUTING)["is_running"])
        self.assertTrue(present(State.VERIFYING)["is_running"])
        self.assertFalse(present(State.RETRYABLE_FAILED)["terminal"])

if __name__ == "__main__":
    unittest.main()
