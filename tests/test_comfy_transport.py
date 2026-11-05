"""Offline validation and fake-network tests for ComfyUI transport."""
import io
import unittest
from unittest.mock import patch

from worker.app.comfy_transport import ComfyTransport, ComfyTransportError, validate_comfy_url


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return b'{"prompt_id":"abc123"}'


class ComfyTransportTests(unittest.TestCase):
    def test_loopback_only(self):
        for url in (
            "http://192.168.1.2:8188", "https://127.0.0.1:8188",
            "http://localhost:8188", "http://127.0.0.1:8188/other",
            "http://user:pass@127.0.0.1:8188", "http://127.0.0.1",
            "http://127.0.0.1:8188?x=1",
        ):
            with self.subTest(url=url), self.assertRaises(ComfyTransportError):
                validate_comfy_url(url)
        self.assertEqual(validate_comfy_url("http://127.0.0.1:8188"), "http://127.0.0.1:8188")

    def test_prompt_submission(self):
        transport = ComfyTransport("http://127.0.0.1:8188")
        with patch.object(transport._opener, "open", return_value=FakeResponse()) as mocked:
            self.assertEqual(transport.submit_prompt({"node": {"class_type": "SaveImage"}}, "client"), "abc123")
            request = mocked.call_args.args[0]
            self.assertEqual(request.full_url, "http://127.0.0.1:8188/prompt")
            self.assertEqual(request.get_method(), "POST")

    def test_invalid_payload(self):
        transport = ComfyTransport("http://127.0.0.1:8188")
        for workflow, client in (({}, "client"), ({"node": 1}, ""), ({"node": float("nan")}, "client")):
            with self.subTest(workflow=workflow), self.assertRaises((ComfyTransportError, ValueError)):
                transport.submit_prompt(workflow, client)


if __name__ == "__main__":
    unittest.main()
