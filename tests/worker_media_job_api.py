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
EXECUTOR = "GPU-" + "0" * 8 + "-0000-0000-0000-" + "0" * 12 + ":" + "a" * 16  # a valid executor instance
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
        self.assertEqual(job["schema"], "kaliv-media-job/v1")
        self.assertNotIn(PROMPT, response.text)
        self.assertNotIn("prompt", job)
        row = self.store.get(job["id"], OWNER)
        self.assertEqual((row["owner"], row["prompt"]), ("installation", PROMPT), "the gallery's owner (#2365)")
        # The resolved task is stored with the parameters (20/11), so the executor never re-derives it.
        self.assertEqual(json.loads(row["params"]), {"width": 1024, "height": 1024, "steps": 20, "task": "text_to_image"})

    def test_recent_lists_the_newest_jobs_with_their_kind_and_nothing_private(self):
        # #2475: a client that died between the rig's answer and its own save finds its job here.
        self.assertEqual(self.client.get("/internal/media/jobs/recent", headers=HEADERS).json(),
                         {"schema": "kaliv-media-job-list/v1", "jobs": []})
        first = self.submit().json()["id"]
        time.sleep(0.01)
        with patch.object(self.service, "video_enabled", True):
            second = self.client.post("/internal/media/jobs", headers=HEADERS,
                                      json={"profile_id": "wan-t2v", "prompt": PROMPT, "task": "text_to_video"}).json()["id"]
        body = self.client.get("/internal/media/jobs/recent", headers=HEADERS).json()
        self.assertEqual([(j["id"], j["kind"], j["state"]) for j in body["jobs"]],
                         [(second, "video", "queued"), (first, "image", "queued")], "newest first, each with its kind")
        status = self.client.get(f"/internal/media/jobs/{first}", headers=HEADERS).json()
        self.assertEqual({k: v for k, v in body["jobs"][1].items() if k != "kind"},
                         {k: v for k, v in status.items() if k != "translated_prompt"},
                         "an entry is what status shows for that job without translated_prompt, plus kind")
        # #2481 review (P2): status may show the rendered prompt of the one job asked about; the
        # list must not hand out the rendered prompts of twenty.
        import sqlite3
        db = sqlite3.connect(str(self.tmp / "jobs.sqlite3"))
        db.execute("UPDATE image_jobs SET effective_prompt=? WHERE id=?", ("a translated secret prompt", first))
        db.commit(); db.close()
        self.assertEqual(self.client.get(f"/internal/media/jobs/{first}", headers=HEADERS).json()["translated_prompt"],
                         "a translated secret prompt", "status still shows it for that one job")
        listed = self.client.get("/internal/media/jobs/recent", headers=HEADERS)
        self.assertNotIn("translated secret prompt", listed.text)
        self.assertTrue(all("translated_prompt" not in entry for entry in listed.json()["jobs"]))
        body = listed.json()
        # An entry carries exactly the public status fields plus kind. Compared as a set of keys:
        # the earlier form searched the serialised JSON for "832" (the video profile's width), and
        # a random job id such as a83af38c1ec24c0d832da3608ba1bed2 or a timestamp can contain it -
        # the suite went red a few times in a hundred with nothing wrong (26 Nov 2026: #2323, #2499).
        public = {"schema", "id", "state", "profile_id", "asset_id", "asset_url", "error",
                  "cancel_requested", "created", "updated", "kind"}
        for entry in body["jobs"]:
            self.assertEqual(set(entry), public)
            self.assertFalse(any(isinstance(v, (dict, list)) for v in entry.values()),
                             "no nested value that could carry request parameters")
            self.assertNotIn(832, entry.values())
        # Free text that cannot occur in a hex id or a timestamp may still be searched for.
        raw = json.dumps(body)
        for private in (PROMPT, "params", "owner", "claimed", "sdxl-base"):
            self.assertNotIn(private, raw)
        # a job whose profile is no longer enabled is still listed; its kind is unknown
        del self.service.profiles["wan-t2v"]
        kinds = {j["id"]: j["kind"] for j in self.client.get("/internal/media/jobs/recent", headers=HEADERS).json()["jobs"]}
        self.assertEqual(kinds, {second: None, first: "image"})

    def test_recent_and_status_agree_on_a_job_that_expired_in_the_queue(self):
        # #2481 review (Codex P2): with no executor running nothing expires a stale queued job;
        # status did it on read and the list did not, so one job was "expired" and "queued" at once.
        stale = self.submit().json()["id"]
        import sqlite3
        db = sqlite3.connect(str(self.tmp / "jobs.sqlite3"))
        db.execute("UPDATE image_jobs SET created=created-? WHERE id=?", (QUEUED_MAX_AGE_S + 60, stale))
        db.commit(); db.close()
        fresh = self.submit().json()["id"]
        db = sqlite3.connect(str(self.tmp / "jobs.sqlite3"))
        db.execute("UPDATE image_jobs SET state='queued', error=NULL WHERE id=?", (stale,))  # as if never looked at
        db.commit(); db.close()
        listed = {j["id"]: j for j in self.client.get("/internal/media/jobs/recent", headers=HEADERS).json()["jobs"]}
        self.assertEqual(listed[stale]["state"], "expired", "the list expires it instead of calling it queued")
        self.assertEqual(listed[fresh]["state"], "queued", "a job inside its deadline is untouched")
        status = self.client.get(f"/internal/media/jobs/{stale}", headers=HEADERS).json()
        self.assertEqual((listed[stale]["state"], listed[stale]["error"]), (status["state"], status["error"]))

    def test_recent_is_bounded_owner_bound_and_behind_the_secret(self):
        from app.image_job_store import RECENT_MAX, ImageJobError
        from app.media_job_api import RECENT_LIMIT
        self.assertEqual(self.client.get("/internal/media/jobs/recent").status_code, 401)
        self.assertEqual(self.client.get("/internal/media/jobs/recent", headers={"X-Internal-Media-Secret": "x" * 40}).status_code, 401)
        other = self.store.submit("someone-else", PROMPT, profile_id="sdxl-a", params={})["job_id"]
        mine = self.submit().json()["id"]
        listed = [j["id"] for j in self.client.get("/internal/media/jobs/recent", headers=HEADERS).json()["jobs"]]
        self.assertEqual(listed, [mine], "another owner's job is never listed")
        self.assertNotIn(other, listed)
        self.assertLessEqual(RECENT_LIMIT, RECENT_MAX)
        for bad in (0, -1, RECENT_MAX + 1, True, "20", 2.0):
            with self.assertRaises(ImageJobError):
                self.store.recent_for(OWNER, bad)
        # the list never grows with the table
        import sqlite3
        db = sqlite3.connect(str(self.tmp / "jobs.sqlite3"))
        row = db.execute("SELECT * FROM image_jobs WHERE id=?", (mine,)).fetchone()
        names = [d[0] for d in db.execute("SELECT * FROM image_jobs LIMIT 1").description]
        for n in range(RECENT_LIMIT + 15):
            values = dict(zip(names, row))
            values.update(id=f"{n:032x}", state="completed", created=values["created"] + n + 1)
            db.execute(f"INSERT INTO image_jobs ({','.join(names)}) VALUES ({','.join('?' * len(names))})", list(values.values()))
        db.commit(); db.close()
        jobs = self.client.get("/internal/media/jobs/recent", headers=HEADERS).json()["jobs"]
        self.assertEqual(len(jobs), RECENT_LIMIT)
        self.assertEqual(jobs[0]["id"], f"{RECENT_LIMIT + 14:032x}", "the newest is first")
        # 'recent' is not read as a job id by the status route
        self.assertEqual(self.client.get("/internal/media/jobs/recent", headers=HEADERS).json()["schema"], "kaliv-media-job-list/v1")

    def test_profiles_are_filtered_versioned_and_do_not_expose_model_details(self):
        response = self.client.get("/internal/media/jobs/profiles", headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "schema": "kaliv-media-job/v1",
            "profiles": [{
                "profile_id": "sdxl-a", "modality": "image",
                "tasks": sorted(self.profiles["sdxl-a"].tasks),
                "sizes": [list(size) for size in self.profiles["sdxl-a"].limits.sizes],
                "max_steps": self.profiles["sdxl-a"].limits.max_steps,
                "max_prompt_chars": self.profiles["sdxl-a"].limits.max_prompt_chars,
            }],
        })
        for sensitive in ("model_id", "revision", "backend_options", "resources", "license", "secret"):
            self.assertNotIn(sensitive, response.text)
        video_service = MediaJobService(self.store, self.profiles, SECRET, video_enabled=True)
        enabled = client_for(video_service).get("/internal/media/jobs/profiles", headers=HEADERS)
        self.assertEqual(enabled.status_code, 200)
        self.assertEqual([p["profile_id"] for p in enabled.json()["profiles"]], ["sdxl-a", "wan-t2v"])
        # image_to_video is served since the owner-gated reader was wired (20/11): advertised as the
        # profile lists it.
        self.assertEqual(enabled.json()["profiles"][1]["tasks"], ["image_to_video", "text_to_video"])

    def test_profiles_never_advertise_a_prompt_longer_than_submit_accepts(self):
        from dataclasses import replace
        large = replace(self.profiles["sdxl-a"], limits=replace(self.profiles["sdxl-a"].limits,
                                                                 max_prompt_chars=6000))
        configured = MediaJobService(self.store, {"sdxl-a": large}, SECRET)
        response = client_for(configured).get("/internal/media/jobs/profiles", headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profiles"][0]["max_prompt_chars"], 4000)

    def test_profiles_require_secret_and_loopback_before_exposing_catalog(self):
        for headers in ({}, {"X-Internal-Media-Secret": "invalid"}):
            response = self.client.get("/internal/media/jobs/profiles", headers=headers)
            self.assertEqual(response.status_code, 401)
        remote = client_for(self.service, loopback=lambda host: False)
        self.assertEqual(remote.get("/internal/media/jobs/profiles", headers=HEADERS).status_code, 401)

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
            ({"task": "image_to_image"}, "task_not_served"),
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

    def test_video_needs_its_switch_and_image_to_video_needs_an_owned_source(self):
        response = self.submit(profile_id="wan-t2v")
        self.assertEqual((response.status_code, response.json()["detail"]), (400, "video_not_enabled"))
        video = client_for(MediaJobService(self.store, self.profiles, SECRET, video_enabled=True))
        ok = video.post("/internal/media/jobs", json={"profile_id": "wan-t2v", "prompt": PROMPT, "task": "text_to_video"},
                        headers=HEADERS)
        self.assertEqual(ok.status_code, 202, ok.text)
        # No task named and no source: the text task, never the alphabetical first (image_to_video).
        default = video.post("/internal/media/jobs", json={"profile_id": "wan-t2v", "prompt": PROMPT}, headers=HEADERS)
        self.assertEqual(default.status_code, 202, default.text)
        # image_to_video: the source must be a completed asset of THIS owner -- checked at submit.
        refused = video.post("/internal/media/jobs", headers=HEADERS, json={
            "profile_id": "wan-t2v", "prompt": PROMPT, "task": "image_to_video"})
        self.assertEqual((refused.status_code, refused.json()["detail"]), (400, "invalid_request"), "no source")
        refused = video.post("/internal/media/jobs", headers=HEADERS, json={
            "profile_id": "wan-t2v", "prompt": PROMPT, "task": "image_to_video", "input_asset_id": "a" * 24})
        self.assertEqual((refused.status_code, refused.json()["detail"]), (400, "source_not_found"), "unknown source")
        # Another owner's completed asset is not ours either.
        theirs = self.store.submit("someone-else", PROMPT, profile_id="sdxl-a")["job_id"]
        self.assertEqual(self.store.claim_for(["sdxl-a"], EXECUTOR)["id"], theirs)
        self.assertTrue(self.store.begin_publish(theirs, EXECUTOR))
        self.assertTrue(self.store.complete(theirs, EXECUTOR, "img_theirs"))
        refused = video.post("/internal/media/jobs", headers=HEADERS, json={
            "profile_id": "wan-t2v", "prompt": PROMPT, "task": "image_to_video", "input_asset_id": "img_theirs"})
        self.assertEqual((refused.status_code, refused.json()["detail"]), (400, "source_not_found"))
        # Our own completed asset: accepted, and a missing task defaults to image_to_video when a source is given.
        mine = self.store.submit(OWNER, PROMPT, profile_id="sdxl-a")["job_id"]
        self.assertEqual(self.store.claim_for(["sdxl-a"], EXECUTOR)["id"], mine)
        self.assertTrue(self.store.begin_publish(mine, EXECUTOR))
        self.assertTrue(self.store.complete(mine, EXECUTOR, "img_mine"))
        accepted = video.post("/internal/media/jobs", headers=HEADERS, json={
            "profile_id": "wan-t2v", "prompt": PROMPT, "input_asset_id": "img_mine"})
        self.assertEqual(accepted.status_code, 202, accepted.text)
        row = self.store.get(accepted.json()["id"], OWNER)
        params = json.loads(row["params"]) if isinstance(row.get("params"), str) else row["params"]
        self.assertEqual((params.get("task"), params.get("input_asset_id")), ("image_to_video", "img_mine"))

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

    def test_the_owner_sees_a_translated_prompt_but_never_the_original_or_the_parameters(self):
        job_id = self.submit().json()["id"]
        before = self.client.get(f"/internal/media/jobs/{job_id}", headers=HEADERS).json()
        self.assertIsNone(before["translated_prompt"], "nothing translated yet: null, not the original")
        self.assertNotIn("prompt", before)
        self.assertNotIn("params", before)
        claimed = self.store.claim_for(["sdxl-a"], INSTANCE)
        self.assertEqual(claimed["id"], job_id)
        self.assertTrue(self.store.record_effective_prompt(job_id, INSTANCE, "a red bicycle, translated"))
        after = self.client.get(f"/internal/media/jobs/{job_id}", headers=HEADERS).json()
        self.assertEqual(after["translated_prompt"], "a red bicycle, translated")
        self.assertNotIn("prompt", after)
        self.assertNotIn("effective_prompt", after, "the store's column name does not leak; the view names the field")

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
                 "c = TestClient(m.app); "
                 "print(c.post('/internal/media/jobs', json={}).status_code, c.get('/internal/media/assets').status_code)")
        # The gallery read routes (media_gallery_api) are mounted by the same switch.
        for value, expected in (("1", "401 401"), ("0", "404 404"), ("true", "404 404"), (None, "404 404")):
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
