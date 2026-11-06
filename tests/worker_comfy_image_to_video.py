#!/usr/bin/env python3
"""Image-to-video, the generator side (#2296 6635978072): template slot, staged source, cleanup.

The adapter receives the source as bytes (the executor reads it through ChatGPT's
owner-gated reader, which is not part of this file). Runs the real ComfySupervisor
and ComfyVideoAdapter against the fake ComfyUI, which records exactly what its
LoadImage would read.

Run: PYTHONPATH=worker python3 tests/worker_comfy_image_to_video.py
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import struct
import sys
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

import app.comfy_video_adapter as adapter_module  # noqa: E402
from app.comfy_workflow_template import load_template  # noqa: E402
from app.media_generation_contract import (ArtifactSinkUnavailable, GenerationCancelled,  # noqa: E402
                                           GenerationError, GenerationRequest)
from app.media_generation_profiles import parse_profile  # noqa: E402
from worker_comfy_supervisor import AnyExistingDirectory, free_port  # noqa: E402
import worker_comfy_video_adapter as base  # noqa: E402  (module import: its test classes must not run here)
from worker_comfy_video_adapter import GRAPH, raw, request, sha  # noqa: E402
from worker_media_generation_profiles import video_profile  # noqa: E402

I2V = copy.deepcopy(GRAPH)
I2V["10"] = {"class_type": "LoadImage", "inputs": {"image": "__KALIV_VIDEO_IMAGE__"}}
I2V["11"] = {"class_type": "WanImageToVideo", "inputs": {"start_image": ["10", 0]}}
SOURCE_NAME = re.compile(r"kaliv-src-[0-9a-f]{16}\.png")


def png(width: int = 832, height: int = 480) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b"")


def i2v_request(**overrides) -> GenerationRequest:
    return request(task="image_to_video", input_asset_id="a" * 32, **overrides)


class TemplateTests(unittest.TestCase):
    def test_the_image_slot_makes_an_image_to_video_template(self):
        self.assertEqual(load_template(raw(I2V), sha(raw(I2V))).task, "image_to_video")
        self.assertEqual(load_template(raw(), sha(raw())).task, "text_to_video")

    def test_the_image_slot_is_only_loadimages_image_input(self):
        for node in ({"class_type": "VAEEncode", "inputs": {"image": "__KALIV_VIDEO_IMAGE__"}},
                     {"class_type": "LoadImage", "inputs": {"upload": "__KALIV_VIDEO_IMAGE__"}}):
            graph = copy.deepcopy(I2V)
            graph["10"] = node
            with self.subTest(node=node), self.assertRaises(GenerationError):
                load_template(raw(graph), sha(raw(graph)))
        graph = copy.deepcopy(I2V)
        graph["12"] = {"class_type": "LoadImage", "inputs": {"image": "__KALIV_VIDEO_IMAGE__"}}
        with self.assertRaisesRegex(GenerationError, "more than once"):
            load_template(raw(graph), sha(raw(graph)))

    def test_bind_takes_only_the_staged_source_name_and_only_for_its_task(self):
        i2v, t2v = load_template(raw(I2V), sha(raw(I2V))), load_template(raw(), sha(raw()))
        bound = i2v.bind(i2v_request(), fps=16, source_file="kaliv-src-0123456789abcdef.png")
        self.assertEqual(bound["10"]["inputs"]["image"], "kaliv-src-0123456789abcdef.png")
        self.assertEqual(i2v.graph["10"]["inputs"]["image"], "__KALIV_VIDEO_IMAGE__", "template not mutated")
        for name in (None, "", "../kaliv-src-0123456789abcdef.png", "kaliv-src-0123456789ABCDEF.png",
                     "kaliv-src-0123.png", "other.png", "kaliv-src-0123456789abcdef.png\n", 7):
            with self.subTest(name=name), self.assertRaisesRegex(GenerationError, "staged source"):
                i2v.bind(i2v_request(), fps=16, source_file=name)
        with self.assertRaisesRegex(GenerationError, "binds image_to_video only"):
            i2v.bind(request(), fps=16)
        with self.assertRaisesRegex(GenerationError, "binds text_to_video only"):
            t2v.bind(i2v_request(), fps=16, source_file="kaliv-src-0123456789abcdef.png")
        with self.assertRaisesRegex(GenerationError, "only valid for image_to_video"):
            t2v.bind(request(), fps=16, source_file="kaliv-src-0123456789abcdef.png")


class SourceLimitTests(unittest.TestCase):
    def test_the_decode_is_bounded_before_anything_else(self):
        adapter_module.check_source_png(png())
        adapter_module.check_source_png(png(4096, 4096))
        for data in (png(4097, 10), png(10, 4097), png(0, 10), png(10, 0), b"GIF89a" + png()[6:],
                     png()[:20], bytearray(png()), "png", None, png().replace(b"IHDR", b"IHDX", 1)):
            with self.subTest(data=bytes(data)[:24] if isinstance(data, (bytes, bytearray)) else data), \
                    self.assertRaises(GenerationError):
                adapter_module.check_source_png(data)
        with patch.object(adapter_module, "MAX_SOURCE_BYTES", len(png()) - 1), self.assertRaises(GenerationError):
            adapter_module.check_source_png(png())

    def test_an_animated_png_is_refused_whatever_its_frame_size(self):
        # #2346 review 4489553700: LoadImage decodes and concatenates every APNG frame, so IHDR's
        # size bounds one frame only. Any animation chunk refuses the source.
        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        single = png()
        head, iend = single[:33], single[-12:]
        idat = single[33:-12]
        actl = chunk(b"acTL", struct.pack(">II", 100, 0))
        fctl = chunk(b"fcTL", struct.pack(">IIIIIHHBB", 0, 832, 480, 0, 0, 1, 10, 0, 0))
        fdat = chunk(b"fdAT", struct.pack(">I", 1) + zlib.compress(b"\x00" * 16))
        for animated in (head + actl + fctl + idat + fdat + iend,  # a regular APNG
                         head + actl + idat + iend,                 # animation control alone
                         head + idat + fctl + fdat + iend):         # frames after the default image
            with self.subTest(chunks=animated[33:].count(b"acTL") + animated.count(b"fdAT")), \
                    self.assertRaisesRegex(GenerationError, "single-frame"):
                adapter_module.check_source_png(animated)
        for truncated in (single[:-12], single[:-12] + b"\x00\x00\x00\x00IEN"):  # no complete IEND
            with self.assertRaisesRegex(GenerationError, "not a complete PNG"):
                adapter_module.check_source_png(truncated)
        adapter_module.check_source_png(head + chunk(b"tEXt", b"Comment\x00fine") + idat + iend)


class ImageToVideoAdapterTests(unittest.TestCase):
    setUp, tearDown = base.AdapterTests.setUp, base.AdapterTests.tearDown
    adapter, profile, lease_is_free = base.AdapterTests.adapter, base.AdapterTests.profile, base.AdapterTests.lease_is_free

    def i2v_profile(self, tasks=("image_to_video",), template="wan-i2v.json", data=None):
        data = raw(I2V) if data is None else data
        Path(self.templates, template).write_bytes(data)
        options = {"template_name": template, "template_sha256": sha(data), "fps": 16,
                   "max_render_seconds": 60, "max_output_bytes": 1024 * 1024, "port": self.port}
        return parse_profile(video_profile(tasks=list(tasks), backend_options=options,
                                           limits={"max_prompt_chars": 200, "sizes": [[832, 480]],
                                                   "max_steps": 30, "max_frames": 81}))

    def loaded(self, fake=None, volume=None):
        adapter = self.adapter(fake=fake, profile=self.i2v_profile(), volume=volume)
        adapter.load()
        return adapter

    def submitted(self) -> bool:
        return Path(self.state, "prompts.log").exists()

    def test_end_to_end_comfyui_loads_exactly_the_source_bytes_then_it_is_removed(self):
        adapter, source = self.loaded(), png()
        sink = io.BytesIO()
        self.assertEqual(adapter.render_to(i2v_request(), sink, source_png=source), "video/mp4")
        self.assertEqual(sink.getvalue()[4:8], b"ftyp")
        seen = json.loads(Path(self.state, "loadimage.json").read_text())
        self.assertEqual([(s["sha256"], s["bytes"]) for s in seen], [(sha(source), len(source))])
        self.assertRegex(seen[0]["name"], SOURCE_NAME)
        sent = json.loads(Path(self.state, "last_prompt.json").read_text())["prompt"]
        self.assertEqual(sent["10"]["inputs"]["image"], seen[0]["name"], "the slot names the staged file")
        self.assertEqual(os.listdir(self.dirs["input"]), [], "the source is removed after the job")
        self.assertEqual(adapter.last_cleanup["source"], "removed")
        # A second job gets a fresh name.
        self.assertEqual(adapter.render_to(i2v_request(seed=8), io.BytesIO(), source_png=source), "video/mp4")
        self.assertNotEqual(json.loads(Path(self.state, "loadimage.json").read_text())[0]["name"], seen[0]["name"])

    def test_the_staged_file_is_exclusive_private_and_on_the_verified_volume(self):
        volume = AnyExistingDirectory()
        adapter = self.loaded(volume=volume)
        created = []
        real_open = os.open

        def spy(path, flags, mode=0o777, **kwargs):
            if Path(str(path)).parent == Path(self.dirs["input"]):
                created.append((flags, mode, list(volume.checked)))
            return real_open(path, flags, mode, **kwargs)
        with patch.object(adapter_module.os, "open", spy):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        (flags, mode, checked_before), = created
        self.assertTrue(flags & os.O_EXCL and flags & os.O_CREAT, "exclusive create")
        self.assertTrue(flags & getattr(os, "O_NOFOLLOW", 0) == getattr(os, "O_NOFOLLOW", 0))
        self.assertEqual(mode, 0o600)
        self.assertEqual(checked_before[-1], self.dirs["input"], "the input dir is verified right before the write")

    def test_a_volume_lost_just_before_staging_writes_nothing(self):
        class LosesInputOnSecondCheck(AnyExistingDirectory):
            def require(inner, path):
                if path == self.dirs["input"] and inner.checked.count(path) >= 1:
                    inner.lost.add(path)
                super().require(path)
        adapter = self.loaded(volume=LosesInputOnSecondCheck())
        with self.assertRaises(ArtifactSinkUnavailable):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        self.assertEqual(os.listdir(self.dirs["input"]), [])
        self.assertFalse(self.submitted())

    def test_a_volume_lost_before_the_source_cleanup_touches_nothing(self):
        class LosesInputAtCleanup(AnyExistingDirectory):
            # The input dir is checked: at job start, before staging, after the render, by the
            # output cleanup, and by the source cleanup (the 5th check) -- lost only there.
            def require(inner, path):
                if path == self.dirs["input"] and inner.checked.count(path) >= 4:
                    inner.lost.add(path)
                super().require(path)
        adapter = self.loaded(volume=LosesInputAtCleanup())
        adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        self.assertEqual(len(os.listdir(self.dirs["input"])), 1, "left in place, not touched")
        self.assertTrue(adapter.last_cleanup["source"].startswith("failed"), adapter.last_cleanup["source"])

    def test_the_source_is_removed_after_a_failure_and_after_a_cancel(self):
        adapter = self.loaded(fake={"FAKE_COMFY_OUTPUT_MODE": "error"})
        with self.assertRaisesRegex(GenerationError, "reported an error"):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        self.assertEqual(os.listdir(self.dirs["input"]), [])
        self.assertEqual(adapter.last_cleanup["source"], "removed")
        adapter.close()
        self.port = free_port()
        slow = self.loaded(fake={"FAKE_COMFY_RENDER_SECONDS": "5"})
        start = time.monotonic()
        with self.assertRaises(GenerationCancelled):
            slow.render_to(i2v_request(), io.BytesIO(), source_png=png(),
                           should_cancel=lambda: time.monotonic() - start > 0.3)
        self.assertEqual(os.listdir(self.dirs["input"]), [])
        self.assertEqual(slow.last_cleanup["source"], "removed")

    def test_a_replaced_source_is_kept_not_deleted(self):
        adapter = self.loaded(fake={"FAKE_COMFY_SWAP_INPUT": "1"})
        adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        left = os.listdir(self.dirs["input"])
        self.assertEqual(len(left), 1)
        self.assertEqual(Path(self.dirs["input"], left[0]).read_bytes(), b"someone else's image")
        self.assertTrue(adapter.last_cleanup["source"].startswith("kept"), adapter.last_cleanup["source"])

    def test_the_source_is_required_exactly_for_image_to_video(self):
        adapter = self.loaded()
        with self.assertRaisesRegex(GenerationError, "PNG bytes"):
            adapter.render_to(i2v_request(), io.BytesIO())
        with self.assertRaisesRegex(GenerationError, "not a PNG"):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=b"\x00" * 64)
        with self.assertRaisesRegex(GenerationError, "px per side"):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=png(4097, 16))
        with self.assertRaisesRegex(GenerationError, "task not supported by this profile"):
            adapter.render_to(request(), io.BytesIO(), source_png=png())
        self.assertEqual(os.listdir(self.dirs["input"]), [], "nothing staged")
        self.assertFalse(self.submitted(), "nothing submitted")

    def test_a_profile_listing_both_tasks_still_renders_only_the_templates_task(self):
        adapter = self.adapter(profile=self.i2v_profile(tasks=("image_to_video", "text_to_video")))
        adapter.load()
        with self.assertRaisesRegex(GenerationError, "renders image_to_video only"):
            adapter.render_to(request(), io.BytesIO())
        self.assertFalse(self.submitted())

    def test_a_text_to_video_adapter_refuses_a_source(self):
        adapter = self.adapter()
        adapter.load()
        opened = []
        real_open = os.open
        with patch.object(adapter_module.os, "open", lambda p, *a, **k: opened.append(str(p)) or real_open(p, *a, **k)):
            with self.assertRaisesRegex(GenerationError, "only valid for image_to_video"):
                adapter.render_to(request(), io.BytesIO(), source_png=png())
        self.assertFalse([p for p in opened if p.startswith(self.dirs["input"])], "never staged, not staged-then-removed")
        self.assertFalse(self.submitted())

    def test_a_source_that_changes_while_it_is_written_is_refused_before_submit(self):
        adapter = self.loaded()
        real_stat = os.stat

        def grown(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            if Path(str(path)).name.startswith("kaliv-src-"):
                fields = list(info[:10])
                fields[6] += 1  # st_size
                return os.stat_result(fields)
            return info
        with patch.object(adapter_module.os, "stat", grown), \
                self.assertRaisesRegex(GenerationError, "changed while it was written"):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        self.assertFalse(self.submitted())
        self.assertEqual(os.listdir(self.dirs["input"]), [], "the refused source is still cleaned up")

    def test_a_failed_write_after_the_create_still_removes_the_source(self):
        # #2346 review 4484574398: the identity used to be recorded only after the write, so a
        # failing write or fsync left the private source image behind with no cleanup report.
        adapter = self.loaded()

        def broken_fsync(fd):
            raise OSError(5, "Input/output error")
        with patch.object(adapter_module.os, "fsync", broken_fsync), self.assertRaises(OSError):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        self.assertEqual(os.listdir(self.dirs["input"]), [], "removed although staging failed")
        self.assertEqual(adapter.last_cleanup["source"], "removed")
        self.assertFalse(self.submitted())

    def test_a_same_size_file_swapped_in_during_the_write_is_refused_and_kept(self):
        # #2346 review 4484574409: the identity came from the name after the write, so a same-size
        # replacement was submitted as the source and then deleted as job-owned.
        adapter = self.loaded()
        source = png()
        real_fsync = os.fsync

        def swap_during_fsync(fd):
            real_fsync(fd)
            ours, = [n for n in os.listdir(self.dirs["input"]) if n.startswith("kaliv-src-")]
            intruder = Path(self.dirs["input"], "intruder.tmp")
            intruder.write_bytes(b"X" * len(source))  # same size, another file
            os.replace(intruder, Path(self.dirs["input"], ours))
        with patch.object(adapter_module.os, "fsync", swap_during_fsync), \
                self.assertRaisesRegex(GenerationError, "changed while it was written"):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=source)
        self.assertFalse(self.submitted(), "never submitted as the source")
        left = os.listdir(self.dirs["input"])
        self.assertEqual(len(left), 1)
        self.assertEqual(Path(self.dirs["input"], left[0]).read_bytes(), b"X" * len(source), "kept, not deleted")
        self.assertTrue(adapter.last_cleanup["source"].startswith("kept"), adapter.last_cleanup["source"])

    def test_a_file_swapped_in_right_after_the_create_is_refused_before_any_write(self):
        adapter = self.loaded()
        real_fstat = os.fstat

        def other_identity(fd):
            info = real_fstat(fd)
            fields = list(info[:10])
            fields[1] += 1  # st_ino: the name now points at another file than the one created
            return os.stat_result(fields)
        with patch.object(adapter_module.os, "fstat", other_identity), \
                self.assertRaisesRegex(GenerationError, "replaced while it was created"):
            adapter.render_to(i2v_request(), io.BytesIO(), source_png=png())
        self.assertFalse(self.submitted())

    def test_the_profile_must_list_the_templates_task(self):
        t2v_on_i2v = self.adapter(profile=self.i2v_profile(tasks=("text_to_video",)))
        with self.assertRaisesRegex(GenerationError, "renders image_to_video, which this profile does not list"):
            t2v_on_i2v.load()
        i2v_on_t2v = self.adapter(profile=self.i2v_profile(template="plain.json", data=raw()))
        with self.assertRaisesRegex(GenerationError, "renders text_to_video, which this profile does not list"):
            i2v_on_t2v.load()
        self.assertTrue(self.lease_is_free(), "refused before ComfyUI started")


if __name__ == "__main__":
    unittest.main()
