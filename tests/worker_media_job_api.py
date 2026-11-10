#!/usr/bin/env python3
"""Internal media job routes: submit, status, cancel (#2275 6764090458, backlog item 4).

Run: PYTHONPATH=worker python3 tests/worker_media_job_api.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.image_job_store import ImageJobStore, QUEUED_MAX_AGE_S  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_job_api import (OWNER, MediaJobService, MediaJobsUnavailable, build_media_job_router,  # noqa: E402
                               cached_service, service_from_env)
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

SECRET = "s" * 40
INSTANCE = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab:0123456789abcdef"
HEADERS = {"X-Internal-Media-Secret": SECRET}
PROMPT = "a red bicycle under a streetlight"


def client_for(service, *, loopback=lambda host: True):
    app = FastAPI()
    app.include_router(build_media_job_router(service if callable(service) else (lambda: service),
                                              loopback=loopback))
    return TestClient(app)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = ImageJobStore(str(self.tmp / "jobs.sqlite3"))
        self.profiles = {"sdxl-a": parse_profile(image_profile(profile_id="sdxl-a")),
                         "wan-t2v": parse_profile(video_profile(profile_id="wan-t2v"))}
        self.service = MediaJobService(self.store, self.profiles, SECRET)
        self.client = client_for(self.service)

    def submit(self, **body):
        return self.client.post("/internal/media/jobs", json={"profile_id": "sdxl-a", "prompt": PROMPT, **body},
                                headers=HEADERS)

    def test_submit_queues_a_job_for_the_installation_and_never_echoes_the_prompt(self):
        response = self.submit(width=1024, height=1024, steps=20)
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual((job["state"], job["profile_id"], job["asset_id"], job["error"]), ("queued", "sdxl-a", None, None))
        self.assertNotIn(PROMPT, response.text)
        self.assertNotIn("prompt", job)
        row = self.store.get(job["id"], OWNER)
        self.assertEqual((row["owner"], row["prompt"]), ("installation", PROMPT), "the gallery's owner (#2365)")
        self.assertEqual(json.loads(row["params"]), {"width": 1024, "height": 1024, "steps": 20})

    def test_an_owner_header_is_ignored(self):
        response = self.client.post("/internal/media/jobs", json={"profile_id": "sdxl-a", "prompt": PROMPT},
                                    headers={**HEADERS, "X-Verified-Owner": "someone-else"})
        self.assertEqual(response.status_code, 202)
        self.assertIsNone(self.store.get(response.json()["id"], "someone-else"))
        self.assertIsNotNone(self.store.get(response.json()["id"], OWNER))

    def test_secret_and_loopback_are_both_required_and_nothing_is_read_without_them(self):
        for headers in ({}, {"X-Internal-Media-Secret": ""}, {"X-Internal-Media-Secret": "s" * 39},
                        {"X-Internal-Media-Secret": SECRET + "x"}):
            with self.subTest(headers=headers):
                response = self.client.post("/internal/media/jobs", json={"profile_id": "sdxl-a", "prompt": PROMPT},
                                            headers=headers)
                self.assertEqual(response.status_code, 401)
        remote = client_for(self.service, loopback=lambda host: False)
        for method, path in (("post", "/internal/media/jobs"), ("get", "/internal/media/jobs/" + "a" * 32),
                             ("post", "/internal/media/jobs/" + "a" * 32 + "/cancel")):
            with self.subTest(method=method, path=path):
                kwargs = {"json": {"profile_id": "sdxl-a", "prompt": PROMPT}} if path.endswith("jobs") else {}
                self.assertEqual(getattr(remote, method)(path, headers=HEADERS, **kwargs).status_code, 401)
        for body in ({}, {"x": 1}, "not json"):  # authentication comes before the schema: 401, never 422
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/internal/media/jobs", json=body).status_code, 401)
        with self.store._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM image_jobs").fetchone()[0], 0)

    def test_the_real_loopback_check_refuses_the_test_client_host(self):
        # The default predicate is netguard.is_loopback; TestClient's host "testclient" is not loopback.
        app = FastAPI()
        app.include_router(build_media_job_router(lambda: self.service))
        response = TestClient(app).post("/internal/media/jobs", json={"profile_id": "sdxl-a", "prompt": PROMPT},
                                        headers=HEADERS)
        self.assertEqual(response.status_code, 401)

    def test_requests_the_executor_would_refuse_are_400_now(self):
        cases = [
            ({"profile_id": "not-enabled"}, "profile_not_enabled"),
            ({"width": 1000, "height": 1000}, "invalid_request"),
            ({"width": 1024}, "invalid_request"),
            ({"steps": 41}, "invalid_request"),
            ({"seed": -1}, "invalid_request"),
            ({"frames": 10}, "invalid_request"),
            ({"task": "image_to_image"}, "invalid_request"),
            ({"prompt": "x" * 501}, "invalid_request"),
            ({"input_asset_id": "abc"}, "invalid_request"),
        ]
        for change, code in cases:
            with self.subTest(change=change):
                response = self.submit(**change)
                self.assertEqual((response.status_code, response.json().get("detail")), (400, code), response.text)
        for body in ({"profile_id": "sdxl-a"}, {"prompt": PROMPT}, {"profile_id": "sdxl-a", "prompt": PROMPT, "x": 1},
                     {"profile_id": "sdxl-a", "prompt": PROMPT, "steps": "20"}, {"profile_id": "sdxl-a", "prompt": ""}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/internal/media/jobs", json=body, headers=HEADERS).status_code, 422)
        with self.store._db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM image_jobs").fetchone()[0], 0)

    def test_video_needs_its_switch_and_image_to_video_is_not_served(self):
        response = self.submit(profile_id="wan-t2v")
        self.assertEqual((response.status_code, response.json()["detail"]), (400, "video_not_enabled"))
        video = client_for(MediaJobService(self.store, self.profiles, SECRET, video_enabled=True))
        ok = video.post("/internal/media/jobs", json={"profile_id": "wan-t2v", "prompt": PROMPT, "task": "text_to_video"},
                        headers=HEADERS)
        self.assertEqual(ok.status_code, 202, ok.text)
        refused = video.post("/internal/media/jobs", headers=HEADERS, json={
            "profile_id": "wan-t2v", "prompt": PROMPT, "task": "image_to_video", "input_asset_id": "a" * 24})
        self.assertEqual((refused.status_code, refused.json()["detail"]), (400, "task_not_served"))

    def test_queue_and_active_limits_are_429_codes(self):
        for _ in range(3):
            self.assertEqual(self.submit().status_code, 202)
        response = self.submit()
        self.assertEqual((response.status_code, response.json()["detail"]), (429, "active_limit"))
        with patch.object(ImageJobStore, "submit", side_effect=__import__("app.image_job_store", fromlist=["x"])
                          .ImageJobError("image job queue full")):
            response = self.submit()
        self.assertEqual((response.status_code, response.json()["detail"]), (429, "queue_full"))

    def test_status_cancel_and_expiry_are_visible(self):
        job_id = self.submit().json()["id"]
        status = self.client.get(f"/internal/media/jobs/{job_id}", headers=HEADERS)
        self.assertEqual((status.status_code, status.json()["state"]), (200, "queued"))
        cancelled = self.client.post(f"/internal/media/jobs/{job_id}/cancel", headers=HEADERS)
        self.assertEqual((cancelled.json()["result"], cancelled.json()["job"]["state"]), ("cancelled", "cancelled"))
        self.assertEqual(self.client.post(f"/internal/media/jobs/{job_id}/cancel", headers=HEADERS).status_code, 404)
        stale = self.submit().json()["id"]
        with self.store._db() as db:
            db.execute("UPDATE image_jobs SET created=? WHERE id=?", (time.time() - QUEUED_MAX_AGE_S - 1, stale))
        expired = self.client.get(f"/internal/media/jobs/{stale}", headers=HEADERS).json()
        self.assertEqual((expired["state"], expired["error"]), ("expired", "expired_unclaimed"))
        for bad in ("A" * 32, "a" * 31, "../" + "a" * 29, "0" * 32):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.get(f"/internal/media/jobs/{bad}", headers=HEADERS).status_code, 404)

    def test_a_completed_job_points_at_its_gallery_asset_and_legacy_errors_are_codes(self):
        job_id = self.submit().json()["id"]
        claimed = self.store.claim_for(["sdxl-a"], INSTANCE)
        self.assertEqual(claimed["id"], job_id)
        self.assertTrue(self.store.begin_publish(job_id, INSTANCE))
        self.assertTrue(self.store.complete(job_id, INSTANCE, "asset_0123456789abcdef"))
        job = self.client.get(f"/internal/media/jobs/{job_id}", headers=HEADERS).json()
        self.assertEqual((job["state"], job["asset_id"], job["asset_url"]),
                         ("completed", "asset_0123456789abcdef", "/api/v1/media/asset_0123456789abcdef"))
        other = self.submit().json()["id"]
        with self.store._db() as db:
            db.execute("UPDATE image_jobs SET state='failed', error='interrupted by restart' WHERE id=?", (other,))
        self.assertEqual(self.client.get(f"/internal/media/jobs/{other}", headers=HEADERS).json()["error"],
                         "interrupted_by_restart")

    def test_an_image_source_must_be_a_completed_asset_of_the_installation(self):
        profiles = {"i2i": parse_profile(image_profile(profile_id="i2i", tasks=["image_to_image"]))}
        client = client_for(MediaJobService(self.store, profiles, SECRET))
        response = client.post("/internal/media/jobs", headers=HEADERS, json={
            "profile_id": "i2i", "prompt": PROMPT, "task": "image_to_image", "input_asset_id": "a" * 24})
        self.assertEqual((response.status_code, response.json()["detail"]), (400, "source_not_found"))

    def test_a_failing_work_area_is_503_and_nothing_is_written(self):
        broken = []

        def guard():
            if broken:
                raise ArtifactSinkUnavailable("media_work_area_not_private: group or others have access")
        guarded = MediaJobService(ImageJobStore(str(self.tmp / "jobs.sqlite3"), volume_guard=guard), self.profiles,
                                  SECRET)
        broken.append(True)  # the work area opened up after the worker started
        response = client_for(guarded).post("/internal/media/jobs", json={"profile_id": "sdxl-a", "prompt": PROMPT},
                                            headers=HEADERS)
        self.assertEqual((response.status_code, response.json()["detail"]), (503, "media_work_area_not_private"))
        self.assertNotIn("group", response.text, "only the code, never the explanation")

    def test_an_unconfigured_service_is_503_with_a_code_and_is_retried(self):
        calls = []

        def factory():
            calls.append(1)
            if len(calls) == 1:
                raise MediaJobsUnavailable("media_jobs_secret_invalid")
            return self.service
        client = client_for(cached_service(factory))
        first = client.get("/internal/media/jobs/" + "a" * 32, headers=HEADERS)
        self.assertEqual((first.status_code, first.json()["detail"]), (503, "media_jobs_secret_invalid"))
        self.assertEqual(client.get("/internal/media/jobs/" + "a" * 32, headers=HEADERS).status_code, 404)
        client.get("/internal/media/jobs/" + "a" * 32, headers=HEADERS)
        self.assertEqual(len(calls), 2, "built once it works, then kept")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "work" / "state").mkdir(parents=True)
        (self.tmp / "profiles").mkdir()
        os.chmod(self.tmp / "work", 0o700)
        patcher = patch("app.media_work_area.WorkAreaProbe.containing_filesystem", return_value=("ext4", False))
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.tmp / "profiles" / "sdxl-a.json").write_text(json.dumps(image_profile(profile_id="sdxl-a")))
        self.env = {"KALIV_MEDIA_INTERNAL_SECRET": SECRET, "KALIV_MEDIA_WORK_ROOT": str(self.tmp / "work"),
                    "KALIV_MEDIA_JOB_DB": str(self.tmp / "work" / "state" / "jobs.sqlite3"),
                    "KALIV_MEDIA_PROFILE_DIR": str(self.tmp / "profiles"), "KALIV_MEDIA_PROFILES_ENABLED": "sdxl-a",
                    "KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES": "1"}

    def test_a_complete_configuration_builds_and_is_the_executor_s_database(self):
        service = service_from_env(self.env)
        self.assertEqual(set(service.profiles), {"sdxl-a"})
        self.assertFalse(service.video_enabled)
        self.assertEqual(service.store.path, Path(self.env["KALIV_MEDIA_JOB_DB"]))

    def test_each_missing_or_unsafe_setting_is_a_code_and_creates_nothing(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        cases = [
            ({"KALIV_MEDIA_INTERNAL_SECRET": ""}, "media_jobs_secret_invalid"),
            ({"KALIV_MEDIA_INTERNAL_SECRET": "short"}, "media_jobs_secret_invalid"),
            ({"KALIV_MEDIA_INTERNAL_SECRET": "s" * 40 + "\n"}, "media_jobs_secret_invalid"),
            ({"KALIV_MEDIA_WORK_ROOT": ""}, "KALIV_MEDIA_WORK_ROOT is required"),
            ({"KALIV_MEDIA_JOB_DB": "jobs.sqlite3"}, "media_jobs_db_invalid"),
            ({"KALIV_MEDIA_JOB_DB": str(outside / "jobs.sqlite3")}, "media_jobs_db_not_in_work_area"),
            ({"KALIV_MEDIA_PROFILE_DIR": ""}, "media_jobs_profile_dir_invalid"),
            ({"KALIV_MEDIA_PROFILES_ENABLED": ""}, "media_jobs_no_enabled_profiles"),
            ({"KALIV_MEDIA_PROFILES_ENABLED": "nope"}, "media_jobs_profiles_invalid"),
            ({"KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES": "0"}, "media_jobs_profiles_invalid"),
        ]
        for change, code in cases:
            with self.subTest(change=change):
                with self.assertRaises(MediaJobsUnavailable) as caught:
                    service_from_env({**self.env, **change})
                self.assertEqual(str(caught.exception), code)
        os.chmod(self.tmp / "work", 0o755)
        with self.assertRaises(MediaJobsUnavailable) as caught:
            service_from_env(self.env)
        self.assertEqual(str(caught.exception), "media_work_area_not_private")
        self.assertFalse(Path(self.env["KALIV_MEDIA_JOB_DB"]).exists(), "no database was created")

    def test_the_worker_mounts_the_routes_only_with_the_switch(self):
        import subprocess
        # Behaviour, not route introspection. KALIV_WORKER_ALLOW_LAN=1 lets the test client past the
        # worker's own loopback middleware; mounted, the route still refuses it as not loopback
        # (401, so the route keeps its own check even on a LAN-exposed worker); not mounted, 404.
        probe = ("import app.main as m; from fastapi.testclient import TestClient; "
                 "print(TestClient(m.app).post('/internal/media/jobs', json={}).status_code)")
        for value, expected in (("1", "401"), ("0", "404"), ("true", "404"), (None, "404")):
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "worker"), "PYTHONDONTWRITEBYTECODE": "1",
                   "KALIV_WORKER_ALLOW_LAN": "1", "HOME": str(self.tmp), "KALIV_DATA_ROOT": str(self.tmp / "data")}
            if value is not None:
                env["KALIV_MEDIA_JOBS_API"] = value
            with self.subTest(value=value):
                result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                                        timeout=120, cwd=str(ROOT / "worker"))
                if result.returncode != 0 and "ModuleNotFoundError" in result.stderr:
                    self.skipTest(f"the worker's full dependencies are not installed here: {result.stderr[-200:]}")
                self.assertEqual(result.stdout.strip().splitlines()[-1], expected, result.stderr[-500:])


class EndToEndTests(unittest.TestCase):
    """Submit through the route; the executor claims the job by its profile (no owner involved)."""

    def test_a_submitted_job_is_claimed_by_the_executor_protocol(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        store = ImageJobStore(str(tmp / "jobs.sqlite3"))
        client = client_for(MediaJobService(store, {"sdxl-a": parse_profile(image_profile(profile_id="sdxl-a"))},
                                            SECRET))
        job_id = client.post("/internal/media/jobs", json={"profile_id": "sdxl-a", "prompt": PROMPT, "steps": 20},
                             headers=HEADERS).json()["id"]
        claimed = store.claim_for(["sdxl-a"], INSTANCE)
        self.assertEqual((claimed["id"], claimed["prompt"], claimed["owner"]), (job_id, PROMPT, "installation"))
        # The executor turns the row into the same request the route validated.
        from app.media_executor import MediaExecutor
        request = MediaExecutor._request(None, claimed, parse_profile(image_profile(profile_id="sdxl-a")))
        self.assertEqual((request.width, request.height, request.steps), (1024, 1024, 20))


if __name__ == "__main__":
    unittest.main()
