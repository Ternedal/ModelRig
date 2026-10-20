"""Offline contract tests for the dormant ComfyUI video adapter."""
import unittest
from unittest.mock import patch
import urllib.error

from app.video_comfy_adapter import ComfyVideoClient, VideoBackendError


class ComfyVideoClientTests(unittest.TestCase):
    def test_loopback_only(self):
        for url in ("https://127.0.0.1:8188", "http://example.com:8188",
                    "http://192.168.1.2:8188", "http://127.0.0.1:8188/api",
                    "http://user:pass@localhost:8188"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ComfyVideoClient(url)

    def test_defaults_to_loopback(self):
        self.assertEqual(ComfyVideoClient().base_url, "http://127.0.0.1:8188")

    def test_rejects_invalid_workflow(self):
        with self.assertRaises(ValueError):
            ComfyVideoClient().submit_trusted_workflow({})

    def test_rejects_invalid_history_id(self):
        for prompt_id in ("../prompt", "", "a/b", "?" * 200):
            with self.subTest(prompt_id=prompt_id), self.assertRaises(ValueError):
                ComfyVideoClient().history(prompt_id)

    def test_outputs_are_not_ready_until_completed(self):
        client = ComfyVideoClient()
        with patch.object(client, "history", return_value={
            "prompt_1": {"status": {"completed": False, "status_str": "running"},
                         "outputs": {"node": {"videos": []}}}
        }):
            self.assertIsNone(client.completed_outputs("prompt_1"))

    def test_explicit_backend_error_raises(self):
        client = ComfyVideoClient()
        with patch.object(client, "history", return_value={
            "prompt_1": {"status": {"completed": False, "status_str": "error"}, "outputs": {}}
        }):
            with self.assertRaises(VideoBackendError):
                client.completed_outputs("prompt_1")

    def test_completed_backend_returns_outputs(self):
        client = ComfyVideoClient()
        expected = {"node": {"videos": []}}
        with patch.object(client, "history", return_value={
            "prompt_1": {"status": {"completed": True, "status_str": "success"}, "outputs": expected}
        }):
            self.assertEqual(client.completed_outputs("prompt_1"), expected)

    def test_redirect_to_external_host_is_rejected(self):
        client = ComfyVideoClient()
        request = __import__("urllib.request", fromlist=["Request"]).Request(client.base_url + "/history/abc")
        with self.assertRaises(VideoBackendError):
            next(handler for handler in client._opener.handlers if handler.__class__.__name__ == "_NoRedirect").redirect_request(request, None, 302, "Found", {}, "https://example.com/")

    def test_missing_backend_is_reported(self):
        client = ComfyVideoClient()
        with patch.object(client._opener, "open", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(VideoBackendError):
                client.history("abc-123")


if __name__ == "__main__":
    unittest.main()
