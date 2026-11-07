"""Offline atomic gallery-index registration tests, including the process-lifetime lock.

Runs on Linux CI and, unchanged, on the Windows gate (msvcrt locking).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.media_gallery_index_writer import index_lock, register_asset
from app.media_gallery_catalog import GalleryUnavailable, list_gallery

WORKER = str(Path(__file__).resolve().parents[1] / "worker")
CHILD_ENV = dict(os.environ, PYTHONPATH=WORKER, PYTHONDONTWRITEBYTECODE="1")
HOLD = """
import sys, time
from pathlib import Path
from app.media_gallery_index_writer import index_lock
with index_lock(Path(sys.argv[1])):
    print("held", flush=True)
    time.sleep(120)
"""
REGISTER = """
import sys, time
from unittest.mock import patch
patch("app.media_gallery_catalog.os.path.ismount", return_value=True).start()
from app.media_gallery_index_writer import register_asset
root, volume, asset, size, start = sys.argv[1:]
while time.time() < float(start):
    time.sleep(0.001)
register_asset(root, volume, asset, ".png", int(size))
"""


def hold_lock(root: Path) -> subprocess.Popen:
    """Another process that holds the index lock until it is killed."""
    proc = subprocess.Popen([sys.executable, "-c", HOLD, str(root)], env=CHILD_ENV, stdout=subprocess.PIPE, text=True)
    if proc.stdout.readline().strip() != "held":
        proc.kill()
        raise RuntimeError("the lock holder did not start")
    return proc


def stop(proc: subprocess.Popen) -> None:
    """SIGKILL on POSIX, TerminateProcess on Windows: no cleanup code runs in the holder."""
    proc.kill()
    proc.wait(30)
    proc.stdout.close()


class IndexWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # The Windows runner's %TEMP% is an 8.3 alias (C:\Users\RUNNER~1\...); the catalog's _root
        # rightly refuses a root whose real path differs, so start from the canonical path.
        self.volume = Path(os.path.realpath(self.temp.name))
        self.root = self.volume / "media"
        self.root.mkdir()
        self.mount = patch("app.media_gallery_catalog.os.path.ismount", return_value=True)
        self.mount.start()
        self.addCleanup(self.mount.stop)

    def test_register_and_preserve_entries(self):
        (self.root / "first.png").write_bytes(b"12345")
        register_asset(self.root, self.volume, "first", ".png", 5)
        (self.root / "second.mp4").write_bytes(b"0123456789")
        register_asset(self.root, self.volume, "second", ".mp4", 10)
        items = list_gallery(self.root, verified_volume_root=self.volume)["items"]
        self.assertEqual([item["id"] for item in items], ["first", "second"])
        self.assertEqual(items[1]["mime_type"], "video/mp4")

    def test_preserves_explicit_range_support_on_subsequent_registration(self):
        (self.root / "first.mp4").write_bytes(b"video")
        (self.root / "gallery-index.json").write_text(json.dumps([{
            "id": "first", "kind": "video", "mime_type": "video/mp4",
            "size_bytes": 5, "created_at": "2026-11-03T00:00:00Z",
            "supports_range": False,
        }]))
        (self.root / "second.png").write_bytes(b"image")
        register_asset(self.root, self.volume, "second", ".png", 5)
        raw = json.loads((self.root / "gallery-index.json").read_text())
        self.assertIs(raw[0]["supports_range"], False)
        items = list_gallery(self.root, verified_volume_root=self.volume)["items"]
        self.assertIs(items[0]["playback"]["supports_range"], False)

    def test_refuse_duplicate_without_corrupting_index(self):
        (self.root / "first.png").write_bytes(b"12345")
        register_asset(self.root, self.volume, "first", ".png", 5)
        before = (self.root / "gallery-index.json").read_bytes()
        register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertEqual((self.root / "gallery-index.json").read_bytes(), before)
        (self.root / "first.mp4").write_bytes(b"12345")
        with self.assertRaisesRegex(GalleryUnavailable, "duplicate_index_id"):
            register_asset(self.root, self.volume, "first", ".mp4", 5)
        with self.assertRaisesRegex(GalleryUnavailable, "asset_size_mismatch"):
            register_asset(self.root, self.volume, "first", ".png", 6)
        self.assertEqual((self.root / "gallery-index.json").read_bytes(), before)

    def test_refuse_traversal_asset_id_before_filesystem_access(self):
        with self.assertRaisesRegex(ValueError, "invalid_asset_id"):
            register_asset(self.root, self.volume, "../outside", ".png", 5)
        with self.assertRaisesRegex(ValueError, "invalid_asset_id"):
            register_asset(self.root, self.volume, "", ".png", 5)
        self.assertFalse((self.root / "gallery-index.json").exists())

    def test_refuse_missing_or_wrong_size_asset(self):
        with self.assertRaisesRegex(GalleryUnavailable, "asset_unavailable"):
            register_asset(self.root, self.volume, "missing", ".png", 5)
        (self.root / "wrong.png").write_bytes(b"123")
        with self.assertRaisesRegex(GalleryUnavailable, "asset_size_mismatch"):
            register_asset(self.root, self.volume, "wrong", ".png", 5)
        self.assertFalse((self.root / "gallery-index.json").exists())

    def test_refuse_active_lock(self):
        # A live writer in another process holds the OS lock for longer than the bounded wait.
        (self.root / "first.png").write_bytes(b"12345")
        holder = hold_lock(self.root)
        try:
            with patch("app.media_gallery_index_writer.LOCK_TIMEOUT_S", 0.5):
                started = time.monotonic()
                with self.assertRaisesRegex(GalleryUnavailable, "gallery_index_locked"):
                    register_asset(self.root, self.volume, "first", ".png", 5)
                self.assertGreaterEqual(time.monotonic() - started, 0.45, "it waited before refusing")
            self.assertFalse((self.root / "gallery-index.json").exists())
        finally:
            stop(holder)
        register_asset(self.root, self.volume, "first", ".png", 5)  # free again once the holder is gone

    def test_a_writer_killed_inside_the_lock_blocks_nobody(self):
        # C8 finding 3 (#2275 6680066477): SIGKILL or power loss inside the window. The OS lock dies
        # with the process; the persistent file stays and is not a lock by itself.
        (self.root / "first.png").write_bytes(b"12345")
        holder = hold_lock(self.root)
        stop(holder)
        self.assertTrue((self.root / ".gallery-index.lock").exists())
        # The default bounded wait: Windows releases a dead process's byte-range locks "after a
        # delay that depends on system resources" (LockFileEx), so no shorter timeout here.
        register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertEqual([i["id"] for i in list_gallery(self.root, verified_volume_root=self.volume)["items"]],
                         ["first"])

    def test_a_leftover_lock_file_from_the_old_writer_blocks_nothing(self):
        (self.root / "first.png").write_bytes(b"12345")
        (self.root / ".gallery-index.lock").write_text("busy")
        register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertEqual((self.root / ".gallery-index.lock").read_text(), "busy", "never unlinked or rewritten")

    def test_concurrent_writers_in_separate_processes_are_all_indexed(self):
        # C8 finding 2: two executors (one per GPU) finishing together. Six processes start at once.
        ids = [f"asset{n}" for n in range(6)]
        for n, asset in enumerate(ids):
            (self.root / f"{asset}.png").write_bytes(b"x" * (n + 1))
        start = time.time() + 1.0
        procs = [subprocess.Popen([sys.executable, "-c", REGISTER, str(self.root), str(self.volume), asset,
                                   str(n + 1), repr(start)], env=CHILD_ENV, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for n, asset in enumerate(ids)]
        results = [p.communicate(timeout=60) for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * 6, results)
        items = list_gallery(self.root, verified_volume_root=self.volume)["items"]
        self.assertEqual(sorted(i["id"] for i in items), sorted(ids))

    def test_lock_path_that_is_not_a_plain_file_is_refused(self):
        (self.root / "first.png").write_bytes(b"12345")
        lock = self.root / ".gallery-index.lock"
        lock.mkdir()
        with self.assertRaisesRegex(GalleryUnavailable, "gallery_index_lock_refused"):
            register_asset(self.root, self.volume, "first", ".png", 5)
        lock.rmdir()
        target = self.volume / "elsewhere"
        target.write_text("untouched")
        try:
            lock.symlink_to(target)
        except OSError:
            self.skipTest("symlinks need a privilege here")
        with self.assertRaisesRegex(GalleryUnavailable, "gallery_index_lock_refused"):
            register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertEqual(target.read_text(), "untouched")
        self.assertFalse((self.root / "gallery-index.json").exists())

    def test_refuse_corrupt_index_without_replacing_it(self):
        (self.root / "first.png").write_bytes(b"12345")
        (self.root / "gallery-index.json").write_text("{invalid")
        with self.assertRaises(GalleryUnavailable):
            register_asset(self.root, self.volume, "first", ".png", 5)
        self.assertEqual((self.root / "gallery-index.json").read_text(), "{invalid")
        with index_lock(self.root, timeout_s=0):  # released on the error path
            pass


if __name__ == "__main__":
    unittest.main()
