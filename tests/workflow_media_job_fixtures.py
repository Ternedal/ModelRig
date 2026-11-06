"""The proposed kaliv-media-job/v1 fixtures must agree with the store, the OpenAPI sketch and themselves.

docs/contracts/kaliv-media-job-v1/fixtures.json is the shared example set for the route
(ChatGPT's) and the Android parser (Claude's, MediaJobFixturesTest reads the same file). This
test checks every exchange against the store's invariants, the public error codes and the paths
in openapi.json, so neither side can implement against a fixture that the other would refuse.

Run: PYTHONPATH=worker python3 tests/workflow_media_job_fixtures.py
"""
import json
import re
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))

from app import image_job_store  # noqa: E402
from workflow_media_job_contract import executor_errors  # noqa: E402

CONTRACT = ROOT / "docs/contracts/kaliv-media-job-v1"
FIXTURES = json.loads((CONTRACT / "fixtures.json").read_text(encoding="utf-8"))
OPENAPI = json.loads((CONTRACT / "openapi.json").read_text(encoding="utf-8"))
SCHEMA = "kaliv-media-job/v1"
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
PROFILE = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
FORBIDDEN = {"prompt", "params", "owner", "claimed_by", "cancel_requested"}
ACTIVE = {"queued", "running", "publishing"}


def utc(value):
    assert isinstance(value, str) and value.endswith("Z"), value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_job(job: dict) -> None:
    """The Kotlin parser's rules (MediaJobContract.parseJob), restated."""
    states = ACTIVE | set(image_job_store._FINISHED)
    assert SAFE_ID.fullmatch(job["id"]), job["id"]
    assert job["state"] in states, job["state"]
    assert PROFILE.fullmatch(job["profile_id"]), job["profile_id"]
    created, updated = utc(job["created_at"]), utc(job["updated_at"])
    assert updated >= created
    assert (job["expires_at"] is not None) == (job["state"] == "queued")
    if job["expires_at"] is not None:
        expires = utc(job["expires_at"])
        assert (expires - created).total_seconds() == image_job_store.QUEUED_MAX_AGE_S
    assert (job["asset_id"] is not None) == (job["state"] == "completed")
    if job["asset_id"] is not None:
        assert SAFE_ID.fullmatch(job["asset_id"])
    assert (job["error"] is not None) == (job["state"] in ("failed", "expired"))
    if job["state"] == "expired":
        assert job["error"] == image_job_store.EXPIRED_ERROR
    if job["error"] is not None:
        assert job["error"] in public_errors(), f"not a public code: {job['error']!r}"


def public_errors() -> set[str]:
    """What a route may send: codes only. Legacy sentences are mapped by public_error()."""
    stored = executor_errors() | {image_job_store.EXPIRED_ERROR, image_job_store.INTERRUPTED_BY_RESTART,
                                  image_job_store.INTERRUPTED_DURING_PUBLICATION}
    return {image_job_store.public_error(e) for e in stored}


def keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from keys(v)


def openapi_path(path: str) -> str | None:
    bare = path.split("?", 1)[0]
    for template in OPENAPI["paths"]:
        if re.fullmatch(re.sub(r"\{[^}]+\}", "[A-Za-z0-9_-]+", template), bare):
            return template
    return None


