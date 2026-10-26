"""Regression tests for Kaliv delivery Markdown rendering."""
import unittest
from kaliv_delivery_markdown import render

class MarkdownReportTests(unittest.TestCase):
    def test_failures_and_unknown_are_visible(self):
        payload = {"schema": "kaliv.delivery-report.v1", "generated_at": "2026-10-23",
                   "repositories": [
                       {"repository": "Ternedal/ModelRig", "status": "collected",
                        "open_issues": 2, "open_prs": 1, "stale_prs": 1,
                        "workflow": "failure", "warnings": []},
                       {"repository": "Ternedal/Kaliv", "status": "unknown",
                        "open_issues": None, "open_prs": None,
                        "stale_prs": None, "workflow": "unknown",
                        "warnings": ["github_api_error:HTTPError"]}]}
        result = render(payload)
        self.assertIn("Draft PRs", result)
        self.assertIn("Ready PRs", result)
        self.assertIn("failure", result)
        self.assertIn("unknown", result)
        self.assertIn("stale PR(s)", result)
        self.assertIn("not a rollup of all required checks", result)

    def test_no_false_production_green(self):
        result = render({"schema": "kaliv.delivery-report.v1",
                         "repositories": [{"repository": "Ternedal/VoiceRig",
                             "status": "collected", "open_issues": 0,
                             "open_prs": 0, "stale_prs": 0, "workflow": "success",
                             "warnings": []}]})
        self.assertIn("not", result.lower())
        self.assertIn("release readiness", result)

    def test_escape_and_invalid_schema(self):
        result = render({"schema": "kaliv.delivery-report.v1",
                         "repositories": [{"repository": "evil|table\nrow",
                             "status": "unknown", "workflow": "unknown"}]})
        self.assertIn("evil\\|table row", result)
        with self.assertRaises(ValueError):
            render({"schema": "wrong", "repositories": []})

if __name__ == "__main__":
    unittest.main()
