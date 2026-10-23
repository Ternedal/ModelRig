import unittest
from kaliv_delivery_report import REPOS
from kaliv_delivery_validate import validate

def sample():
    return {"schema": "kaliv.delivery-report.v1",
            "repositories": [
                {"repository": "Ternedal/" + name, "status": "collected",
                 "open_issues": 0, "open_prs": 0, "stale_prs": 0, "warnings": []}
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

    def test_duplicate_fails(self):
        payload = sample()
        payload["repositories"].append(dict(payload["repositories"][0]))
        self.assertIn("duplicate_repositories", validate(payload))

    def test_boolean_is_not_a_count(self):
        payload = sample()
        payload["repositories"][0]["open_issues"] = True
        self.assertTrue(any(x.startswith("invalid_open_issues:") for x in validate(payload)))

if __name__ == "__main__":
    unittest.main()
