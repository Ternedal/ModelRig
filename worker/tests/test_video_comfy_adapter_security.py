"""Offline ComfyUI HTTP boundary tests, no network or model downloads."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from app.video_comfy_adapter import ComfyVideoClient, VideoBackendError


class FakeResponse:
    def __init__(self, payload):
        self.stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.stream.read(size)


class ComfyAdapterSecurityTests(unittest.TestCase):
    def test_invalid_timeout_values_are_rejected(self):
        for timeout in (0, -1, 121, float("nan"), float("inf"),
                        float("-inf"), True, "10", None):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                ComfyVideoClient(timeout=timeout)

    def test_remote_endpoint_is_rejected(self):
        for endpoint in ("http://example.com:8188", "https://127.0.0.1:8188",
                         "http://127.0.0.1:8188/redirect",
                         "http://user:pass@127.0.0.1:8188"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                ComfyVideoClient(endpoint)

    def test_submit_trusted_graph_returns_valid_prompt_id(self):
        client = ComfyVideoClient()
        with patch.object(client._opener, "open",
                          return_value=FakeResponse({"prompt_id": "abc_123"})) as opener:
            self.assertEqual(client.submit_trusted_workflow(
                {"node": {"class_type": "Example"}}), "abc_123")
            request = opener.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8188/prompt")
            self.assertEqual(request.get_method(), "POST")

    def test_oversized_response_is_rejected(self):
        client = ComfyVideoClient()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"x" * 2_000_001
        with patch.object(client._opener, "open", return_value=response):
            with self.assertRaises(VideoBackendError):
                client.submit_trusted_workflow({"node": {}})

    def test_non_object_json_is_rejected(self):
        client = ComfyVideoClient()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"[]"
        with patch.object(client._opener, "open", return_value=response):
            with self.assertRaises(VideoBackendError):
                client.submit_trusted_workflow({"node": {}})

    def test_invalid_timeout_is_rejected(self):
        for timeout in (0, -1, 121, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                ComfyVideoClient(timeout=timeout)

    def test_invalid_prompt_id_fails_closed(self):
        client = ComfyVideoClient()
        with patch.object(client._opener, "open",
                          return_value=FakeResponse({"prompt_id": "../../escape"})):
            with self.assertRaises(VideoBackendError):
                client.submit_trusted_workflow({"node": {}})

    def test_history_rejects_path_injection_before_network(self):
        client = ComfyVideoClient()
        with patch.object(client._opener, "open") as opener:
            for prompt_id in ("../escape", "a/b", "", "a?b"):
                with self.subTest(prompt_id=prompt_id), self.assertRaises(ValueError):
                    client.history(prompt_id)
            opener.assert_not_called()

    def test_completed_outputs_requires_success_status(self):
        client = ComfyVideoClient()
        with patch.object(client, "history", return_value={
            "p1": {"status": {"completed": True, "status_str": "success"},
                   "outputs": {"node": {"videos": []}}}
        }):
            self.assertEqual(client.completed_outputs("p1"), {"node": {"videos": []}})
        with patch.object(client, "history", return_value={
            "p1": {"status": {"completed": False, "status_str": "running"}}
        }):
            self.assertIsNone(client.completed_outputs("p1"))
        with patch.object(client, "history", return_value={
            "p1": {"status": {"completed": True, "status_str": "error"}}
        }):
            with self.assertRaises(VideoBackendError):
                client.completed_outputs("p1")


if __name__ == "__main__":
    unittest.main()
