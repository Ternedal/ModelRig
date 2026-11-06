#!/usr/bin/env python3
"""ComfyUI video adapter + pinned workflow templates (ModelRig #2296 slice 2).

Template tests are pure. Adapter tests drive the fake ComfyUI as a real child
through the real supervisor. No GPU, no ComfyUI install, loopback only.

Run: PYTHONPATH=worker python3 tests/worker_comfy_video_adapter.py
"""
from __future__ import annotations

import copy
import dataclasses
import shutil
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
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
    def test_a_pinned_template_may_only_load_pinned_model_files(self):
        load_template(raw(), sha(raw()), pinned_files=["diffusion_models/wan2.2_t2v_example.safetensors"])
        with self.assertRaisesRegex(GenerationError, "not pinned"):
            load_template(raw(), sha(raw()), pinned_files=["diffusion_models/other.safetensors"])
        graph = copy.deepcopy(GRAPH)
        graph["5"] = {"class_type": "LoraLoader", "inputs": {"lora_name": "sub/extra.safetensors"}}
        with self.assertRaisesRegex(GenerationError, "not pinned"):
            load_template(raw(graph), sha(raw(graph)), pinned_files=["diffusion_models/wan2.2_t2v_example.safetensors"])
        # The value is the path inside the loader's folder: the basename alone is a different file.
        with self.assertRaisesRegex(GenerationError, "not pinned"):
            load_template(raw(graph), sha(raw(graph)),
                          pinned_files=["diffusion_models/wan2.2_t2v_example.safetensors", "loras/extra.safetensors"])
        load_template(raw(graph), sha(raw(graph)),
                      pinned_files=["diffusion_models/wan2.2_t2v_example.safetensors", "loras/sub/extra.safetensors"])
        load_template(raw(), sha(raw()))  # no pins: no binding (candidate profiles)

    def test_a_distinct_whitespace_named_file_cannot_satisfy_the_pin(self):
        # Codex's reproduction (4472405235), as ChatGPT asked: two REAL files with different bytes,
        # only the first pinned. The weights check passes (both files exist, the pinned one matches);
        # the template that names the second is refused before anything starts.
        from app.comfy_weights import verify_weights
        from app.media_generation_profiles import WeightPin
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp, "models", "diffusion_models")
            models.mkdir(parents=True)
            Path(models, "wan2.2_t2v_example.safetensors").write_bytes(b"pinned bytes")
            Path(models, " wan2.2_t2v_example.safetensors").write_bytes(b"never hashed")
            pin = WeightPin("diffusion_models/wan2.2_t2v_example.safetensors",
                            hashlib.sha256(b"pinned bytes").hexdigest(), len(b"pinned bytes"))
            verify_weights(Path(tmp, "models"), [pin], comfy_root=tmp)
            graph = copy.deepcopy(GRAPH)
            graph["4"]["inputs"]["unet_name"] = " wan2.2_t2v_example.safetensors"
            with self.assertRaisesRegex(GenerationError, "not pinned"):
                load_template(raw(graph), sha(raw(graph)), pinned_files=[pin.path])
            load_template(raw(), sha(raw()), pinned_files=[pin.path])  # the exact name is accepted

    def test_a_backslash_is_refused_because_it_means_different_files_per_platform(self):
        # #2328 review 4472675602: on POSIX "evil\\wan.safetensors" is one file name, not evil/ + wan.
        # (A value that does not END in a model extension is not a file ComfyUI lists, so it never loads.)
        for value in ("evil\\wan2.2_t2v_example.safetensors", "\\wan2.2_t2v_example.safetensors"):
            graph = copy.deepcopy(GRAPH)
            graph["4"]["inputs"]["unet_name"] = value
            with self.subTest(value=value), self.assertRaisesRegex(GenerationError, "not pinned"):
                load_template(raw(graph), sha(raw(graph)),
                              pinned_files=["diffusion_models/wan2.2_t2v_example.safetensors",
                                            "diffusion_models/evil/wan2.2_t2v_example.safetensors"])

    def test_embeddings_cannot_be_loaded_under_pins(self):
        # #2328 review 4472675615: "embedding:<name>" in any encoded text loads models/embeddings/<name>.
        pins = ["diffusion_models/wan2.2_t2v_example.safetensors"]
        graph = copy.deepcopy(GRAPH)
        graph["5"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, Embedding:badhands", "clip": ["8", 0]}}
        with self.assertRaisesRegex(GenerationError, "references an embedding"):
            load_template(raw(graph), sha(raw(graph)), pinned_files=pins)
        load_template(raw(graph), sha(raw(graph)))  # candidates are not pinned
        pinned = load_template(raw(), sha(raw()), pinned_files=pins)
        for prompt in ("a kite embedding:unpinned", "(EMBEDDING:x:1.2) a kite", "embedding:x"):
            with self.subTest(prompt=prompt), self.assertRaisesRegex(GenerationError, "embedding"):
                pinned.bind(request(prompt=prompt), fps=16)
        self.assertEqual(pinned.bind(request(prompt="an embedding of meaning"), fps=16)["6"]["inputs"]["text"],
                         "an embedding of meaning", "the word alone is fine")
        unpinned = load_template(raw(), sha(raw()))
        self.assertEqual(unpinned.bind(request(prompt="embedding:x"), fps=16)["6"]["inputs"]["text"], "embedding:x")

    def test_the_binding_is_keyed_on_the_value_not_the_input_name(self):
        # #2328 review 4472123690: DualCLIPLoader's clip_name1/clip_name2 do not end in "_name".
        base = ["diffusion_models/wan2.2_t2v_example.safetensors"]
        for inputs in ({"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl.safetensors", "type": "flux"},
                       # #2328 review 4472405235: a distinct POSIX file must not satisfy the pin by stripping
                       {"unet_name": " wan2.2_t2v_example.safetensors"},
                       {"unet_name": "wan2.2_t2v_example.safetensors "},
                       {"unet_name": "WAN2.2_T2V_EXAMPLE.safetensors"},
                       {"clip_name1": "CLIP_L.SAFETENSORS "},           # case and trailing space
                       {"model": "x\\nested\\upscaler.pt2"},           # any input name, Windows separators
                       {"files": ["a.txt", "lora.pkl"]}):               # inside a list
            graph = copy.deepcopy(GRAPH)
            graph["5"] = {"class_type": "DualCLIPLoader", "inputs": inputs}
            with self.subTest(inputs=inputs), self.assertRaisesRegex(GenerationError, "not pinned"):
                load_template(raw(graph), sha(raw(graph)), pinned_files=base)
        graph = copy.deepcopy(GRAPH)
        graph["5"] = {"class_type": "DualCLIPLoader",
                      "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl.safetensors", "type": "flux"}}
        load_template(raw(graph), sha(raw(graph)),
                      pinned_files=base + ["text_encoders/clip_l.safetensors", "text_encoders/t5xxl.safetensors"])

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

    def adapter(self, fake=None, profile=None, work_area=None, comfy_root=None, **kwargs) -> ComfyVideoAdapter:
        main_py = str(Path(comfy_root, "main.py")) if comfy_root else str(FAKE_MAIN)
        launch = ComfyLaunch(python_executable=sys.executable, main_py=main_py, port=self.port,
                             input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                             temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
        env = {"FAKE_COMFY_STATE_DIR": self.state, **(fake or {})}
        sup = FakeSupervisor(fake_env=env, work_area=work_area, gpu_uuid=GPU, lease_dir=self.lease_dir, launch=launch,
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

    def test_comfyui_directories_must_be_in_the_private_work_area_before_start(self):
        for lost in ("input", "output", "temp", "user"):
            with self.subTest(lost=lost):
                work_area = AnyExistingDirectory()
                work_area.lost.add(self.dirs[lost])
                self.port = free_port()
                with self.assertRaises(ArtifactSinkUnavailable):
                    self.adapter(work_area=work_area).load()
                self.assertFalse(Path(self.state, "pid").exists(), "no ComfyUI outside the verified work area")
                self.assertTrue(self.lease_is_free())

    def test_losing_the_work_area_before_submit_is_fatal_and_submits_nothing(self):
        work_area = AnyExistingDirectory()
        adapter = self.adapter(work_area=work_area)
        adapter.load()
        work_area.lost.add("*")  # replaced, or no longer private
        with self.assertRaises(ArtifactSinkUnavailable):
            adapter.render_to(request(), io.BytesIO())
        self.assertEqual(self.submissions(), 0)

    def test_losing_the_work_area_during_the_render_hands_nothing_to_the_sink(self):
        work_area = AnyExistingDirectory()
        adapter = self.adapter(work_area=work_area, fake={"FAKE_COMFY_RENDER_SECONDS": "0.5"})
        adapter.load()
        real_history = adapter.supervisor.history

        def history_then_unplug(prompt_id):
            record = real_history(prompt_id)
            if record is not None:
                work_area.lost.add("*")  # the render finished, then the work area failed its check
            return record

        adapter.supervisor.history = history_then_unplug
        sink = io.BytesIO()
        with self.assertRaises(ArtifactSinkUnavailable):
            adapter.render_to(request(), sink)
        self.assertEqual(sink.getvalue(), b"")

    # --- #2316 review 4415046066: failed jobs must not fill the work area-----------------------
    def test_rejected_outputs_do_not_accumulate(self):
        """Codex's scenario: three renders rejected by the size cap must leave nothing behind."""
        adapter = self.adapter(fake={"FAKE_COMFY_MP4_PAD": "4096"}, profile=self.profile(max_output_bytes=1024))
        adapter.load()
        for _ in range(3):
            with self.assertRaisesRegex(GenerationError, "size cap"):
                adapter.render_to(request(), io.BytesIO())
        self.assertEqual(os.listdir(self.dirs["output"]), [])

    def test_a_sink_write_error_still_cleans_up(self):
        class BrokenSink(io.BytesIO):
            def write(self, data):
                raise OSError("disk full on the sink side")

        adapter = self.adapter()
        adapter.load()
        with self.assertRaises(OSError):
            adapter.render_to(request(), BrokenSink())
        self.assertEqual(os.listdir(self.dirs["output"]), [])

    # --- Anders, 6 Nov (#2275 6686905826): the work-area copy goes only once the staged copy is durable ---
    def test_the_staged_copy_is_synced_before_the_work_area_copy_is_removed(self):
        from unittest.mock import patch
        adapter = self.adapter()
        adapter.load()
        events = []
        real_remove = adapter._remove_job_outputs

        def remove(*args):
            events.append(("remove", sorted(os.listdir(self.dirs["output"]))))
            return real_remove(*args)

        adapter._remove_job_outputs = remove
        real_fsync = os.fsync
        staged = Path(self.tmp, "staged.mp4")
        with open(staged, "wb") as sink, \
                patch("app.comfy_video_adapter.os.fsync",
                      side_effect=lambda fd: (events.append(("fsync", fd)), real_fsync(fd))[1]):
            self.assertEqual(adapter.render_to(request(), sink), "video/mp4")
            fileno = sink.fileno()
        self.assertEqual([e[0] for e in events], ["fsync", "remove"], "durable on the volume, then removed here")
        self.assertEqual(events[0][1], fileno, "the sink's own descriptor is synced")
        self.assertEqual(len(events[1][1]), 1, "the render's output was still there when the copy was synced")
        self.assertEqual(os.listdir(self.dirs["output"]), [])
        self.assertEqual(staged.read_bytes()[4:8], b"ftyp")

    def test_a_staged_handle_is_synced_through_its_own_sync_before_the_removal(self):
        """The staged sink's handle (#2347) has sync() and no fileno: that is what is called."""
        adapter = self.adapter()
        adapter.load()
        events = []
        real_remove = adapter._remove_job_outputs
        adapter._remove_job_outputs = lambda *a: (events.append("remove"), real_remove(*a))[1]

        class StagedHandle:
            def __init__(self):
                self.data = bytearray()

            def write(self, chunk):
                self.data += chunk
                return len(chunk)

            def flush(self):
                pass

            def sync(self):
                events.append(("sync", len(self.data)))

        handle = StagedHandle()
        self.assertEqual(adapter.render_to(request(), handle), "video/mp4")
        self.assertEqual(events, [("sync", len(handle.data)), "remove"], "the whole copy is synced, then removed")
        self.assertEqual(bytes(handle.data[4:8]), b"ftyp")

    def test_a_staged_handle_whose_sync_fails_fails_the_job(self):
        from app.media_generation_contract import ArtifactSinkUnavailable
        adapter = self.adapter()
        adapter.load()

        class FullDisk(io.BytesIO):
            def sync(self):
                raise ArtifactSinkUnavailable("staged_video_unavailable")

        with self.assertRaises(ArtifactSinkUnavailable):
            adapter.render_to(request(), FullDisk())
        self.assertEqual(os.listdir(self.dirs["output"]), [], "a failed job's output is cleaned up, as for any failure")

    def test_holding_keeps_the_copy_until_the_block_ends_then_removes_it(self):
        adapter = self.adapter()
        adapter.load()
        with adapter.holding_outputs():
            self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
            self.assertEqual(len(os.listdir(self.dirs["output"])), 1, "still on C: until published")
        self.assertEqual(os.listdir(self.dirs["output"]), [])
        self.assertIsNone(adapter._holding)

    def test_a_failure_after_the_hand_over_keeps_the_copy_for_recovery(self):
        from app.media_generation_contract import ArtifactSinkUnavailable
        adapter = self.adapter()
        adapter.load()
        with self.assertLogs("kaliv.media.comfy", level="WARNING"), self.assertRaises(ArtifactSinkUnavailable):
            with adapter.holding_outputs():
                adapter.render_to(request(), io.BytesIO())
                raise ArtifactSinkUnavailable("publication failed")
        kept = os.listdir(self.dirs["output"])
        self.assertEqual(len(kept), 1)
        self.assertEqual(adapter.last_cleanup["kept_for_recovery"], kept)

    def test_a_cancel_after_the_hand_over_removes_the_copy(self):
        from app.media_generation_contract import GenerationCancelled
        adapter = self.adapter()
        adapter.load()
        with self.assertRaises(GenerationCancelled):
            with adapter.holding_outputs():
                adapter.render_to(request(), io.BytesIO())
                raise GenerationCancelled("the owner cancelled before publication")
        self.assertEqual(os.listdir(self.dirs["output"]), [])

    def test_a_render_that_fails_inside_the_hold_is_cleaned_at_once(self):
        adapter = self.adapter(fake={"FAKE_COMFY_OUTPUT_MODE": "notmp4"})
        adapter.load()
        with self.assertRaises(GenerationError), adapter.holding_outputs():
            try:
                adapter.render_to(request(), io.BytesIO())
            finally:
                self.assertEqual(os.listdir(self.dirs["output"]), [], "removed before the hold even ends")
        self.assertNotIn("kept_for_recovery", adapter.last_cleanup)

    def test_the_holder_gets_a_receipt_before_the_copy_and_one_after_the_sync(self):
        adapter = self.adapter()
        adapter.load()
        sink = io.BytesIO()
        receipts = []

        def record(receipt):
            receipts.append((receipt, len(sink.getvalue())))
        with adapter.holding_outputs(on_handoff=record):
            adapter.render_to(request(), sink)
            name = os.listdir(self.dirs["output"])[0]
            info = os.stat(Path(self.dirs["output"], name))
        output = {"name": name, "dev": info.st_dev, "ino": info.st_ino, "size": info.st_size}
        self.assertEqual(receipts[0], ({"stage": "copying", "output": output}, 0), "before a byte reached the sink")
        copied, written = receipts[1]
        self.assertEqual(copied, {"stage": "copied", "output": output, "sha256": hashlib.sha256(sink.getvalue()).hexdigest(),
                                  "size": len(sink.getvalue())})
        self.assertEqual(written, len(sink.getvalue()))
        self.assertEqual(len(receipts), 2)

    def test_an_unrecorded_hand_off_fails_before_anything_is_copied(self):
        adapter = self.adapter()
        adapter.load()
        sink = io.BytesIO()

        def refuse(receipt):
            raise GenerationError("the hand-off could not be recorded for this job")
        with self.assertRaises(GenerationError), adapter.holding_outputs(on_handoff=refuse):
            adapter.render_to(request(), sink)
        self.assertEqual(sink.getvalue(), b"", "nothing reached the volume")
        self.assertEqual(os.listdir(self.dirs["output"]), [], "a job that never handed over is cleaned at once")

    def test_receipts_go_only_to_the_current_holder(self):
        adapter = self.adapter()
        adapter.load()
        receipts = []
        with adapter.holding_outputs(on_handoff=receipts.append):
            adapter.render_to(request(), io.BytesIO())
        adapter.render_to(request(), io.BytesIO())  # no holder: no receipts, as before
        self.assertEqual([r["stage"] for r in receipts], ["copying", "copied"])

    def test_holding_does_not_nest(self):
        adapter = self.adapter()
        with adapter.holding_outputs():
            with self.assertRaises(RuntimeError):
                with adapter.holding_outputs():
                    pass

    def test_a_sync_failure_is_a_failed_job_never_a_silent_success(self):
        import errno
        from unittest.mock import patch
        adapter = self.adapter()
        adapter.load()
        with open(Path(self.tmp, "staged.mp4"), "wb") as sink, \
                patch("app.comfy_video_adapter.os.fsync", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            with self.assertRaises(OSError) as caught:
                adapter.render_to(request(), sink)
        self.assertEqual(caught.exception.errno, errno.ENOSPC)
        self.assertEqual(os.listdir(self.dirs["output"]), [], "the failed job's output is cleaned up, as for any failure")
        self.assertEqual(adapter.last_cleanup["failed"], [])

    def test_cleanup_never_touches_what_existed_before_the_job(self):
        Path(self.dirs["output"], "operator-note.txt").write_text("keep me")
        os.mkdir(os.path.join(self.dirs["output"], "keep-dir"))
        adapter = self.adapter()
        adapter.load()
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
        self.assertEqual(sorted(os.listdir(self.dirs["output"])), ["keep-dir", "operator-note.txt"])

    def test_cleanup_touches_nothing_when_the_work_area_is_no_longer_verified(self):
        work_area = AnyExistingDirectory()
        adapter = self.adapter(work_area=work_area, fake={"FAKE_COMFY_RENDER_SECONDS": "0.3"})
        adapter.load()
        real_history = adapter.supervisor.history

        def history_then_unplug(prompt_id):
            record = real_history(prompt_id)
            if record is not None:
                work_area.lost.add("*")
            return record

        adapter.supervisor.history = history_then_unplug
        with self.assertRaises(ArtifactSinkUnavailable):
            adapter.render_to(request(), io.BytesIO())
        self.assertEqual(len([n for n in os.listdir(self.dirs["output"]) if n.endswith(".mp4")]), 1,
                         "on an unverified (possibly replaced) disk, nothing is deleted")

    # --- #2316 review 5702562074: only provably job-owned files go -------------------------------
    def test_a_foreign_file_created_mid_job_is_kept_and_reported(self):
        adapter = self.adapter(fake={"FAKE_COMFY_FOREIGN_FILE": "someone-elses.mp4", "FAKE_COMFY_RENDER_SECONDS": "0.3"})
        adapter.load()
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
        self.assertEqual(os.listdir(self.dirs["output"]), ["someone-elses.mp4"], "not named in this job's history")
        self.assertEqual(Path(self.dirs["output"], "someone-elses.mp4").read_bytes(), b"not ours")
        self.assertEqual(len(adapter.last_cleanup["removed"]), 1)
        self.assertEqual(adapter.last_cleanup["untracked"], ["someone-elses.mp4"])

    def test_a_file_replaced_under_the_same_name_is_kept_and_reported(self):
        adapter = self.adapter()
        adapter.load()
        output = self.dirs["output"]

        class ReplacingSink(io.BytesIO):
            done = False

            def write(self, data):
                if not self.done:  # mid-copy, another writer swaps a different file in under our name
                    self.done = True
                    name = [n for n in os.listdir(output) if n.endswith(".mp4")][0]
                    Path(output, "swap.tmp").write_bytes(b"a different file")
                    os.replace(os.path.join(output, "swap.tmp"), os.path.join(output, name))
                return super().write(data)

        adapter.render_to(request(), ReplacingSink())
        left = os.listdir(output)
        self.assertEqual(len(left), 1, "the replacement survives")
        self.assertEqual(Path(output, left[0]).read_bytes(), b"a different file")
        self.assertEqual(adapter.last_cleanup["kept_replaced"], left)
        self.assertEqual(adapter.last_cleanup["removed"], [])

    def test_cleanup_failures_are_reported_and_logged(self):
        adapter = self.adapter()
        adapter.load()
        import app.comfy_video_adapter as adapter_module
        real_unlink = adapter_module.os.unlink

        def refusing_unlink(path, *a, **k):
            raise PermissionError("in use")

        adapter_module.os.unlink = refusing_unlink
        try:
            with self.assertLogs("kaliv.media.comfy", level="WARNING") as logs:
                adapter.render_to(request(), io.BytesIO())
        finally:
            adapter_module.os.unlink = real_unlink
        self.assertEqual(len(adapter.last_cleanup["failed"]), 1)
        self.assertIn("PermissionError", "\n".join(logs.output))
        self.assertNotIn("Nørrebro", "\n".join(logs.output), "no prompt text in the log")

    def test_cleanup_works_without_dir_fd_support(self):
        """The rig is Windows: no dir_fd. Same identity rule, by path."""
        from unittest.mock import patch
        adapter = self.adapter(fake={"FAKE_COMFY_FOREIGN_FILE": "foreign.bin"})
        adapter.load()
        with patch.object(os, "supports_dir_fd", set()):
            self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
        self.assertEqual(os.listdir(self.dirs["output"]), ["foreign.bin"])
        self.assertEqual(len(adapter.last_cleanup["removed"]), 1)

    # --- #2316 6505072747: no deletion of a replaced file on either code path -------------------
    def _both_paths(self):
        from contextlib import nullcontext
        from unittest.mock import patch
        return (("dir_fd (POSIX)", nullcontext()), ("by path (Windows)", patch.object(os, "supports_dir_fd", set())))

    def test_a_file_swapped_in_right_before_the_capture_is_never_deleted(self):
        import app.comfy_video_adapter as adapter_module
        for label, mode in self._both_paths():
            with self.subTest(label):
                self.port = free_port()
                adapter = self.adapter()
                adapter.load()
                output, real_rename = self.dirs["output"], adapter_module.os.rename

                def swap_then_rename(src, dst, **kw):
                    if os.path.basename(str(dst)).startswith(".kaliv-cleanup-") and not swapped:
                        swapped.append(1)  # the adversary wins the race: a different file now carries the name
                        Path(output, "x.tmp").write_bytes(b"swapped in by someone else")
                        os.replace(os.path.join(output, "x.tmp"), os.path.join(output, os.path.basename(str(src))))
                    return real_rename(src, dst, **kw)

                swapped = []
                adapter_module.os.rename = swap_then_rename
                try:
                    with mode:
                        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
                finally:
                    adapter_module.os.rename = real_rename
                left = os.listdir(output)
                self.assertEqual(len(left), 1, f"{label}: the swapped-in file survives under its own name: {left}")
                self.assertFalse(left[0].startswith(".kaliv-cleanup-"))
                self.assertEqual(Path(output, left[0]).read_bytes(), b"swapped in by someone else")
                self.assertEqual(adapter.last_cleanup["kept_replaced"], left)
                adapter.close()
                os.unlink(os.path.join(output, left[0]))

    def test_if_the_name_is_taken_again_before_the_restore_nothing_is_deleted(self):
        import app.comfy_video_adapter as adapter_module
        for label, mode in self._both_paths():
            with self.subTest(label):
                self.port = free_port()
                adapter = self.adapter()
                adapter.load()
                output = self.dirs["output"]
                real_rename, real_link = adapter_module.os.rename, adapter_module.os.link

                def swap_then_rename(src, dst, **kw):
                    if os.path.basename(str(dst)).startswith(".kaliv-cleanup-"):
                        Path(output, "x.tmp").write_bytes(b"first stranger")
                        os.replace(os.path.join(output, "x.tmp"), os.path.join(output, os.path.basename(str(src))))
                    return real_rename(src, dst, **kw)

                def retake_then_link(src, dst, **kw):
                    Path(output, os.path.basename(str(dst))).write_bytes(b"second stranger")  # name taken again
                    return real_link(src, dst, **kw)

                adapter_module.os.rename, adapter_module.os.link = swap_then_rename, retake_then_link
                try:
                    with mode:
                        adapter.render_to(request(), io.BytesIO())
                finally:
                    adapter_module.os.rename, adapter_module.os.link = real_rename, real_link
                contents = sorted(Path(output, n).read_bytes() for n in os.listdir(output))
                self.assertEqual(contents, [b"first stranger", b"second stranger"], f"{label}: nobody's file is deleted")
                self.assertIn("(now .kaliv-cleanup-", adapter.last_cleanup["kept_replaced"][0])
                adapter.close()
                for n in os.listdir(output):
                    os.unlink(os.path.join(output, n))

    def test_without_a_file_id_nothing_is_deleted(self):
        """Some filesystems report st_ino 0: identity is then unprovable, so the file is kept."""
        import app.comfy_video_adapter as adapter_module
        adapter = self.adapter()
        adapter.load()
        real_stat = adapter_module.os.stat

        def no_file_id(path, *a, **k):
            info = real_stat(path, *a, **k)
            if str(path).endswith(".mp4"):
                info = os.stat_result((info[0], 0) + tuple(info[2:10]))
            return info

        adapter_module.os.stat = no_file_id
        try:
            self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
        finally:
            adapter_module.os.stat = real_stat
        left = os.listdir(self.dirs["output"])
        self.assertEqual(len(left), 1, "kept")
        self.assertEqual(adapter.last_cleanup["untracked"], left, "and reported")
        self.assertEqual(adapter.last_cleanup["removed"], [])

    def test_a_captured_file_that_cannot_be_deleted_is_reported_where_it_is(self):
        import app.comfy_video_adapter as adapter_module
        adapter = self.adapter()
        adapter.load()
        real_unlink = adapter_module.os.unlink

        def refusing_unlink(path, *a, **k):
            raise PermissionError("in use")

        adapter_module.os.unlink = refusing_unlink
        try:
            with self.assertLogs("kaliv.media.comfy", level="WARNING") as logs:
                adapter.render_to(request(), io.BytesIO())
        finally:
            adapter_module.os.unlink = real_unlink
        left = os.listdir(self.dirs["output"])
        self.assertEqual(len(left), 1)
        self.assertTrue(left[0].startswith(".kaliv-cleanup-"))
        self.assertIn(f"(now {left[0]})", adapter.last_cleanup["failed"][0])
        self.assertIn(left[0], "\n".join(logs.output))

    def test_the_native_windows_cleanup_contract_passes_on_this_platform(self):
        contract = Path(__file__).resolve().parent / "support" / "windows_cleanup_identity_contract.py"
        result = subprocess.run([sys.executable, str(contract)], capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, PYTHONPATH=str(contract.parents[2] / "worker")))
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
        self.assertIn("(0 failures)", result.stdout)

    # --- G2 cooperative cancellation (#2296 6510332634) ------------------------------------------
    def test_should_cancel_interrupts_comfyui_and_runs_the_normal_cleanup(self):
        from app.media_generation_contract import GenerationCancelled
        adapter = self.adapter(fake={"FAKE_COMFY_RENDER_SECONDS": "5"})
        adapter.load()
        deadline = time.monotonic() + 0.5
        started = time.monotonic()
        with self.assertRaises(GenerationCancelled):
            adapter.render_to(request(), io.BytesIO(), should_cancel=lambda: time.monotonic() >= deadline)
        self.assertLess(time.monotonic() - started, 3, "interrupted, not waited out")
        self.assertEqual(adapter.last_cleanup.get("failed"), [], "cleanup ran and touched nothing it cannot prove")
        self.assertTrue(adapter.supervisor.running, "ComfyUI stays resident for the next job")
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4", "and it still renders")

    def test_an_unconfirmed_drain_marks_the_adapter_for_restart(self):
        """#2318 review 4469472651: a ComfyUI whose queue does not drain must take no further job."""
        from unittest.mock import patch
        from app.comfy_supervisor import ComfySupervisorError
        from app.media_generation_contract import GenerationCancelled
        import app.comfy_video_adapter as adapter_module

        def stuck_queue(sup):
            return False

        def failing_check(sup):
            raise ComfySupervisorError("queue check failed")

        for label in ("queue never drains", "queue check fails", "interrupt fails"):
            with self.subTest(label):
                self.port = free_port()
                adapter = self.adapter(fake={"FAKE_COMFY_RENDER_SECONDS": "5"})
                adapter.load()
                sup = adapter.supervisor
                real_submit, real_queue, real_interrupt = sup.submit, sup.queue_is_empty, sup.interrupt
                submitted = []

                def submit(graph):
                    submitted.append(1)
                    return real_submit(graph)

                def queue_is_empty():
                    if not submitted:
                        return real_queue()  # the pre-submit single-tenant check is real
                    return stuck_queue(sup) if label == "queue never drains" else failing_check(sup)

                def interrupt():
                    if label == "interrupt fails":
                        raise ComfySupervisorError("interrupt failed")
                    return real_interrupt()

                sup.submit, sup.queue_is_empty, sup.interrupt = submit, queue_is_empty, interrupt
                start = time.monotonic()
                try:
                    with patch.object(adapter_module, "DRAIN_SECONDS", 0.3):
                        with self.assertRaises(GenerationCancelled):
                            adapter.render_to(request(), io.BytesIO(),
                                              should_cancel=lambda: time.monotonic() - start > 0.3)
                finally:
                    sup.submit, sup.queue_is_empty, sup.interrupt = real_submit, real_queue, real_interrupt
                self.assertTrue(adapter.needs_restart)
                self.assertTrue(adapter.close(), "it can still be stopped and its lease released")
                with self.assertRaisesRegex(GenerationError, "needs a restart"):
                    adapter.load()

    # --- G3 pins (#2296 6634996133) --------------------------------------------------------------
    def _models(self, data=b"wan weights" * 100):
        """A ComfyUI root of our own (the fake main.py plus models/), as on the rig."""
        root = Path(self.tmp, "comfy-root")
        (root / "models" / "diffusion_models").mkdir(parents=True, exist_ok=True)
        shutil.copy(FAKE_MAIN, root / "main.py")
        Path(root, "models", "diffusion_models", "wan2.2_t2v_example.safetensors").write_bytes(data)
        return str(root), {"path": "diffusion_models/wan2.2_t2v_example.safetensors",
                           "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def test_a_pinned_comfyui_version_must_match_at_start(self):
        ok = self.adapter(fake={"FAKE_COMFY_VERSION": "0.3.68"}, profile=self.profile(comfyui_version="0.3.68"))
        ok.load()
        self.assertEqual(ok.render_to(request(), io.BytesIO()), "video/mp4")
        ok.close()
        self.port = free_port()
        wrong = self.adapter(fake={"FAKE_COMFY_VERSION": "0.3.70"}, profile=self.profile(comfyui_version="0.3.68"))
        with self.assertRaisesRegex(GenerationError, "version does not match"):
            wrong.load()
        self.assertFalse(wrong.supervisor.running, "stopped, not left running")
        self.assertTrue(self.lease_is_free(), "and the lease went with it")

    def test_a_version_change_under_a_resident_comfyui_refuses_the_next_job(self):
        adapter = self.adapter(fake={"FAKE_COMFY_VERSION": "0.3.68"}, profile=self.profile(comfyui_version="0.3.68"))
        adapter.load()
        Path(self.state, "comfyui_version").write_text("0.4.0")
        with self.assertRaisesRegex(GenerationError, "version does not match"):
            adapter.render_to(request(), io.BytesIO())
        self.assertFalse(Path(self.state, "last_prompt.json").exists(), "nothing was submitted")

    def test_pinned_weights_are_verified_before_comfyui_starts(self):
        root, pin = self._models()
        good = self.adapter(profile=self.profile(weights=[pin]), comfy_root=root)
        good.load()
        self.assertEqual(good.render_to(request(), io.BytesIO()), "video/mp4")
        good.close()
        os.unlink(Path(self.state, "env.json"))
        Path(root, "models", "diffusion_models", "wan2.2_t2v_example.safetensors").write_bytes(b"swapped weights" * 73)
        self.port = free_port()
        swapped = self.adapter(profile=self.profile(weights=[pin]), comfy_root=root)
        with self.assertRaisesRegex(GenerationError, "pinned model file"):
            swapped.load()
        self.assertFalse(Path(self.state, "env.json").exists(), "ComfyUI never started")
        self.assertTrue(self.lease_is_free())

    def test_a_weight_swapped_after_load_refuses_the_next_job_and_forces_a_restart(self):
        # ComfyUI reads weights when a job runs: the start-time hash must still describe the file.
        root, pin = self._models()
        adapter = self.adapter(profile=self.profile(weights=[pin]), comfy_root=root)
        adapter.load()
        target = Path(root, "models", "diffusion_models", "wan2.2_t2v_example.safetensors")
        incoming = target.with_name("incoming")
        incoming.write_bytes(b"swapped weights" * 73)
        os.replace(incoming, target)
        with self.assertRaisesRegex(GenerationError, "changed since it was verified"):
            adapter.render_to(request(), io.BytesIO())
        self.assertFalse(Path(self.state, "last_prompt.json").exists(), "nothing was submitted")
        self.assertTrue(adapter.needs_restart, "the executor restarts it, which re-verifies")
        adapter.close()

    def test_an_embedding_added_after_load_refuses_the_next_job(self):
        root, pin = self._models()
        adapter = self.adapter(profile=self.profile(weights=[pin]), comfy_root=root)
        adapter.load()
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
        os.unlink(Path(self.state, "last_prompt.json"))
        Path(root, "models", "embeddings").mkdir()
        Path(root, "models", "embeddings", "late.pt").write_bytes(b"tensor")
        with self.assertRaisesRegex(GenerationError, "unpinned embedding"):
            adapter.render_to(request(), io.BytesIO())
        self.assertFalse(Path(self.state, "last_prompt.json").exists(), "nothing was submitted")
        self.assertTrue(adapter.needs_restart)
        adapter.close()

    def test_a_prompt_embedding_under_pins_is_refused_before_anything_is_submitted(self):
        root, pin = self._models()
        adapter = self.adapter(profile=self.profile(weights=[pin]), comfy_root=root)
        adapter.load()
        with self.assertRaisesRegex(GenerationError, "may not reference an embedding"):
            adapter.render_to(request(prompt="a kite embedding:unpinned"), io.BytesIO())
        self.assertFalse(Path(self.state, "last_prompt.json").exists(), "nothing was submitted")
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4", "the next job still runs")
        adapter.close()

    def test_an_ambiguous_comfyui_lookup_is_refused_before_start(self):
        root, pin = self._models()
        Path(root, "extra_model_paths.yaml").write_text("comfyui:\n  base_path: /elsewhere\n")
        adapter = self.adapter(profile=self.profile(weights=[pin]), comfy_root=root)
        with self.assertRaisesRegex(GenerationError, "extra model paths"):
            adapter.load()
        self.assertFalse(Path(self.state, "env.json").exists(), "ComfyUI never started")

    def test_a_template_that_loads_an_unpinned_file_is_refused_before_start(self):
        root, pin = self._models()
        other = dict(pin, path="diffusion_models/some_other.safetensors")
        adapter = self.adapter(profile=self.profile(weights=[other]), comfy_root=root)
        with self.assertRaisesRegex(GenerationError, "not pinned"):
            adapter.load()
        self.assertFalse(Path(self.state, "env.json").exists(), "ComfyUI never started")

    def test_cleanup_never_masks_the_render_result_or_error(self):
        adapter = self.adapter(fake={"FAKE_COMFY_OUTPUT_MODE": "notmp4"})
        adapter.load()

        def exploding_cleanup(*_):
            raise RuntimeError("cleanup bug")

        adapter._remove_job_outputs = exploding_cleanup
        with self.assertLogs("kaliv.media.comfy", level="WARNING"):
            with self.assertRaisesRegex(GenerationError, "not an MP4"):  # the render's own error, not the cleanup's
                adapter.render_to(request(), io.BytesIO())
        adapter.close()
        self.port = free_port()
        good = self.adapter()
        good.load()
        good._remove_job_outputs = exploding_cleanup
        with self.assertLogs("kaliv.media.comfy", level="WARNING"):
            self.assertEqual(good.render_to(request(), io.BytesIO()), "video/mp4", "a successful hand-off stays a success")

    def test_production_supervisor_has_no_default_work_area(self):
        from app.comfy_supervisor import ComfyLaunch, ComfySupervisor, ComfySupervisorError
        launch = ComfyLaunch(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                             input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                             temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
        common = dict(gpu_uuid=GPU, lease_dir=self.lease_dir, launch=launch, reserve_gib=2, min_usable_gib=8)
        with self.assertRaises(TypeError):
            ComfySupervisor(**common)  # work_area is required
        for bogus in (None, "/mnt/media", object()):
            with self.subTest(work_area=bogus), self.assertRaises(ComfySupervisorError):
                ComfySupervisor(work_area=bogus, **common)

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
                left = sorted(os.listdir(self.dirs["output"]))
                expected = {"stale": ["old.mp4"], "subfolder": ["sub"]}.get(mode, [])
                self.assertEqual(left, expected,
                                 "a failed job leaves nothing it owns behind, and never removes what it cannot prove is its own")
                if mode == "subfolder":
                    self.assertEqual(adapter.last_cleanup["untracked"], ["sub"], "kept, and reported")
                if mode in ("symlink", "traversal"):
                    self.assertTrue(Path(self.dirs["output"], "..", "outside.mp4").exists(),
                                    "nothing outside the output root is ever touched")
                for name in left:
                    target = os.path.join(self.dirs["output"], name)
                    shutil.rmtree(target) if os.path.isdir(target) else os.unlink(target)

    def test_vram_is_rechecked_before_every_job(self):
        adapter = self.adapter()
        adapter.load()
        self.assertEqual(adapter.render_to(request(), io.BytesIO()), "video/mp4")
        Path(self.state, "vram_free_gib").write_text("9")  # e.g. Ollama loaded a model meanwhile
        os.unlink(Path(self.state, "last_prompt.json"))
        # G4 (Anders 5 Nov 2026): a VRAM shortage is transient, not a job failure -- it reaches the
        # executor as ComfyVramShortage, which re-queues the job.
        from app.comfy_supervisor import ComfyVramShortage
        with self.assertRaisesRegex(ComfyVramShortage, "insufficient free VRAM"):
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
