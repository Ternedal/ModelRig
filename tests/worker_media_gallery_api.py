#!/usr/bin/env python3
"""Internal gallery read routes: ownership join, verified volume, Range (#2275 6819704169).

The shared fixture (contracts/kaliv-media-gallery-v1-fixtures.json, #2374) is the index; the real
ImageJobStore decides ownership and the real MountedMediaVolume (with the test probe for the mount
point) decides the volume. T1-T6 from #2365 6817417307.

Run: PYTHONPATH=worker python3 tests/worker_media_gallery_api.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.image_job_store import ImageJobError, ImageJobStore  # noqa: E402
from app.media_gallery_api import (MediaGalleryService, build_media_gallery_router, byte_range,  # noqa: E402
                                   gallery_service_from_env)
from app.media_job_api import OWNER, MediaJobsUnavailable, cached_service  # noqa: E402
from app.media_volume import MARKER_NAME, MountedMediaVolume  # noqa: E402
from worker_media_volume import VOLUME_ID, FakeProbe  # noqa: E402

FIXTURE = json.loads((ROOT / "contracts" / "kaliv-media-gallery-v1-fixtures.json").read_text(encoding="utf-8"))
SECRET = "g" * 40
HEADERS = {"X-Internal-Media-Secret": SECRET}
INSTANCE = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab:0123456789abcdef"
EXT = {"image/png": ".png", "video/mp4": ".mp4", "image/jpeg": ".jpg", "image/webp": ".webp"}
MOUNT = "app.media_gallery_catalog.os.path.ismount"


def client_for(service, *, loopback=lambda host: True) -> TestClient:
    app = FastAPI()
    app.include_router(build_media_gallery_router(service if callable(service) else (lambda: service),
                                                  loopback=loopback))
    return TestClient(app)


class GalleryRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.volume_root = self.tmp / "vol"
        self.media = self.volume_root / "media"
        self.media.mkdir(parents=True)
        (self.volume_root / MARKER_NAME).write_text(VOLUME_ID, encoding="ascii")
        self.write_index(FIXTURE["index"])
        for entry in FIXTURE["index"]:
            with open(self.media / f"{entry['id']}{EXT[entry['mime_type']]}", "wb") as handle:
                if entry["id"] == "img_png_1024":
                    handle.write(bytes(range(256)) * (entry["size_bytes"] // 256))
                else:
                    handle.truncate(entry["size_bytes"])  # sparse: the size is what is checked
        self.probe = FakeProbe({str(self.volume_root)})
        self.volume = MountedMediaVolume(str(self.volume_root), VOLUME_ID, probe=self.probe)
        self.store = ImageJobStore(str(self.tmp / "jobs.sqlite3"))
        self.mount = patch(MOUNT, return_value=True)
        self.mount.start()
        self.addCleanup(self.mount.stop)
        # T1's shape: completed x3 (one of them the VR180 video), failed, running.
        self.complete("img_png_1024")
        self.complete("vid_vr180_lr")
        self.complete("vid_flat_writer_shape")
        self.job("img_jpeg_fraction", end="failed")
        self.job("img_webp_writer_shape", end="running")
        self.service = MediaGalleryService(self.store, self.volume, str(self.media), SECRET)
        self.client = client_for(self.service)

    # -- fixtures -----------------------------------------------------------------------------
    def write_index(self, entries):
        (self.media / "gallery-index.json").write_text(json.dumps(entries), encoding="utf-8")

    def job(self, asset_id, *, end):
        job = self.store.submit(OWNER, "p", profile_id="sdxl-a", max_owner_active=16, max_queued=16)["job_id"]
        self.assertEqual(self.store.claim_for(["sdxl-a"], INSTANCE)["id"], job)
        if end == "completed":
            self.assertTrue(self.store.begin_publish(job, INSTANCE))
            self.assertTrue(self.store.complete(job, INSTANCE, asset_id))
        elif end == "failed":
            self.assertTrue(self.store.begin_publish(job, INSTANCE))
            self.assertTrue(self.store.fail(job, INSTANCE, "publication_failed"))
            with sqlite3.connect(self.tmp / "jobs.sqlite3") as db:  # an asset id on a failed job
                db.execute("UPDATE image_jobs SET asset_id=? WHERE id=?", (asset_id, job))
        return job

    def complete(self, asset_id):
        return self.job(asset_id, end="completed")

    def get(self, path, **headers):
        return self.client.get(path, headers={**HEADERS, **headers})

    def items(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return [item["id"] for item in response.json()["items"]]

    # -- T1: the list holds exactly the completed assets ---------------------------------------
    def test_t1_only_completed_assets_in_index_order_and_pagination_stays_inside(self):
        owned = ["img_png_1024", "vid_vr180_lr", "vid_flat_writer_shape"]
        page = self.get("/internal/media/assets?limit=100")
        self.assertEqual(self.items(page), owned)
        self.assertEqual(page.json()["schema"], "kaliv-media-gallery/v1")
        self.assertIsNone(page.json()["next_cursor"])
        expected = [item for item in FIXTURE["page"]["items"] if item["id"] in owned]
        self.assertEqual(page.json()["items"], expected, "the fixture's item shape, unchanged")
        first = self.get("/internal/media/assets?limit=2")
        self.assertEqual(self.items(first), owned[:2])
        self.assertEqual(first.json()["next_cursor"], "vid_vr180_lr")
        second = self.get("/internal/media/assets?limit=2&cursor=vid_vr180_lr")
        self.assertEqual(self.items(second), owned[2:])
        self.assertIsNone(second.json()["next_cursor"])
        for cursor in ("img_jpeg_fraction", "nope"):
            with self.subTest(cursor=cursor):
                response = self.get(f"/internal/media/assets?limit=2&cursor={cursor}")
                self.assertEqual((response.status_code, response.json()["detail"]), (400, "unknown_cursor"))

    def test_t1_a_thumbnail_that_is_not_owned_is_never_linked(self):
        with sqlite3.connect(self.tmp / "jobs.sqlite3") as db:
            db.execute("UPDATE image_jobs SET state='failed' WHERE asset_id='img_png_1024'")
        vr = [item for item in self.get("/internal/media/assets").json()["items"] if item["id"] == "vid_vr180_lr"][0]
        self.assertEqual((vr["thumbnail_id"], vr["thumbnail_url"]), (None, None))

    def test_query_and_limit_are_bounded(self):
        for query in ("limit=0", "limit=101", "limit=abc", "limit=1&limit=2", "x=1", "cursor=a%2Fb"):
            with self.subTest(query=query):
                self.assertEqual(self.get(f"/internal/media/assets?{query}").status_code, 400)

    # -- T2: not owned is the same 404 as unknown, decided before the volume -------------------
    def test_t2_failed_running_unindexed_and_unknown_are_the_same_404(self):
        bodies = set()
        for asset_id in ("img_jpeg_fraction", "img_webp_writer_shape", "never_published", "a" * 128):
            for method in ("GET", "HEAD"):
                with self.subTest(asset=asset_id, method=method):
                    response = self.client.request(method, f"/internal/media/assets/{asset_id}", headers=HEADERS)
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.headers["cache-control"], "private, no-store") if method == "GET" else None
                    bodies.add(response.text)
        self.assertEqual(len(bodies - {""}), 1, "one body for every 404: no existence oracle")

    def test_t2_ownership_is_decided_before_the_volume_is_touched(self):
        self.probe.mounts = set()  # Z: gone
        self.assertEqual(self.get("/internal/media/assets/img_jpeg_fraction").status_code, 404)
        owned = self.get("/internal/media/assets/img_png_1024")
        self.assertEqual(owned.status_code, 503)
        self.assertTrue(owned.json()["detail"].startswith("media_volume_"), owned.text)

    # -- bytes, Range and HEAD ----------------------------------------------------------------
    def test_full_ranged_suffix_unsatisfiable_and_head(self):
        data = (self.media / "img_png_1024.png").read_bytes()
        full = self.get("/internal/media/assets/img_png_1024")
        self.assertEqual((full.status_code, full.content), (200, data))
        self.assertEqual(full.headers["content-type"], "image/png")
        self.assertEqual(full.headers["content-length"], str(len(data)))
        self.assertEqual(full.headers["accept-ranges"], "bytes")
        self.assertEqual(full.headers["cache-control"], "private, no-store")
        part = self.get("/internal/media/assets/img_png_1024", Range="bytes=2-5")
        self.assertEqual((part.status_code, part.content, part.headers["content-range"]),
                         (206, data[2:6], f"bytes 2-5/{len(data)}"))
        tail = self.get("/internal/media/assets/img_png_1024", Range="bytes=-3")
        self.assertEqual((tail.status_code, tail.content), (206, data[-3:]))
        video = self.get("/internal/media/assets/vid_vr180_lr", Range="bytes=52428700-")
        self.assertEqual((video.status_code, len(video.content), video.headers["content-type"]),
                         (206, 100, "video/mp4"))
        past = self.get("/internal/media/assets/img_png_1024", Range=f"bytes={len(data)}-")
        self.assertEqual((past.status_code, past.headers["content-range"]), (416, f"bytes */{len(data)}"))
        multi = self.get("/internal/media/assets/img_png_1024", Range="bytes=1-2,4-5")
        self.assertEqual((multi.status_code, len(multi.content)), (200, len(data)))
        head = self.client.head("/internal/media/assets/img_png_1024", headers={**HEADERS, "Range": "bytes=2-5"})
        self.assertEqual((head.status_code, head.content, head.headers["content-length"]), (206, b"", "4"))

    def test_byte_range_rules(self):
        self.assertEqual(byte_range(None, 10), (0, 9, False))
        self.assertEqual(byte_range("bytes=2-5", 10), (2, 5, True))
        self.assertEqual(byte_range("bytes=8-100", 10), (8, 9, True))
        self.assertEqual(byte_range("bytes=-3", 10), (7, 9, True))
        self.assertEqual(byte_range("bytes=-30", 10), (0, 9, True))
        for header in ("bytes=10-", "bytes=-0"):
            self.assertEqual(byte_range(header, 10), "unsatisfiable", header)
        for header in ("bytes=5-2", "bytes=-", "items=0-1", "bytes=1-2,4-5", "bytes=a-b"):
            self.assertEqual(byte_range(header, 10), "ignore", header)

    # -- T3/T4: cannot decide is 503, never an empty 200 or a 404 ------------------------------
    def test_t3_too_many_completed_assets_is_503(self):
        with patch.object(self.store, "completed_assets_for", side_effect=ImageJobError("owner_asset_limit")):
            response = self.get("/internal/media/assets")
        self.assertEqual((response.status_code, response.json()["detail"]), (503, "owner_asset_limit"))

    def test_t4_a_database_error_is_503_for_list_and_open(self):
        broken = sqlite3.OperationalError("disk I/O error at /secret/path")
        with patch.object(self.store, "completed_assets_for", side_effect=broken):
            listed = self.get("/internal/media/assets")
        with patch.object(self.store, "owns_completed_asset", side_effect=broken):
            opened = self.get("/internal/media/assets/img_png_1024")
        for response in (listed, opened):
            self.assertEqual((response.status_code, response.json()["detail"]), (503, "media_gallery_unavailable"))
            self.assertNotIn("secret", response.text)

    def test_t4_a_lost_volume_is_503_and_stays_lost_after_it_returns(self):
        self.assertEqual(self.get("/internal/media/assets").status_code, 200)
        self.probe.mounts = set()
        gone = self.get("/internal/media/assets")
        self.assertEqual(gone.status_code, 503)
        self.probe.mounts = {str(self.volume_root)}  # replugged: still refused until a restart
        again = self.get("/internal/media/assets")
        self.assertEqual((again.status_code, again.json()["detail"]), (503, "media_volume_lost"))
        self.assertEqual(self.get("/internal/media/assets/img_png_1024").status_code, 503)

    def test_a_changed_marker_is_503(self):
        (self.volume_root / MARKER_NAME).write_text("kaliv-media-9999", encoding="ascii")
        response = self.get("/internal/media/assets")
        self.assertEqual((response.status_code, response.json()["detail"]), (503, "media_volume_marker_mismatch"))

    def test_an_owned_asset_that_is_missing_resized_linked_or_unindexed_is_503(self):
        png = self.media / "img_png_1024.png"
        original = png.read_bytes()
        cases = {
            "missing": lambda: png.unlink(),
            "grown": lambda: png.write_bytes(original + b"x"),
            "link": lambda: (png.unlink(), png.symlink_to(self.media / "vid_flat_writer_shape.mp4")),
            "unindexed": lambda: self.write_index([e for e in FIXTURE["index"] if e["id"] != "img_png_1024"]),
        }
        for label, change in cases.items():
            with self.subTest(label):
                if png.is_symlink() or png.exists():
                    png.unlink()
                png.write_bytes(original)
                self.write_index(FIXTURE["index"])
                change()
                response = self.get("/internal/media/assets/img_png_1024")
                self.assertEqual(response.status_code, 503, response.text)
                self.assertTrue(response.json()["detail"].startswith("media_"), response.text)
                self.assertNotIn(str(self.tmp), response.text, "never a path")

    def test_a_malformed_index_is_503(self):
        (self.media / "gallery-index.json").write_text('[{"id":"x","url":"/elsewhere"}]', encoding="utf-8")
        self.assertEqual(self.get("/internal/media/assets").status_code, 503)

    # -- T6: the internal boundary -------------------------------------------------------------
    def test_t6_secret_and_loopback_come_first(self):
        for headers in ({}, {"X-Internal-Media-Secret": "wrong" * 10}):
            with self.subTest(headers=bool(headers)):
                self.assertEqual(self.client.get("/internal/media/assets", headers=headers).status_code, 401)
                self.assertEqual(self.client.get("/internal/media/assets/img_png_1024", headers=headers).status_code, 401)
        remote = client_for(self.service, loopback=lambda host: False)
        self.assertEqual(remote.get("/internal/media/assets", headers=HEADERS).status_code, 401)

    def test_t6_an_unusable_configuration_is_503_with_a_code_and_is_retried(self):
        calls = {"n": 0}

        def factory():
            calls["n"] += 1
            if calls["n"] == 1:
                raise MediaJobsUnavailable("media_gallery_root_invalid")
            return self.service
        client = client_for(cached_service(factory))
        first = client.get("/internal/media/assets", headers=HEADERS)
        self.assertEqual((first.status_code, first.json()["detail"]), (503, "media_gallery_root_invalid"))
        self.assertEqual(client.get("/internal/media/assets", headers=HEADERS).status_code, 200)

    def test_each_missing_setting_is_a_code(self):
        base = {"KALIV_MEDIA_INTERNAL_SECRET": SECRET}
        for env, code in (({}, "media_jobs_secret_invalid"),):
            with self.subTest(code=code), self.assertRaises(MediaJobsUnavailable) as caught:
                gallery_service_from_env(env)
            self.assertEqual(str(caught.exception), code)
        with self.assertRaises(MediaJobsUnavailable):
            gallery_service_from_env(base)  # no work area: refused with a code, nothing opened


if __name__ == "__main__":
    unittest.main()
