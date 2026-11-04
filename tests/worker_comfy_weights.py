#!/usr/bin/env python3
"""Pinned ComfyUI model files (G3, ModelRig #2296 6634996133): verify_weights().

Run: PYTHONPATH=worker python3 tests/worker_comfy_weights.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

import app.comfy_weights as weights_module  # noqa: E402
from app.comfy_weights import WeightsMismatch, verify_weights  # noqa: E402
from app.media_generation_profiles import WeightPin  # noqa: E402

DATA = b"\x00weights" * 4096


def pin_for(path: str, data: bytes = DATA) -> WeightPin:
    return WeightPin(path=path, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


class VerifyWeightsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.models = Path(self.tmp, "models")
        (self.models / "diffusion_models").mkdir(parents=True)
        self.file = self.models / "diffusion_models" / "wan.safetensors"
        self.file.write_bytes(DATA)
        self.pin = pin_for("diffusion_models/wan.safetensors")
        self.cache = str(Path(self.tmp, "weights-cache.json"))

    def test_matching_files_pass(self):
        verify_weights(self.models, [self.pin])

    def test_a_flipped_byte_of_the_same_size_is_refused(self):
        self.file.write_bytes(DATA[:-1] + b"\x01")
        with self.assertRaisesRegex(WeightsMismatch, "SHA-256: diffusion_models/wan.safetensors"):
            verify_weights(self.models, [self.pin])

    def test_wrong_size_missing_and_non_regular_are_refused(self):
        self.file.write_bytes(DATA + b"x")
        with self.assertRaisesRegex(WeightsMismatch, "wrong size"):
            verify_weights(self.models, [self.pin])
        self.file.unlink()
        with self.assertRaisesRegex(WeightsMismatch, "missing"):
            verify_weights(self.models, [self.pin])
        self.file.mkdir()
        with self.assertRaisesRegex(WeightsMismatch, "not a regular file|cannot be opened"):
            verify_weights(self.models, [self.pin])

    def test_links_and_escapes_are_refused(self):
        outside = Path(self.tmp, "outside.safetensors")
        outside.write_bytes(DATA)
        self.file.unlink()
        self.file.symlink_to(outside)
        with self.assertRaisesRegex(WeightsMismatch, "link or outside"):
            verify_weights(self.models, [self.pin])
        self.file.unlink()
        linked_dir = self.models / "linked"
        linked_dir.symlink_to(Path(self.tmp), target_is_directory=True)
        with self.assertRaisesRegex(WeightsMismatch, "link or outside"):
            verify_weights(self.models, [pin_for("linked/outside.safetensors")])
        with self.assertRaisesRegex(WeightsMismatch, "link or outside|missing"):
            verify_weights(self.models, [pin_for("../outside.safetensors")])  # a pin built without the parser

    def test_the_models_directory_must_be_absolute_and_real(self):
        with self.assertRaises(WeightsMismatch):
            verify_weights("models", [self.pin])
        link = Path(self.tmp, "models-link")
        link.symlink_to(self.models, target_is_directory=True)
        with self.assertRaises(WeightsMismatch):
            verify_weights(link, [self.pin])

    def test_a_cache_hit_skips_the_rehash(self):
        verify_weights(self.models, [self.pin], cache_path=self.cache)
        reads = []
        real_read = os.read
        with patch.object(weights_module.os, "read", lambda fd, n: reads.append(n) or real_read(fd, n)):
            verify_weights(self.models, [self.pin], cache_path=self.cache)
        self.assertEqual(reads, [], "unchanged file: no bytes read")

    # --- the lookup ComfyUI performs must be unambiguous (#2296 6636684138) -----------------------
    def test_an_unambiguous_lookup_passes(self):
        verify_weights(self.models, [self.pin], comfy_root=self.tmp)

    def test_an_extra_model_paths_file_is_refused(self):
        for name in ("extra_model_paths.yaml", "extra_model_paths.yml"):
            with self.subTest(name):
                Path(self.tmp, name).write_text("x: 1\n")
                with self.assertRaisesRegex(WeightsMismatch, "extra model paths"):
                    verify_weights(self.models, [self.pin], comfy_root=self.tmp)
                Path(self.tmp, name).unlink()

    def test_a_second_file_with_a_pinned_name_is_refused(self):
        (self.models / "unet").mkdir()  # ComfyUI treats unet/ as an alias of diffusion_models/
        (self.models / "unet" / "wan.safetensors").write_bytes(b"other weights")
        with self.assertRaisesRegex(WeightsMismatch, "second file named like a pinned weight would be found by ComfyUI: unet/wan.safetensors"):
            verify_weights(self.models, [self.pin], comfy_root=self.tmp)

    def test_links_anywhere_in_the_models_tree_are_refused(self):
        elsewhere = Path(self.tmp, "elsewhere")
        elsewhere.mkdir()
        (self.models / "loras").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(WeightsMismatch, "contains a link ComfyUI would follow: loras"):
            verify_weights(self.models, [self.pin], comfy_root=self.tmp)

    def test_a_new_pin_is_not_satisfied_by_a_cache_entry_for_the_old_one(self):
        verify_weights(self.models, [self.pin], cache_path=self.cache)  # caches the real digest
        repinned = WeightPin(path=self.pin.path, sha256=hashlib.sha256(b"other" + DATA[5:]).hexdigest(),
                             bytes=self.pin.bytes)  # an operator pins different bytes; the file did not change
        with self.assertRaisesRegex(WeightsMismatch, "SHA-256"):
            verify_weights(self.models, [repinned], cache_path=self.cache)

    def test_a_changed_file_is_rehashed_despite_the_cache(self):
        verify_weights(self.models, [self.pin], cache_path=self.cache)
        info = self.file.stat()
        self.file.write_bytes(DATA[:-1] + b"\x01")  # same size, new content, new mtime
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        with self.assertRaisesRegex(WeightsMismatch, "SHA-256"):
            verify_weights(self.models, [self.pin], cache_path=self.cache)

    def test_a_corrupt_or_foreign_cache_never_accepts(self):
        Path(self.cache).write_text("{not json")
        verify_weights(self.models, [self.pin], cache_path=self.cache)  # re-hashed, still fine
        info = self.file.stat()
        key = f"{self.file.resolve()}|{info.st_dev}|{info.st_ino}|{info.st_size}|{info.st_mtime_ns}"
        Path(self.cache).write_text(json.dumps({"version": 1, "entries": {key: "0" * 64}}))
        verify_weights(self.models, [self.pin], cache_path=self.cache)  # a wrong cached digest is not a hit
        self.file.write_bytes(DATA[:-1] + b"\x02")
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns))  # stated limit: same size, inode, mtime
        Path(self.cache).write_text(json.dumps({"version": 2, "entries": {key: self.pin.sha256}}))
        with self.assertRaises(WeightsMismatch, msg="a cache of another version is ignored"):
            verify_weights(self.models, [self.pin], cache_path=self.cache)


if __name__ == "__main__":
    unittest.main()
