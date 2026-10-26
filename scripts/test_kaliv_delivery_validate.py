import unittest
from kaliv_delivery_report import REPOS
from kaliv_delivery_validate import validate

def sample():
    return {"schema": "kaliv.delivery-report.v1",
            "repositories": [
                {"repository": "Ternedal/" + name, "status": "collected",
                 "open_issues": 0, "open_prs": 0, "stale_prs": 0, "workflow": "success", "warnings": []}
                for name in REPOS]}

class SnapshotValidationTests(unittest.TestCase):
    def test_complete_snapshot_passes(self):
        self.assertEqual(validate(sample()), [])

    def test_missing_repository_fails(self):
        payload = sample()
        payload["repositories"].pop()
        self.assertTrue(any(x.startswith("missing:") for x in validate(payload)))

    def test_unknown_and_truncated_fail(self):
        payload = sample()
        payload["repositories"][0]["status"] = "partial"
        payload["repositories"][0]["open_prs"] = None
        payload["repositories"][0]["warnings"] = ["pagination_limit_reached"]
        errors = validate(payload)
        self.assertTrue(any(x.startswith("incomplete:") for x in errors))
        self.assertTrue(any(x.startswith("invalid_open_prs:") for x in errors))
        self.assertTrue(any(x.startswith("warnings:") for x in errors))

    def test_pr_split_reconciles_with_total(self):
        payload = sample()
        repo = payload["repositories"][0]
        repo.update(open_prs=3, draft_prs=1, ready_prs=2)
        self.assertEqual(validate(payload), [])
        repo["ready_prs"] = 1
        self.assertTrue(any(x.startswith("invalid_pr_split:") for x in validate(payload)))

    def test_missing_or_boolean_pr_split_fails_closed(self):
        payload = sample()
        repo = payload["repositories"][0]
        repo.update(open_prs=1, draft_prs=None, ready_prs=1)
        self.assertTrue(any(x.startswith("invalid_pr_split:") for x in validate(payload)))
        repo["draft_prs"] = False
        self.assertTrue(any(x.startswith("invalid_pr_split:") for x in validate(payload)))

    def test_duplicate_fails(self):
        payload = sample()
        payload["repositories"].append(dict(payload["repositories"][0]))
        self.assertIn("duplicate_repositories", validate(payload))

    def test_unknown_workflow_is_incomplete(self):
        payload = sample()
        payload["repositories"][0]["workflow"] = "unknown"
        self.assertTrue(any(x.startswith("unknown_workflow:") for x in validate(payload)))

    def test_no_workflow_runs_is_explicit_not_an_api_error(self):
        payload = sample()
        payload["repositories"][0]["workflow"] = "none"
        self.assertEqual(validate(payload), [])

    def test_stale_ready_subset_reconciles(self):
        payload = sample()
        repo = payload["repositories"][0]
        repo.update(open_prs=3, draft_prs=1, ready_prs=2,
                    stale_prs=2, stale_ready_prs=1)
        self.assertEqual(validate(payload), [])
        repo["stale_ready_prs"] = 3
        self.assertTrue(any(x.startswith("invalid_stale_ready_prs:") for x in validate(payload)))
        repo["stale_ready_prs"] = True
        self.assertTrue(any(x.startswith("invalid_stale_ready_prs:") for x in validate(payload)))

    def test_non_object_payload_fails_closed(self):
        self.assertEqual(validate([]), ["payload_not_object"])

    def test_unhashable_repository_name_fails_closed(self):
        payload = sample()
        payload["repositories"][0]["repository"] = ["invalid"]
        self.assertIn("invalid_repository_name", validate(payload))

    def test_boolean_is_not_a_count(self):
        payload = sample()
        payload["repositories"][0]["open_issues"] = True
        self.assertTrue(any(x.startswith("invalid_open_issues:") for x in validate(payload)))

if __name__ == "__main__":
    unittest.main()
