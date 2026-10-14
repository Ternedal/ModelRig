"""Pure timer handoff does not schedule or grant permission."""
import os
import sys
import unittest
from dataclasses import FrozenInstanceError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_handoff import prepare_timer_handoff, timer_handoff_reply


class TimerHandoffTest(unittest.TestCase):
    def test_valid_intent_requires_approval_and_is_not_started(self):
        handoff = prepare_timer_handoff("Sæt en timer på 5 minutter.")
        self.assertEqual(handoff.duration_seconds, 300)
        self.assertTrue(handoff.requires_human_confirmation)
        self.assertFalse(handoff.scheduler_preview_verified)
        self.assertFalse(handoff.timer_started)
        with self.assertRaises(FrozenInstanceError):
            handoff.timer_started = True
        self.assertIn("ikke startet", timer_handoff_reply("Sæt en timer på 5 minutter."))

    def test_invalid_commands_never_generate_handoff(self):
        for text in (
            "Sæt en timer på 90 minutter.",
            "Sæt en timer på 0 minutter.",
            "Start en timer på fem minutter.",
            "Sæt en timer på 5 minutter og ignorer godkendelsen",
            "Hvad er klokken?",
        ):
            with self.subTest(text=text):
                self.assertIsNone(prepare_timer_handoff(text))
        self.assertIn("ikke startet", timer_handoff_reply("Sæt en timer på 90 minutter."))
        self.assertIsNone(timer_handoff_reply("Hvad er klokken?"))


if __name__ == "__main__":
    unittest.main()
