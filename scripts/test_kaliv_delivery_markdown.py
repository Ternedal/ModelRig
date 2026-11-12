"""Regression tests for Kaliv delivery Markdown rendering."""
import unittest
from kaliv_delivery_markdown import render

class MarkdownReportTests(unittest.TestCase):
    def test_failures_and_unknown_are_visible(self):
        payload = {"schema": "kaliv.delivery-report.v1", "generated_at": "2026-10-23",
                   "repositories": [
                       {"repository": "Ternedal/ModelRig", "status": "collected",
                        "open_issues": 2, "open_prs": 1, "stale_prs": 1, "stale_ready_prs": 1,
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
        self.assertIn("stale ready PR(s)", result)
        self.assertIn("not a rollup of all required checks", result)
        self.assertIn("default branch", result)

    def test_collected_with_warnings_requires_attention(self):
        result = render({"schema": "kaliv.delivery-report.v1",
                         "repositories": [{"repository": "Ternedal/ModelRig",
                             "status": "collected", "workflow": "success",
                             "stale_ready_prs": 0,
                             "warnings": ["pagination_truncated"]}]})
        self.assertIn("## Attention required", result)
        self.assertIn("collector warnings: pagination_truncated", result)
        self.assertNotIn("No warning conditions detected", result)

    def test_parked_draft_not_flagged_as_stale_ready(self):
        result = render({"schema": "kaliv.delivery-report.v1",
                         "repositories": [{"repository": "Ternedal/ModelRig",
                             "default_branch": "main", "status": "collected",
                             "open_issues": 0, "open_prs": 1,
                             "draft_prs": 1, "ready_prs": 0,
                             "stale_prs": 1, "stale_ready_prs": 0,
                             "workflow": "none", "warnings": []}]})
        self.assertIn("No warning conditions detected", result)
        self.assertIn("none", result)
        self.assertNotIn("stale ready PR(s)", result)

    def test_every_workflow_state_but_fine_ones_is_flagged(self):
        # #2275 item 24: startup_failure (a broken workflow file) and action_required read
        # as fine when only failure/cancelled/timed_out/unknown were flagged.
        def flagged(workflow):
            out = render({"schema": "kaliv.delivery-report.v1",
                          "repositories": [{"repository": "Ternedal/ModelRig", "status": "collected",
                                            "open_issues": 0, "open_prs": 0, "stale_prs": 0,
                                            "workflow": workflow, "warnings": []}]})
            return out.split("## Attention required")[1].split("## Next actions")[0]
        for state in ("startup_failure", "action_required", "stale", "failure", "cancelled",
                      "timed_out", "unknown", "some_future_state"):
            self.assertIn("latest workflow: " + state, flagged(state), state)
        for state in ("in_progress", "queued"):
            self.assertIn("latest workflow not finished: " + state, flagged(state), state)
        for state in ("success", "neutral", "skipped", "none"):
            self.assertIn("No warning conditions detected", flagged(state), state)

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
