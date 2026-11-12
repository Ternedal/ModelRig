#!/usr/bin/env python3
"""Image and text-to-video, from the job route to the gallery route, in one run (#2275 6819704169).

The real job routes (media_job_api), the real executor from the entry point (build_from_env) with
the real staged video sink, ComfyUI adapter and supervisor driving the fake ComfyUI as a child
process, and the real gallery routes (media_gallery_api) on the same job database and volume.
The image pipeline is the stand-in (no torch, no GPU). Loopback only.

What it pins: a job submitted through the device route is what the gallery later lists and serves,
under the asset id the job status names; nothing else is listed.

Run: PYTHONPATH=worker python3 tests/worker_media_job_to_gallery.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import worker_media_executor_main_video as video_suite  # noqa: E402  (its fixture; not its tests)
from app.media_gallery_api import build_media_gallery_router, gallery_service_from_env  # noqa: E402
from app.media_job_api import build_media_job_router, service_from_env  # noqa: E402

SECRET = "e" * 40
HEADERS = {"X-Internal-Media-Secret": SECRET}
MOUNT = "app.media_gallery_catalog.os.path.ismount"


class JobToGalleryTests(video_suite.VideoEntryPointTests):
    def routes(self, env):
        app = FastAPI()
        app.include_router(build_media_job_router(lambda: service_from_env(env), loopback=lambda host: True))
        app.include_router(build_media_gallery_router(lambda: self.gallery, loopback=lambda host: True))
        return TestClient(app)

    def test_image_and_text_to_video_jobs_end_in_the_gallery_and_nothing_else_does(self):
        env = {**self.env, "KALIV_MEDIA_PROFILES_ENABLED": "sdxl-a,wan-a", "KALIV_MEDIA_INTERNAL_SECRET": SECRET}
        with patch(MOUNT, return_value=True):
            self.gallery = gallery_service_from_env(env)
            client = self.routes(env)
            image = client.post("/internal/media/jobs", headers=HEADERS, json={
                "profile_id": "sdxl-a", "prompt": "a red bicycle", "width": 1024, "height": 1024, "steps": 20})
            video = client.post("/internal/media/jobs", headers=HEADERS, json={
                "profile_id": "wan-a", "prompt": "a red kite over Nørrebro", "task": "text_to_video",
                **video_suite.VIDEO_PARAMS})
            cancelled = client.post("/internal/media/jobs", headers=HEADERS, json={
                "profile_id": "sdxl-a", "prompt": "never rendered", "width": 1024, "height": 1024, "steps": 20})
            self.assertEqual([r.status_code for r in (image, video, cancelled)], [202, 202, 202],
                             [r.text for r in (image, video, cancelled)])
            self.assertEqual(client.post(f"/internal/media/jobs/{cancelled.json()['id']}/cancel",
                                         headers=HEADERS).json()["result"], "cancelled")
            # Nothing is listed before anything completed.
            self.assertEqual(client.get("/internal/media/assets", headers=HEADERS).status_code, 503,
                             "no gallery index yet: cannot decide, never an empty 200")

            executor = self.build(env)
            self.assertEqual(executor.run(max_steps=4, idle_sleep=lambda: None), 0)

            jobs = {name: client.get(f"/internal/media/jobs/{r.json()['id']}", headers=HEADERS).json()
                    for name, r in (("image", image), ("video", video), ("cancelled", cancelled))}
            self.assertEqual({name: job["state"] for name, job in jobs.items()},
                             {"image": "completed", "video": "completed", "cancelled": "cancelled"})
            page = client.get("/internal/media/assets", headers=HEADERS)
            self.assertEqual(page.status_code, 200, page.text)
            items = {item["id"]: item for item in page.json()["items"]}
            self.assertEqual(set(items), {jobs["image"]["asset_id"], jobs["video"]["asset_id"]},
                             "exactly the two completed jobs' assets")
            for name, kind, mime in (("image", "image", "image/png"), ("video", "video", "video/mp4")):
                with self.subTest(name):
                    job = jobs[name]
                    item = items[job["asset_id"]]
                    self.assertEqual((item["kind"], item["mime_type"]), (kind, mime))
                    self.assertEqual(item["url"], job["asset_url"], "the job names the gallery's own link")
                    published = Path(env["KALIV_MEDIA_ROOT"], job["asset_id"] + (".png" if kind == "image" else ".mp4"))
                    served = client.get(f"/internal/media/assets/{job['asset_id']}", headers=HEADERS)
                    self.assertEqual((served.status_code, served.content), (200, published.read_bytes()))
                    self.assertEqual(served.headers["content-type"], mime)
            mp4 = client.get(f"/internal/media/assets/{jobs['video']['asset_id']}", headers={**HEADERS, "Range": "bytes=4-7"})
            self.assertEqual((mp4.status_code, mp4.content), (206, b"ftyp"))
            # The prompt reaches neither route's answers.
            for text in (page.text, *(client.get(f"/internal/media/jobs/{r.json()['id']}", headers=HEADERS).text
                                      for r in (image, video))):
                self.assertNotIn("bicycle", text)
                self.assertNotIn("Nørrebro", text)
            self.assertEqual(os.listdir(self.comfy_gpu / "output"), [], "nothing left on the internal disk")


# Only this file's test: the inherited fixture's own tests run in their own suite.
for _name in dir(video_suite.VideoEntryPointTests):
    if _name.startswith("test_"):
        setattr(JobToGalleryTests, _name, None)


if __name__ == "__main__":
    unittest.main()
