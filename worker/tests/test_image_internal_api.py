"""Internal image router tests; no public backend exposure."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.image_job_store import ImageJobStore
from app.image_media_store import ExternalMediaStore
from app import image_internal_api as api

_SECRET = "local-test-only-secret-32-characters-minimum"


class ImageInternalApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.jobs = ImageJobStore(str(root / "jobs.sqlite3"))
        with patch("app.image_media_store.os.path.ismount", return_value=True):
            media = ExternalMediaStore(str(root), [str(root)], min_free_bytes=0)
        api.configure_image_routes(self.jobs, media, internal_secret=_SECRET)
        app = FastAPI()
        app.include_router(api.router)
        self.client = TestClient(app)

    def _headers(self, owner="owner-a"):
        return {"X-Verified-Owner": owner, "X-Internal-Media-Secret": _SECRET}

    def test_requires_internal_secret_even_with_owner(self):
        response = self.client.post("/internal/media/images/jobs", json={"prompt": "hello"},
                                    headers={"X-Verified-Owner": "owner-a"})
        self.assertEqual(response.status_code, 401)
        response = self.client.post("/internal/media/images/jobs", json={"prompt": "hello"},
                                    headers={"X-Verified-Owner": "owner-a",
                                             "X-Internal-Media-Secret": "incorrect"})
        self.assertEqual(response.status_code, 401)

    def test_requires_verified_owner_header(self):
        response = self.client.post("/internal/media/images/jobs", json={"prompt": "hello"},
                                    headers={"X-Internal-Media-Secret": _SECRET})
        self.assertEqual(response.status_code, 401)

    def test_submit_status_cancel(self):
        response = self.client.post("/internal/media/images/jobs",
                                    json={"prompt": "blue elephant"}, headers=self._headers())
        self.assertEqual(response.status_code, 202)
        job_id = response.json()["job_id"]
        path = f"/internal/media/images/jobs/{job_id}"
        self.assertEqual(self.client.get(path, headers=self._headers()).json()["status"], "queued")
        self.assertEqual(self.client.get(path, headers=self._headers("owner-b")).status_code, 404)
        self.assertEqual(self.client.post(path + "/cancel", headers=self._headers()).status_code, 200)
        self.assertEqual(self.client.get(path, headers=self._headers()).json()["status"], "cancelled")

    def test_asset_not_found_for_other_owner(self):
        response = self.client.get("/internal/media/images/assets/" + "a" * 32,
                                   headers=self._headers())
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
