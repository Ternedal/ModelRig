#!/usr/bin/env python3
"""ComfyUI video adapter + pinned workflow templates (ModelRig #2296 slice 2).

Template tests are pure. Adapter tests drive the fake ComfyUI as a real child
through the real supervisor. No GPU, no ComfyUI install, loopback only.

Run: PYTHONPATH=worker python3 tests/worker_comfy_video_adapter.py
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))

from app.comfy_supervisor import ComfyLaunch  # noqa: E402
from app.comfy_video_adapter import ComfyVideoAdapter  # noqa: E402
from app.comfy_workflow_template import load_template  # noqa: E402
from app.gpu_lease import GpuBusy, acquire_gpu_lease  # noqa: E402
from app.media_generation_contract import GenerationError, GenerationRequest  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from worker_comfy_supervisor import AnyExistingDirectory, FAKE_MAIN, GPU, FakeSupervisor, free_port, wait_gone  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable  # noqa: E402
from worker_media_generation_profiles import video_profile  # noqa: E402

GRAPH = {
    "3": {"class_type": "KSampler", "inputs": {"seed": "__KALIV_VIDEO_SEED__", "steps": "__KALIV_VIDEO_STEPS__",
                                               "model": ["4", 0], "cfg": 5.0}},
    "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_t2v_example.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "__KALIV_VIDEO_PROMPT__"},
          "_meta": {"title": "Positive"}},
    "7": {"class_type": "EmptyHunyuanLatentVideo",
          "inputs": {"width": "__KALIV_VIDEO_WIDTH__", "height": "__KALIV_VIDEO_HEIGHT__",
                     "length": "__KALIV_VIDEO_FRAMES__"}},
    "9": {"class_type": "CreateVideo", "inputs": {"fps": "__KALIV_VIDEO_FPS__"}},
}


def raw(graph=None) -> bytes:
    return json.dumps(GRAPH if graph is None else graph).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request(**overrides) -> GenerationRequest:
    values = dict(profile_id="wan-t2v", task="text_to_video", prompt="a red kite over Nørrebro",
                  width=832, height=480, steps=20, frames=33, seed=7)
    values.update(overrides)
    return GenerationRequest(**values)


class TemplateTests(unittest.TestCase):
    def test_binds_values_into_a_fresh_graph(self):
        template = load_template(raw(), sha(raw()))
        bound = template.bind(request(), fps=16)
        self.assertEqual(bound["6"]["inputs"]["text"], "a red kite over Nørrebro")
        self.assertEqual((bound["7"]["inputs"]["width"], bound["7"]["inputs"]["height"]), (832, 480))
        self.assertEqual(bound["7"]["inputs"]["length"], 33)
        self.assertEqual(bound["9"]["inputs"]["fps"], 16)
        self.assertEqual((bound["3"]["inputs"]["seed"], bound["3"]["inputs"]["steps"]), (7, 20))
        self.assertEqual(bound["4"]["inputs"]["unet_name"], "wan2.2_t2v_example.safetensors", "structure untouched")
        self.assertEqual(template.graph["6"]["inputs"]["text"], "__KALIV_VIDEO_PROMPT__", "template not mutated")

    def test_random_seed_when_none(self):
        template = load_template(raw(), sha(raw()))
        seeds = {template.bind(request(seed=None), fps=16)["3"]["inputs"]["seed"] for _ in range(8)}
        self.assertTrue(all(type(s) is int and 0 <= s < 2**32 for s in seeds))
        self.assertGreater(len(seeds), 1)

    def test_a_prompt_cannot_inject_structure(self):
        evil = '", "class_type": "SaveImage'
        bound = load_template(raw(), sha(raw())).bind(request(prompt=evil), fps=16)
        self.assertEqual(bound["6"]["inputs"]["text"], evil)
        self.assertEqual(set(bound), set(GRAPH))

    def test_refusals(self):
        def variant(mutate):
            graph = copy.deepcopy(GRAPH)
            mutate(graph)
            return raw(graph)

        cases = {
            "missing slot": variant(lambda g: g["9"]["inputs"].update(fps=16)),
            "duplicate slot": variant(lambda g: g["9"]["inputs"].update(frame_rate="__KALIV_VIDEO_FPS__")),
            "prompt moved into model name": variant(lambda g: (g["6"]["inputs"].update(text="fixed"),
                                                               g["4"]["inputs"].update(unet_name="__KALIV_VIDEO_PROMPT__"))),
            "marker inside a longer string": variant(lambda g: g["4"]["inputs"].update(
                unet_name="x__KALIV_VIDEO_PROMPT__")),
            "marker nested in a list": variant(lambda g: g["3"]["inputs"].update(model=["__KALIV_VIDEO_SEED__", 0])),
            "marker as input name": variant(lambda g: g["4"]["inputs"].update({"__KALIV_VIDEO_X__": 1})),
            "marker as class": variant(lambda g: g["4"].update(class_type="__KALIV_VIDEO_PROMPT__")),
            "marker in _meta": variant(lambda g: g["6"].update(_meta={"title": "__KALIV_VIDEO_PROMPT__"})),
            "unknown marker": variant(lambda g: g["4"]["inputs"].update(unet_name="__KALIV_VIDEO_MODEL__")),
            "non-decimal node id": variant(lambda g: g.update({"x": {"class_type": "A", "inputs": {}}})),
            "extra node key": variant(lambda g: g["4"].update(is_changed=True)),
            "no class_type": variant(lambda g: g["4"].pop("class_type")),
            "inputs not object": variant(lambda g: g["4"].update(inputs=[])),
        }
        for label, data in cases.items():
            with self.subTest(label), self.assertRaises(GenerationError):
                load_template(data, sha(data))
        for label, data, pin in (("sha mismatch", raw(), sha(b"other")), ("short sha", raw(), "ab" * 31),
                                 ("upper sha", raw(), sha(raw()).upper()), ("empty", b"", sha(b"")),
                                 ("too big", b" " * (1024 * 1024 + 1), sha(b" " * (1024 * 1024 + 1))),
                                 ("not json", b"{", sha(b"{")), ("list", b"[]", sha(b"[]")),
                                 ("empty graph", b"{}", sha(b"{}"))):
            with self.subTest(label), self.assertRaises(GenerationError):
                load_template(data, pin)

    def test_bind_refuses_unvalidated_or_other_tasks(self):
        template = load_template(raw(), sha(raw()))
        with self.assertRaises(GenerationError):
            template.bind(request(task="image_to_video"), fps=16)
        with self.assertRaises(GenerationError):
            template.bind(request(width=None, height=None), fps=16)


@unittest.skipIf(os.name == "nt", "fake ComfyUI uses POSIX process semantics")
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lease_dir = tempfile.mkdtemp(dir=self.tmp)
        os.chmod(self.lease_dir, 0o700)
        self.state = tempfile.mkdtemp(dir=self.tmp)
        self.templates = tempfile.mkdtemp(dir=self.tmp)
        Path(self.templates, "wan-t2v.json").write_bytes(raw())
        self.dirs = {name: os.path.join(self.tmp, name) for name in ("input", "output", "temp", "user")}
        for path in self.dirs.values():
            os.mkdir(path)
        self.port = free_port()
        self.adapters: list[ComfyVideoAdapter] = []

    def tearDown(self):
        for adapter in self.adapters:
            adapter.close()
        pid = Path(self.state, "pid")
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), 9)
            except (ProcessLookupError, ValueError):
                pass

    def profile(self, **options):
        values = {"template_name": "wan-t2v.json", "template_sha256": sha(raw()), "fps": 16,
                  "max_render_seconds": 60, "max_output_bytes": 1024 * 1024, "port": self.port}
        values.update(options)
        return parse_profile(video_profile(tasks=["text_to_video"], backend_options=values,
                                           limits={"max_prompt_chars": 200, "sizes": [[832, 480]],
                                                   "max_steps": 30, "max_frames": 81}))

    def adapter(self, fake=None, profile=None, volume=None, **kwargs) -> ComfyVideoAdapter:
        launch = ComfyLaunch(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                             input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                             temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
        env = {"FAKE_COMFY_STATE_DIR": self.state, **(fake or {})}
        sup = FakeSupervisor(fake_env=env, media_volume=volume, gpu_uuid=GPU, lease_dir=self.lease_dir, launch=launch,
                             reserve_gib=2, min_usable_gib=8, ready_timeout_s=15, stop_timeout_s=5, poll_s=0.05,
                             base_env={"PATH": os.environ.get("PATH", "")})
        values = dict(supervisor=sup, template_dir=self.templates, output_directory=self.dirs["output"], poll_s=0.05,
                      settle_s=0.05)
        values.update(kwargs)
        adapter = ComfyVideoAdapter(profile or self.profile(), **values)
        self.adapters.append(adapter)
        return adapter

    def lease_is_free(self) -> bool:
        try:
            acquire_gpu_lease(GPU, lease_dir=self.lease_dir).release()
            return True
        except GpuBusy:
            return False

    def test_end_to_end_text_to_video(self):
        adapter = self.adapter()
        adapter.load()
        self.assertFalse(self.lease_is_free())
        sink = io.BytesIO()
        self.assertEqual(adapter.render_to(request(), sink), "video/mp4")
        self.assertEqual(sink.getvalue()[4:8], b"ftyp")
        self.assertEqual(os.listdir(self.dirs["output"]), [], "ComfyUI's copy is removed after the hand-off")
        sent = json.loads(Path(self.state, "last_prompt.json").read_text())["prompt"]
        self.assertEqual(sent["6"]["inputs"]["text"], "a red kite over Nørrebro")
        self.assertEqual(sent["7"]["inputs"]["length"], 33)
        self.assertEqual(sent["9"]["inputs"]["fps"], 16)
        # a second job on the same resident ComfyUI
        self.assertEqual(adapter.render_to(request(seed=8), io.BytesIO()), "video/mp4")
        adapter.close()
        self.assertTrue(self.lease_is_free())

    def test_end_to_end_into_a_staged_sink(self):
        """The #2296 seam: with sink.staged(".mp4") as out: mime = render_to(req, out); sink.adopt(out, mime)."""
        from worker_staged_sink_conformance import ReferenceSink
        sink = ReferenceSink(tempfile.mkdtemp(dir=self.tmp), max_bytes=1024 * 1024)
        adapter = self.adapter()
        adapter.load()
        with sink.staged(".mp4") as output:
            mime = adapter.render_to(request(), output)
            asset_id = sink.adopt(output, mime)
        self.assertEqual(sink.registry, {asset_id})
        self.assertEqual(Path(sink.store, f"{asset_id}.mp4").read_bytes()[4:8], b"ftyp")
        self.assertEqual(os.listdir(sink.staging), [])
        # a refused output never reaches adopt(): nothing is published, staging is clean
        adapter.close()
        self.port = free_port()
        bad = self.adapter(fake={"FAKE_COMFY_OUTPUT_MODE": "notmp4"})
        bad.load()
        with self.assertRaises(GenerationError):
            with sink.staged(".mp4") as output:
                sink.adopt(output, bad.render_to(request(), output))
        self.assertEqual(sink.registry, {asset_id})
        self.assertEqual(os.listdir(sink.staging), [])

    # --- #2316 review 5700997784 --------------------------------------------------------------
    def submissions(self) -> int:
        log = Path(self.state, "prompts.log")
        return len(log.read_text().splitlines()) if log.exists() else 0

    def test_a_concurrent_second_job_is_refused_and_never_submitted(self):
        import threading
        adapter = self.adapter(fake={"FAKE_COMFY_RENDER_SECONDS": "1.0"})
        adapter.load()
        barrier, results = threading.Barrier(2), []

        def job():
            barrier.wait()
            try:
                results.append(("ok", adapter.render_to(request(), io.BytesIO())))
            except GenerationError as exc:
                results.append(("refused", str(exc)))

        threads = [threading.Thread(target=job) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(sorted(kind for kind, _ in results), ["ok", "refused"], results)
        self.assertIn("busy", [msg for kind, msg in results if kind == "refused"][0])
        self.assertEqual(self.submissions(), 1, "the refused job never reached ComfyUI")
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4", "the slot is free again")
        self.assertEqual(self.submissions(), 2)

    def test_two_adapters_on_one_comfyui_share_the_single_job_slot(self):
        first = self.adapter(fake={"FAKE_COMFY_RENDER_SECONDS": "1.0"})
        first.load()
        second = ComfyVideoAdapter(self.profile(), supervisor=first.supervisor, template_dir=self.templates,
                                   output_directory=self.dirs["output"], poll_s=0.05, settle_s=0.05)
        second._template = first._template  # same resident ComfyUI, already loaded
        with first.supervisor.job_slot():  # the first adapter's job is in flight
            with self.assertRaisesRegex(GenerationError, "busy"):
                second.render_to(request(), io.BytesIO())
        self.assertEqual(self.submissions(), 0)

    def test_a_failing_job_releases_the_slot(self):
        adapter = self.adapter(fake={"FAKE_COMFY_OUTPUT_MODE": "notmp4"})
        adapter.load()
        with self.assertRaises(GenerationError):
            adapter.render_to(request(), io.BytesIO())
        with adapter.supervisor.job_slot():
            pass  # acquirable: the failed job did not leak it

    def test_comfyui_media_directories_must_be_on_the_verified_volume_before_start(self):
        for lost in ("input", "output", "temp", "user"):
            with self.subTest(lost=lost):
                volume = AnyExistingDirectory()
                volume.lost.add(self.dirs[lost])
                self.port = free_port()
                with self.assertRaises(ArtifactSinkUnavailable):
                    self.adapter(volume=volume).load()
                self.assertFalse(Path(self.state, "pid").exists(), "no ComfyUI on an unverified disk")
                self.assertTrue(self.lease_is_free())

    def test_losing_the_volume_before_submit_is_fatal_and_submits_nothing(self):
        volume = AnyExistingDirectory()
        adapter = self.adapter(volume=volume)
        adapter.load()
        volume.lost.add("*")  # unplugged, or replaced by another disk
        with self.assertRaises(ArtifactSinkUnavailable):
            adapter.render_to(request(), io.BytesIO())
        self.assertEqual(self.submissions(), 0)

    def test_losing_the_volume_during_the_render_hands_nothing_to_the_sink(self):
        volume = AnyExistingDirectory()
        adapter = self.adapter(volume=volume, fake={"FAKE_COMFY_RENDER_SECONDS": "0.5"})
        adapter.load()
        real_history = adapter.supervisor.history

        def history_then_unplug(prompt_id):
            record = real_history(prompt_id)
            if record is not None:
                volume.lost.add("*")  # the render finished, then the disk went away
            return record

        adapter.supervisor.history = history_then_unplug
        sink = io.BytesIO()
        with self.assertRaises(ArtifactSinkUnavailable):
            adapter.render_to(request(), sink)
        self.assertEqual(sink.getvalue(), b"")

    def test_production_supervisor_has_no_internal_disk_default(self):
        from app.comfy_supervisor import ComfyLaunch, ComfySupervisor, ComfySupervisorError
        launch = ComfyLaunch(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                             input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                             temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
        common = dict(gpu_uuid=GPU, lease_dir=self.lease_dir, launch=launch, reserve_gib=2, min_usable_gib=8)
        with self.assertRaises(TypeError):
            ComfySupervisor(**common)  # media_volume is required
        for bogus in (None, "/mnt/media", object()):
            with self.subTest(volume=bogus), self.assertRaises(ComfySupervisorError):
                ComfySupervisor(media_volume=bogus, **common)

    def test_template_problems_stop_load_before_comfyui_starts(self):
        link_dir = tempfile.mkdtemp(dir=self.tmp)
        os.symlink(os.path.join(self.templates, "wan-t2v.json"), os.path.join(link_dir, "wan-t2v.json"))
        cases = {
            "pin mismatch": dict(profile=self.profile(template_sha256=sha(b"x"))),
            "missing file": dict(profile=self.profile(template_name="absent.json")),
            "symlinked template": dict(template_dir=link_dir),
            "relative dir": dict(template_dir="templates"),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                with self.assertRaises(GenerationError):
                    self.adapter(**kwargs).load()
                self.assertFalse(Path(self.state, "pid").exists(), "ComfyUI must not start")
                self.assertTrue(self.lease_is_free())

    def test_constructor_refusals(self):
        with self.assertRaises(GenerationError):
            self.adapter(profile=self.profile(port=self.port + 1 if self.port < 65535 else 1024))
        with self.assertRaises(GenerationError):
            self.adapter(output_directory=self.dirs["temp"])
        image = parse_profile(video_profile(backend="diffusers", modality="image", tasks=["text_to_image"],
                                            outputs=["image/png"], pipeline="FluxPipeline", backend_options={},
                                            limits={"max_prompt_chars": 10, "sizes": [[64, 64]],
                                                    "max_steps": 1, "max_frames": None}))
        with self.assertRaises(GenerationError):
            self.adapter(profile=image)

    def test_requests_are_refused_before_submit(self):
        adapter = self.adapter()
        with self.assertRaises(GenerationError):
            adapter.render_to(request(), io.BytesIO())  # not loaded
        adapter.load()
        for bad in (request(task="image_to_video", input_asset_id="a1"), request(prompt="x" * 201),
                    request(width=1024, height=1024), request(frames=82), request(steps=31)):
            with self.subTest(bad=bad), self.assertRaises(GenerationError):
                adapter.render_to(bad, io.BytesIO())
        self.assertFalse(Path(self.state, "last_prompt.json").exists(), "nothing was submitted")
        with self.assertRaises(GenerationError):
            adapter.render(request())

    def test_foreign_job_in_queue_refuses_to_share(self):
        adapter = self.adapter(fake={"FAKE_COMFY_PREQUEUED": "1"})
        adapter.load()
        with self.assertRaisesRegex(GenerationError, "queue is not empty"):
            adapter.render_to(request(), io.BytesIO())
        self.assertFalse(Path(self.state, "last_prompt.json").exists())

    def test_bad_outputs_are_refused_and_nothing_reaches_the_sink(self):
        expected = {"none": "exactly one", "two": "exactly one", "symlink": "symlink", "notmp4": "not an MP4",
                    "subfolder": "output directory root", "traversal": "plain .mp4", "temp_only": "exactly one",
                    "error": "reported an error", "stale": "already existed"}
        for mode, message in expected.items():
            with self.subTest(mode=mode):
                self.port = free_port()
                adapter = self.adapter(fake={"FAKE_COMFY_OUTPUT_MODE": mode})
                adapter.options = dataclasses.replace(adapter.options, max_render_seconds=3)
                adapter.load()
                if mode == "stale":
                    Path(self.dirs["output"], "old.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 20)
                sink = io.BytesIO()
                with self.assertRaisesRegex(GenerationError, message):
                    adapter.render_to(request(), sink)
                self.assertEqual(sink.getvalue(), b"", "a refused output must not be handed to the sink")
                adapter.close()
                for name in os.listdir(self.dirs["output"]):
                    os.unlink(os.path.join(self.dirs["output"], name))

    def test_vram_is_rechecked_before_every_job(self):
        adapter = self.adapter()
        adapter.load()
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
        Path(self.state, "vram_free_gib").write_text("9")  # e.g. Ollama loaded a model meanwhile
        os.unlink(Path(self.state, "last_prompt.json"))
        with self.assertRaisesRegex(GenerationError, "ComfyUI unavailable"):
            adapter.render_to(request(), io.BytesIO())
        self.assertFalse(Path(self.state, "last_prompt.json").exists(), "nothing submitted on a failed budget")

    def test_output_still_being_written_is_refused(self):
        adapter = self.adapter(fake={"FAKE_COMFY_OUTPUT_MODE": "growing", "FAKE_COMFY_MP4_PAD": "200000"})
        adapter.load()
        with self.assertRaisesRegex(GenerationError, "still being written"):
            adapter.render_to(request(), io.BytesIO())

    def test_output_changed_during_the_copy_is_refused(self):
        """A writer that wakes up mid-copy: the after-copy fstat must notice."""
        adapter = self.adapter(fake={"FAKE_COMFY_MP4_PAD": "4000000"}, profile=self.profile(max_output_bytes=8 * 1024 ** 2))
        adapter.load()
        output = self.dirs["output"]

        class MeddlingSink(io.BytesIO):
            meddled = False

            def write(self, data):
                if not self.meddled:
                    self.meddled = True
                    name = [n for n in os.listdir(output) if n.endswith(".mp4")][0]
                    with open(os.path.join(output, name), "ab") as fh:
                        fh.write(b"late")
                return super().write(data)

        with self.assertRaisesRegex(GenerationError, "changed while it was copied"):
            adapter.render_to(request(), MeddlingSink())

    def test_size_cap(self):
        adapter = self.adapter(fake={"FAKE_COMFY_MP4_PAD": "4096"}, profile=self.profile(max_output_bytes=1024))
        adapter.load()
        sink = io.BytesIO()
        with self.assertRaisesRegex(GenerationError, "size cap"):
            adapter.render_to(request(), sink)
        self.assertEqual(sink.getvalue(), b"")

    def test_deadline_interrupts_the_render(self):
        adapter = self.adapter(fake={"FAKE_COMFY_RENDER_SECONDS": "30"})
        adapter.options = dataclasses.replace(adapter.options, max_render_seconds=1)
        adapter.load()
        with self.assertRaisesRegex(GenerationError, "deadline"):
            adapter.render_to(request(), io.BytesIO())
        # the fake marks an interrupted prompt as failed and empties its queue
        for _ in range(100):
            if adapter.supervisor.queue_is_empty():
                break
            import time
            time.sleep(0.05)
        self.assertTrue(adapter.supervisor.queue_is_empty(), "interrupt reached ComfyUI")

    def test_comfyui_dying_mid_job_is_a_generation_error(self):
        adapter = self.adapter(fake={"FAKE_COMFY_RENDER_SECONDS": "30"})
        adapter.load()
        pid = int(Path(self.state, "pid").read_text())
        import threading
        threading.Timer(0.3, os.kill, args=(pid, 9)).start()
        with self.assertRaisesRegex(GenerationError, "ComfyUI unavailable"):
            adapter.render_to(request(), io.BytesIO())
        self.assertTrue(wait_gone(pid, 5))


if __name__ == "__main__":
    unittest.main(verbosity=2)