class MediaJobFixtureTests(unittest.TestCase):
    exchanges = FIXTURES["exchanges"]

    def test_header(self):
        self.assertEqual(FIXTURES["contract"], SCHEMA)
        self.assertIn("PROPOSED", FIXTURES["status"])
        names = [e["name"] for e in self.exchanges]
        self.assertEqual(len(names), len(set(names)))

    def test_every_job_body_obeys_the_store_invariants(self):
        seen = set()
        for e in self.exchanges:
            body = e["response"]["body"]
            jobs = [body["job"]] if "job" in body else body.get("jobs", [])
            for job in jobs:
                with self.subTest(e["name"]):
                    check_job(job)
                    seen.add(job["state"])
        self.assertEqual(seen, ACTIVE | set(image_job_store._FINISHED), "every state has an example")

    def test_no_private_field_is_ever_returned(self):
        for e in self.exchanges:
            with self.subTest(e["name"]):
                self.assertEqual(set(keys(e["response"]["body"])) & FORBIDDEN, set())

    def test_error_envelopes_use_the_documented_codes(self):
        documented = set(OPENAPI["components"]["schemas"]["Error"]["properties"]["error"]["enum"])
        for e in self.exchanges:
            body = e["response"]["body"]
            if e["response"]["status"] >= 400:
                with self.subTest(e["name"]):
                    self.assertEqual(body["schema"], SCHEMA)
                    self.assertIn(body["error"], documented)
                    self.assertNotIn("job", body)

    def test_cancel_outcomes_are_the_store_answers(self):
        source = Path(image_job_store.__file__).read_text(encoding="utf-8")
        body = re.search(r"def request_cancel\(.*?\n    def ", source, re.S).group(0)
        answers = set(re.findall(r'return "([a-z_]+)"', body))
        self.assertEqual(answers, set(OPENAPI["components"]["schemas"]["CancelResponse"]["properties"]["outcome"]["enum"]))
        for e in self.exchanges:
            if e["request"]["path"].endswith("/cancel") and e["response"]["status"] == 200:
                with self.subTest(e["name"]):
                    self.assertIn(e["response"]["body"]["outcome"], answers)

    def test_owner_isolation_and_races_have_examples(self):
        """ChatGPT 6694053328 P2: another owner's job, a cancel racing the executor, an expired job."""
        by_name = {e["name"]: e for e in self.exchanges}
        for name in ("get-other-owner", "cancel-other-owner"):
            self.assertEqual((by_name[name]["response"]["status"], by_name[name]["response"]["body"]["error"]),
                             (404, "not_found"))
        race = by_name["cancel-running-already-stopped"]["response"]["body"]
        self.assertEqual((race["outcome"], race["job"]["state"]), ("requested", "cancelled"))
        expired = by_name["cancel-expired"]["response"]["body"]
        self.assertEqual((expired["outcome"], expired["job"]["state"]), ("too_late", "expired"))
        self.assertIn("Retry-After", by_name["submit-queue-full"]["response"]["headers"])

    def test_submit_location_names_the_job(self):
        for e in self.exchanges:
            if e["response"]["status"] == 201:
                with self.subTest(e["name"]):
                    job = e["response"]["body"]["job"]
                    self.assertEqual(job["state"], "queued")
                    self.assertEqual(e["response"]["headers"]["Location"], f"/api/v1/media/jobs/{job['id']}")
                    self.assertIn("Idempotency-Key", e["request"]["headers"])

    def test_every_exchange_is_in_the_openapi_sketch(self):
        used = set()
        for e in self.exchanges:
            template = openapi_path(e["request"]["path"])
            with self.subTest(e["name"]):
                self.assertIsNotNone(template)
                self.assertIn(e["request"]["method"].lower(), OPENAPI["paths"][template])
                self.assertIn(str(e["response"]["status"]),
                              OPENAPI["paths"][template][e["request"]["method"].lower()]["responses"])
            used.add((template, e["request"]["method"].lower()))
        declared = {(p, m) for p, ops in OPENAPI["paths"].items() for m in ops}
        self.assertEqual(declared - used, set(), "every operation has an example")

    def test_android_knows_every_refusal_and_cancel_outcome(self):
        kotlin = (ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/MediaJobContract.kt").read_text(encoding="utf-8")
        def enum(name):
            body = re.search(rf"enum class {name}\b.*?\{{(.*?)\n\}}", kotlin, re.S).group(1)
            return set(re.findall(r'[A-Z_]+\("([a-z_]+)"\)', body))
        schemas = OPENAPI["components"]["schemas"]
        self.assertEqual(enum("MediaJobRefusal"), set(schemas["Error"]["properties"]["error"]["enum"]))
        self.assertEqual(enum("MediaCancelOutcome"), set(schemas["CancelResponse"]["properties"]["outcome"]["enum"]))

    def test_openapi_job_states_and_store_agree(self):
        states = OPENAPI["components"]["schemas"]["Job"]["properties"]["state"]["enum"]
        self.assertEqual(set(states), ACTIVE | set(image_job_store._FINISHED))

    def test_the_checker_refuses_broken_jobs(self):
        good = {"id": "j1", "state": "completed", "profile_id": "sdxl-base", "created_at": "2026-11-06T10:00:00Z",
                "updated_at": "2026-11-06T10:00:01Z", "expires_at": None, "asset_id": "a1", "error": None}
        check_job(good)
        for broken in ({"asset_id": None}, {"state": "running"}, {"error": "gpu_busy"},
                       {"state": "failed", "asset_id": None, "error": "interrupted by restart"},
                       {"state": "expired", "asset_id": None, "error": "gpu_busy"},
                       {"updated_at": "2026-11-06T09:00:00Z"}, {"created_at": "2026-11-06T10:00:00+01:00"}):
            with self.subTest(broken=broken), self.assertRaises((AssertionError, KeyError, ValueError)):
                check_job(dict(good, **broken))


if __name__ == "__main__":
    unittest.main()
