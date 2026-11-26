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
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

import app.comfy_weights as weights_module  # noqa: E402
from app.comfy_weights import WeightsMismatch, check_weights_unchanged, verify_weights  # noqa: E402
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

    # --- the files verified at start must still be those files before every job ----------------
    def test_verify_returns_each_files_identity_and_a_later_change_is_caught(self):
        verified = verify_weights(self.models, [self.pin])
        info = os.lstat(self.file)
        self.assertEqual(verified, ((self.pin.path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns),))
        check_weights_unchanged(self.models, verified)
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))  # rewritten in place
        with self.assertRaisesRegex(WeightsMismatch, "changed since it was verified: diffusion_models/wan.safetensors"):
            check_weights_unchanged(self.models, verified)
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns))
        check_weights_unchanged(self.models, verified)
        replacement = self.file.with_name("incoming")
        replacement.write_bytes(DATA)  # the same bytes, but another file
        os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
        os.replace(replacement, self.file)
        with self.assertRaisesRegex(WeightsMismatch, "changed since"):
            check_weights_unchanged(self.models, verified)
        self.file.unlink()
        with self.assertRaisesRegex(WeightsMismatch, "changed since"):
            check_weights_unchanged(self.models, verified)
        self.file.mkdir()
        with self.assertRaisesRegex(WeightsMismatch, "changed since"):
            check_weights_unchanged(self.models, verified)

    def test_a_cache_hit_also_returns_the_identity(self):
        first = verify_weights(self.models, [self.pin], cache_path=self.cache)
        self.assertEqual(verify_weights(self.models, [self.pin], cache_path=self.cache), first)

    def test_the_identity_must_describe_the_hashed_file(self):
        info = os.stat(self.file)
        self.file.write_bytes(DATA + b"grown")  # changed between the hash and the identity
        with self.assertRaisesRegex(WeightsMismatch, "changed while it was verified"):
            weights_module._identity(self.file, self.pin.path, info)

    def test_a_flipped_byte_of_the_same_size_is_refused(self):
        self.file.write_bytes(DATA[:-1] + b"\x01")
        with self.assertRaisesRegex(WeightsMismatch, "SHA-256: diffusion_models/wan.safetensors"):
            verify_weights(self.models, [self.pin])

    def returns_promptly(self, fn):
        """Run fn in a daemon thread; fail if it is still blocked after 10 s. Returns its exception."""
        box = {}

        def run():
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 -- handed back to the test
                box["exc"] = exc
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "blocked on a special file")
        return box.get("exc")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs")
    def test_a_fifo_named_like_a_pinned_weight_is_refused_without_blocking(self):
        # #2328 review 4472123700: a blocking open of a FIFO with no writer never returns.
        self.file.unlink()
        os.mkfifo(self.file)
        exc = self.returns_promptly(lambda: verify_weights(self.models, [self.pin]))
        self.assertIsInstance(exc, WeightsMismatch)
        self.assertIn("not a regular file", str(exc))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs")
    def test_the_open_itself_cannot_block_so_a_late_swap_to_a_fifo_cannot_either(self):
        fifo = Path(self.tmp, "swapped-in")
        os.mkfifo(fifo)
        self.assertIsNone(self.returns_promptly(lambda: os.close(os.open(fifo, weights_module._READ_FLAGS))))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs")
    def test_a_fifo_as_the_cache_is_ignored_and_replaced(self):
        os.mkfifo(self.cache)
        self.assertIsNone(self.returns_promptly(
            lambda: verify_weights(self.models, [self.pin], cache_path=self.cache)))
        self.assertTrue(Path(self.cache).is_file(), "the store replaced it with a regular cache file")
        self.assertEqual(len(json.loads(Path(self.cache).read_text())["entries"]), 1)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs")
    def test_the_cache_store_never_writes_through_something_already_there(self):
        with patch.object(weights_module.secrets, "token_hex", return_value="deadbeef"):
            os.mkfifo(f"{self.cache}.tmp-{os.getpid()}-deadbeef")
            self.assertIsNone(self.returns_promptly(
                lambda: verify_weights(self.models, [self.pin], cache_path=self.cache)))
        self.assertFalse(Path(self.cache).exists(), "skipped, not written through the FIFO")

    def test_a_leftover_temporary_from_an_earlier_process_does_not_stop_the_cache(self):
        Path(f"{self.cache}.tmp-{os.getpid()}").write_text("left by a crash with a reused pid")
        verify_weights(self.models, [self.pin], cache_path=self.cache)
        self.assertEqual(len(json.loads(Path(self.cache).read_text())["entries"]), 1)

    def test_an_oversized_cache_is_ignored(self):
        # Valid JSON followed by whitespace: only the size cap refuses it.
        valid = json.dumps({"version": 1, "entries": {"k": "ab" * 32}})
        Path(self.cache).write_text(valid + " " * weights_module.MAX_CACHE_BYTES)
        self.assertEqual(weights_module._load_cache(self.cache), {})
        Path(self.cache).write_text(valid)
        self.assertEqual(weights_module._load_cache(self.cache), {"k": "ab" * 32})

    def test_a_directory_as_the_cache_is_ignored(self):
        os.mkdir(self.cache)
        verify_weights(self.models, [self.pin], cache_path=self.cache)  # re-hashes; the store fails quietly
        self.assertEqual(weights_module._load_cache(self.cache), {})

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
        # The cache file itself is now read with os.read too; weight files are read in CHUNKs.
        self.assertEqual([n for n in reads if n == weights_module.CHUNK], [], "unchanged file: no weight bytes read")

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

    def test_an_unpinned_embedding_is_refused(self):
        # #2328 review 4472675615: a prompt's "embedding:<name>" loads models/embeddings/<name>.
        (self.models / "embeddings" / "sub").mkdir(parents=True)
        (self.models / "embeddings" / "sub" / "unpinned.pt").write_bytes(b"tensor")
        with self.assertRaisesRegex(WeightsMismatch, "unpinned embedding could be loaded by a prompt: embeddings/sub/unpinned.pt"):
            verify_weights(self.models, [self.pin], comfy_root=self.tmp)
        verify_weights(self.models, [self.pin])  # without comfy_root no lookup check (unit scope)
        pinned = pin_for("embeddings/sub/unpinned.pt", b"tensor")
        verify_weights(self.models, [self.pin, pinned], comfy_root=self.tmp)

    def test_a_second_file_differing_only_in_case_is_refused(self):
        # A Windows lookup of wan.safetensors would also open unet/WAN.safetensors.
        (self.models / "unet").mkdir()
        (self.models / "unet" / "WAN.safetensors").write_bytes(b"other weights")
        with self.assertRaisesRegex(WeightsMismatch, "second file named like a pinned weight would be found by ComfyUI: unet/WAN.safetensors"):
            verify_weights(self.models, [self.pin], comfy_root=self.tmp)
        # And the other way round: an upper-case pin, a lower-case second file.
        (self.models / "unet" / "WAN.safetensors").unlink()
        self.file.rename(self.models / "diffusion_models" / "Wan.safetensors")
        (self.models / "unet" / "wan.safetensors").write_bytes(b"other weights")
        with self.assertRaisesRegex(WeightsMismatch, "would be found by ComfyUI: unet/wan.safetensors"):
            verify_weights(self.models, [pin_for("diffusion_models/Wan.safetensors")], comfy_root=self.tmp)

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

    def test_a_malformed_cached_digest_is_a_miss_not_a_failure(self):
        # #2328 review 4472955385: compare_digest raises TypeError on a non-ASCII string.
        info = self.file.stat()
        key = f"{self.file.resolve()}|{info.st_dev}|{info.st_ino}|{info.st_size}|{info.st_mtime_ns}"
        for bad in ("\u00e9" * 64, self.pin.sha256.upper(), self.pin.sha256[:63], self.pin.sha256 + "0", 7, None):
            with self.subTest(bad=str(bad)[:12]):
                Path(self.cache).write_text(json.dumps({"version": 1, "entries": {key: bad}}))
                self.assertEqual(weights_module._load_cache(self.cache), {})
                verify_weights(self.models, [self.pin], cache_path=self.cache)  # re-hashed, still fine

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
