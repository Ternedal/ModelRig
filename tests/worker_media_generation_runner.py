"""Profile-driven job runner with a fake sink and fake adapters (ModelRig #2296).

Ported from worker/tests/test_image_job_runner.py on the image branch. The
runner now hands bytes to an ArtifactSink (ChatGPT's media store implements
it); these tests use an in-memory sink, so nothing is written to disk except
the temporary job database.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worker_media_generation_profiles import image_profile  # noqa: E402

from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable, RenderedArtifact  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_generation_runner import GenerationJobRunner  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nfixture"


class MemorySink:
    def __init__(self, fail=False):
        self.items, self.fail = [], fail

    def publish(self, data, extension):
        if self.fail:
            raise ArtifactSinkUnavailable("external drive disappeared")
        self.items.append((data, extension))
        return f"asset{len(self.items):03d}"


class FakeAdapter:
    def __init__(self, profile_id, render):
        self.profile_id, self._render, self.requests = profile_id, render, []

    def load(self):
        pass

    def render(self, request):
        self.requests.append(request)
        return self._render(request)

    def close(self):
        pass


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jobs = ImageJobStore(str(Path(self.tmp.name) / "jobs.sqlite3"))
        self.profile = parse_profile(image_profile())
        self.profiles = {"sdxl-base": self.profile}

    def runner(self, render, sink=None):
        adapter = FakeAdapter("sdxl-base", render)
        return GenerationJobRunner(self.jobs, sink or MemorySink(), self.profiles, {"sdxl-base": adapter}), adapter

    def submit(self, prompt="blue elephant", profile_id="sdxl-base", **params):
        return self.jobs.submit("client-a", prompt, profile_id=profile_id, params=params or None)["job_id"]

    def state(self, job_id):
        return self.jobs.get(job_id, "client-a")

    def test_successful_render_is_published_and_completed(self):
        job_id = self.submit(width=832, height=1216, steps=20, seed=7)
        sink = MemorySink()
        runner, adapter = self.runner(lambda r: RenderedArtifact(PNG + r.prompt.encode(), "image/png"), sink)
        result = runner.run_one()
        self.assertEqual(result, {"job_id": job_id, "state": "completed", "asset_id": "asset001"})
        self.assertEqual(sink.items, [(PNG + b"blue elephant", ".png")])
        self.assertEqual(self.state(job_id)["state"], "completed")
        request = adapter.requests[0]
        self.assertEqual((request.width, request.height, request.steps, request.seed), (832, 1216, 20, 7))
        self.assertIsNone(runner.run_one())

    def test_profile_defaults_are_applied(self):
        self.submit()
        runner, adapter = self.runner(lambda r: RenderedArtifact(PNG, "image/png"))
        runner.run_one()
        request = adapter.requests[0]
        self.assertEqual((request.task, request.width, request.height, request.steps), ("text_to_image", 1024, 1024, 30))

    def test_renderer_failure_stores_no_prompt_or_detail(self):
        job_id = self.submit(prompt="secret prompt text")
        def broken(_request):
            raise RuntimeError("CUDA OOM while rendering 'secret prompt text' from C:\\models")
        result = self.runner(broken)[0].run_one()
        self.assertEqual(result["state"], "failed")
        stored = self.state(job_id)
        self.assertEqual(stored["error"], "image_generation_failed")
        self.assertNotIn("secret", json.dumps(stored["error"]))

    def test_wrong_return_type_or_undeclared_mime_fails_the_job(self):
        for render in (lambda _r: None, lambda _r: b"raw bytes", lambda _r: RenderedArtifact(b"mp4", "video/mp4")):
            job_id = self.submit()
            sink = MemorySink()
            result = self.runner(render, sink)[0].run_one()
            with self.subTest(render=render):
                self.assertEqual(result["state"], "failed")
                self.assertEqual(self.state(job_id)["error"], "image_generation_failed")
                self.assertEqual(sink.items, [])

    def test_sink_loss_stops_the_runner_and_leaves_the_job_for_recovery(self):
        job_id = self.submit()
        runner, _ = self.runner(lambda r: RenderedArtifact(PNG, "image/png"), MemorySink(fail=True))
        with self.assertRaises(ArtifactSinkUnavailable):
            runner.run_one()
        self.assertEqual(self.state(job_id)["state"], "running")
        self.assertEqual(self.jobs.recover_interrupted(), 1)
        self.assertEqual(self.state(job_id)["state"], "failed")

    def test_a_sink_returning_no_id_is_treated_as_unavailable(self):
        class NoId(MemorySink):
            def publish(self, data, extension):
                return ""
        self.submit()
        runner, _ = self.runner(lambda r: RenderedArtifact(PNG, "image/png"), NoId())
        with self.assertRaises(ArtifactSinkUnavailable):
            runner.run_one()

    def test_job_for_a_profile_this_executor_does_not_run_is_refused(self):
        job_id = self.submit(profile_id="flux-dev")
        runner, adapter = self.runner(lambda r: RenderedArtifact(PNG, "image/png"))
        self.assertEqual(runner.run_one()["error"], "image_profile_unavailable")
        self.assertEqual(self.state(job_id)["state"], "failed")
        self.assertEqual(adapter.requests, [])

    def test_request_outside_the_profile_limits_is_rejected_before_rendering(self):
        for params in ({"steps": 41}, {"width": 512, "height": 512}, {"task": "image_to_image"}, {"guidance": 7}):
            job_id = self.submit(**params)
            runner, adapter = self.runner(lambda r: RenderedArtifact(PNG, "image/png"))
            with self.subTest(params=params):
                self.assertEqual(runner.run_one()["error"], "image_request_rejected")
                self.assertEqual(self.state(job_id)["state"], "failed")
                self.assertEqual(adapter.requests, [])

    def test_construction_is_strict(self):
        with self.assertRaises(TypeError):
            GenerationJobRunner(self.jobs, object(), self.profiles, {})
        with self.assertRaises(ValueError):
            GenerationJobRunner(self.jobs, MemorySink(), {}, {"sdxl-base": FakeAdapter("sdxl-base", None)})


if __name__ == "__main__":
    unittest.main()
