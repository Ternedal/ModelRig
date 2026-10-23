"""Offline tests for read-only delivery report and fail-closed unknown status."""
import datetime as dt
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from kaliv_delivery_report import GitHubReadClient, report, summarize_repo

class Response(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()

class DeliveryReportTests(unittest.TestCase):
    def test_collects_issue_pr_and_workflow(self):
        def opener(request, timeout):
            self.assertEqual(timeout, 15)
            self.assertEqual(request.get_method(), "GET")
            url = request.full_url
            if "/issues?" in url:
                value = [{"number": 1}, {"number": 2, "pull_request": {}}]
            elif "/pulls?" in url:
                value = [{"updated_at": "2020-01-01T00:00:00Z"}]
            elif "/actions/runs?" in url:
                value = {"workflow_runs": [{"conclusion": "failure", "html_url": "https://github.com/example/run"}]}
            else:
                raise AssertionError(url)
            return Response(json.dumps(value).encode())
        result = summarize_repo(GitHubReadClient("test", opener), "Ternedal", "ModelRig")
        self.assertEqual(result["status"], "collected")
        self.assertEqual(result["open_issues"], 1)
        self.assertEqual(result["open_prs"], 1)
        self.assertEqual(result["stale_prs"], 1)
        self.assertEqual(result["workflow"], "failure")

    def test_api_failure_never_becomes_green(self):
        def fail(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        result = summarize_repo(GitHubReadClient("test", fail), "Ternedal", "Kaliv")
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["open_issues"])
        self.assertEqual(result["workflow"], "unknown")
        self.assertTrue(result["warnings"])

    def test_empty_workflows_are_partial_not_success(self):
        def opener(request, timeout):
            value = {"workflow_runs": []} if "/actions/runs?" in request.full_url else []
            return Response(json.dumps(value).encode())
        result = summarize_repo(GitHubReadClient("test", opener), "Ternedal", "VoiceRig")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["workflow"], "unknown")

    def test_report_scope_and_no_token_in_output(self):
        def opener(request, timeout):
            value = {"workflow_runs": []} if "/actions/runs?" in request.full_url else []
            return Response(json.dumps(value).encode())
        result = report(GitHubReadClient("secret-value", opener), repositories=("ModelRig",))
        self.assertEqual(len(result["repositories"]), 1)
        self.assertNotIn("secret-value", json.dumps(result))

    def test_truncated_pages_are_unknown_not_false_counts(self):
        def opener(request, timeout):
            url = request.full_url
            if "/issues?" in url or "/pulls?" in url:
                value = [{"number": i, "updated_at": "2020-01-01T00:00:00Z"}
                         for i in range(100)]
            else:
                value = {"workflow_runs": [{"conclusion": "success"}]}
            return Response(json.dumps(value).encode())
        with patch("kaliv_delivery_report.MAX_PAGES", 1):
            result = summarize_repo(GitHubReadClient("test", opener), "Ternedal", "ModelRig")
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["open_issues"])
        self.assertIsNone(result["open_prs"])
        self.assertIsNone(result["stale_prs"])
        self.assertIn("pagination_limit_reached", result["warnings"])

    def test_requires_token_and_rejects_absolute_urls(self):
        with self.assertRaises(ValueError):
            GitHubReadClient("")
        with self.assertRaises(ValueError):
            GitHubReadClient("token").get("https://example.com")

if __name__ == "__main__":
    unittest.main()
