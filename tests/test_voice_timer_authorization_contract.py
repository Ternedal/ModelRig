"""Timer authorization receipts must fail closed without touching a scheduler."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_contract import (
    TimerExecutionReceipt,
    TimerProposal,
    authorized_timer_acknowledgement,
    propose_timer,
)


class TimerAuthorizationContractTest(unittest.TestCase):
    def test_proposal_is_pure_and_bounded(self):
        proposal = propose_timer("Sæt en timer på 5 minutter.")
        self.assertEqual(proposal.duration_seconds, 300)
        self.assertIsNone(propose_timer("Sæt en timer på 90 minutter."))
        self.assertIsNone(propose_timer("Fortæl mig om timere."))
        with self.assertRaises(ValueError):
            TimerProposal(3601, "en timer")
        with self.assertRaises(ValueError):
            TimerProposal(1, "")

    def test_no_false_success_on_missing_authorization_or_delivery(self):
        valid = TimerExecutionReceipt(
            authorized=True, persisted=True, delivery_confirmed=True, timer_id="t-1"
        )
        self.assertIn("ikke startet", authorized_timer_acknowledgement(valid))
        for receipt in (
            None,
            TimerExecutionReceipt(False, True, True, "t-1"),
            TimerExecutionReceipt(True, False, True, "t-1"),
            TimerExecutionReceipt(True, True, False, "t-1"),
            TimerExecutionReceipt(True, True, True, None),
            TimerExecutionReceipt(True, True, True, "  "),
        ):
            with self.subTest(receipt=receipt):
                self.assertIn(
                    "ikke startet", authorized_timer_acknowledgement(receipt)
                )


if __name__ == "__main__":
    unittest.main()
