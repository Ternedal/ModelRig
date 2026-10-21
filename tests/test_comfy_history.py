"""Offline fake-history tests; never connects to ComfyUI."""
import unittest
from unittest.mock import patch

from worker.app.comfy_history import poll_history
from worker.app.comfy_transport import ComfyTransport, ComfyTransportError


class Response:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.body


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.transport = ComfyTransport("http://127.0.0.1:8188")

    def query(self, body):
        with patch.object(self.transport._opener, "open", return_value=Response(body)):
            return poll_history(self.transport, "abc")

    def test_pending(self):
        self.assertEqual(self.query(b"{}"), {"state": "pending"})

    def test_success(self):
        body = b'{"abc":{"status":{"status_str":"success","completed":true},"outputs":{"9":{"images":[{"filename":"image.png","subfolder":"","type":"output"}]}}}}'
        self.assertEqual(self.query(body), {"state": "succeeded", "filenames": ["image.png"]})

    def test_failure(self):
        body = b'{"abc":{"status":{"status_str":"error","completed":false}}}'
        self.assertEqual(self.query(body)["state"], "failed")

    def test_unsafe_filename(self):
        body = b'{"abc":{"status":{"status_str":"success","completed":true},"outputs":{"9":{"images":[{"filename":"../private","subfolder":"","type":"output"}]}}}}'
        with self.assertRaises(ComfyTransportError):
            self.query(body)

    def test_invalid_prompt_id(self):
        with self.assertRaises(ComfyTransportError):
            poll_history(self.transport, "../../admin")


if __name__ == "__main__":
    unittest.main()
