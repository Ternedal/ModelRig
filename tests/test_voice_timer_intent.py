"""Voice timer commands must not claim a scheduled alert without authorization."""
import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_intent import parse_timer_request, unsupported_timer_reply


class TimerIntentTest(unittest.TestCase):
    def test_timer_intent(self):
        self.assertEqual(parse_timer_request("Sæt en timer på 5 minutter."), 300)
        self.assertEqual(parse_timer_request("Start en timer på 30 sekunder"), 30)
        self.assertIsNone(parse_timer_request("Sæt en timer på 0 minutter."))
        self.assertIsNone(parse_timer_request("Sæt en timer på 90 minutter."))
        self.assertIsNone(parse_timer_request("Hvad er klokken?"))

    def test_no_false_success(self):
        answer = unsupported_timer_reply("Sæt en timer på 5 minutter.")
        self.assertIn("ikke startet", answer)
        self.assertIsNone(unsupported_timer_reply("Fortæl mig om timere."))


if __name__ == "__main__":
    unittest.main()
