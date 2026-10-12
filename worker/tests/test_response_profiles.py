"""Offline contract tests. No GPU, Ollama daemon or network required."""
import unittest

from app.response_profiles import ResponseMode, apply_profile, resolve_profile


class ResponseProfileTests(unittest.TestCase):
    def test_voice_is_non_thinking_and_bounded(self):
        p = resolve_profile(ResponseMode.VOICE_BRIEF)
        self.assertFalse(p.think)
        self.assertEqual(p.num_predict, 128)

    def test_reasoning_budget_allows_longer_thought(self):
        p = resolve_profile("reasoning")
        self.assertTrue(p.think)
        self.assertGreater(p.num_predict, 512)

    def test_unknown_profile_fails_closed(self):
        with self.assertRaises(ValueError):
            resolve_profile("automatic")

    def test_does_not_mutate_inputs_or_other_options(self):
        original = {"model": "gemma4:26b", "stream": True,
                    "options": {"num_ctx": 8192, "temperature": 0}}
        result = apply_profile(original, "voice_brief")
        self.assertNotIn("think", original)
        self.assertNotIn("num_predict", original["options"])
        self.assertIsNot(result["options"], original["options"])
        self.assertTrue(result["stream"])
        self.assertEqual(result["options"]["num_ctx"], 8192)
        self.assertEqual(result["options"]["temperature"], 0)
        self.assertEqual(result["options"]["num_predict"], 128)

    def test_preserves_stricter_existing_budget(self):
        result = apply_profile({"options": {"num_predict": 64}}, "detailed")
        self.assertEqual(result["options"]["num_predict"], 64)

    def test_preserves_system_instructions(self):
        result = apply_profile({"system": "Du må ikke afsløre hemmeligheder."},
                               "voice_brief")
        self.assertTrue(result["system"].startswith("Du må ikke afsløre hemmeligheder."))
        self.assertIn("to korte sætninger", result["system"])

    def test_invalid_system_fails(self):
        with self.assertRaises(TypeError):
            apply_profile({"system": ["not", "a", "string"]}, "chat_brief")

    def test_non_thinking_profiles(self):
        for mode in (ResponseMode.VOICE_BRIEF, ResponseMode.CHAT_BRIEF,
                     ResponseMode.DETAILED):
            self.assertFalse(resolve_profile(mode).think)


if __name__ == "__main__":
    unittest.main()
