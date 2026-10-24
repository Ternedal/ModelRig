"""Offline ComfyUI output import tests, with no network or rig dependencies."""
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.app.comfy_media_import import import_comfy_output
from worker.app.comfy_transport import ComfyTransport, ComfyTransportError


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.payload


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.transport = ComfyTransport("http://127.0.0.1:8188")

    def test_import_delegates_to_storage_guard(self):
        with patch.object(self.transport._opener, "open", return_value=FakeResponse(b"image")) as http:
            with patch("worker.app.comfy_media_import.write_media_exclusive", return_value=Path("/external/image.png")) as save:
                path = import_comfy_output(self.transport, "source.png", Path("/external"), "image.png")
                self.assertEqual(path, Path("/external/image.png"))
                save.assert_called_once_with(Path("/external"), "image.png", b"image", max_bytes=100_000_000)
                self.assertIn("type=output", http.call_args.args[0].full_url)

    def test_rejects_traversal_before_network(self):
        with patch.object(self.transport._opener, "open") as http:
            with self.assertRaises(ComfyTransportError):
                import_comfy_output(self.transport, "../secret", Path("/external"), "image.png")
            http.assert_not_called()

    def test_rejects_oversized_payload_without_write(self):
        with patch.object(self.transport._opener, "open", return_value=FakeResponse(b"too long")):
            with patch("worker.app.comfy_media_import.write_media_exclusive") as save:
                with self.assertRaises(ComfyTransportError):
                    import_comfy_output(self.transport, "source.png", Path("/external"), "image.png", max_bytes=2)
                save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
