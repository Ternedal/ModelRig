"""API contract tests with an injected external-volume catalog."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.video_media_api import build_media_router
from app.video_media_catalog import MediaCatalog
from app.video_media_contract import MediaItem


class MediaAPITests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for folder in ("Jobs", "Media/Images", "Media/Videos"):
            (root / folder).mkdir(parents=True)
        self.catalog = MediaCatalog(root)
        path = root / "Media" / "Videos" / "clip.mp4"
        path.write_bytes(b"0123456789")
        self.catalog.register(MediaItem("clip_1", "video"), path)
        app = FastAPI()
        app.include_router(build_media_router())
        self.client = TestClient(app)
        patcher = patch("app.video_media_api.MediaCatalog.on_external_volume", return_value=self.catalog)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_gallery(self):
        response = self.client.get("/experimental/media")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["id"], "clip_1")
        self.assertEqual(response.json()["items"][0]["url"], "/api/v1/media/clip_1")

    def test_seek(self):
        response = self.client.get("/api/v1/media/clip_1", headers={"Range": "bytes=3-5"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"345")
        self.assertEqual(response.headers["content-range"], "bytes 3-5/10")

    def test_head(self):
        response = self.client.head("/api/v1/media/clip_1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-length"], "10")
        self.assertEqual(response.content, b"")

    def test_unknown_media(self):
        self.assertEqual(self.client.get("/api/v1/media/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
