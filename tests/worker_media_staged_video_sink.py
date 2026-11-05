#!/usr/bin/env python3
"""ExternalStagedVideoSink: the production staged, job-keyed video sink (#2296 6667142387).

Two parts:
- the seam's conformance suite (tests/support/staged_sink_conformance.py) against the real class
  on a real directory, with the gallery index as the registry;
- job-keyed and adversarial rules: idempotent retry, conflicts, symlinks, a staged name swapped
  mid-adopt, volume loss at each step, registration failure, no write after publication.

The mount check is the only thing patched (os.path.ismount in the gallery catalog), exactly as the
gallery's own tests do; everything else is the real filesystem.

Run: PYTHONPATH=worker python3 tests/worker_media_staged_video_sink.py
The Windows gate runs the same file on NTFS (hard links, file ids, the index lock).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests" / "support"):
    sys.path.insert(0, str(extra))

import app.media_staged_video_sink as sink_module  # noqa: E402
from app.media_gallery_catalog import list_gallery  # noqa: E402
from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_generation_contract import (  # noqa: E402
    ArtifactSinkUnavailable, JobKeyedStagedSink, StagedFileArtifactSink,
)
from app.media_staged_video_sink import ExternalStagedVideoSink  # noqa: E402
from staged_sink_conformance import MP4, StagedSinkConformance  # noqa: E402

JOB = "0123456789abcdef0123456789abcdef"


class _Volume:
    """A real directory that stands in for the mounted external volume."""

    def __init__(self, test: unittest.TestCase):
        self.root = Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.root, True)
        self.media = self.root / "media"
        self.media.mkdir()
        self.mounted = True
        mount = patch("app.media_gallery_catalog.os.path.ismount",
                      side_effect=lambda p: self.mounted and Path(p) == self.root)
        mount.start()
        test.addCleanup(mount.stop)

    def sink(self, **kwargs) -> ExternalStagedVideoSink:
        return ExternalStagedVideoSink(self.media, self.root, **kwargs)

    def indexed(self) -> set:
        index = self.media / "gallery-index.json"
        return {item["id"] for item in json.loads(index.read_text())} if index.exists() else set()

    def temporaries(self) -> list:
        return sorted(p.name for p in self.media.iterdir() if p.name.startswith(".kaliv-"))


class ConformanceAgainstTheRealSink(StagedSinkConformance, unittest.TestCase):
    max_bytes = 4096

    def make_sink(self):
        volume = _Volume(self)
        sink = volume.sink(max_bytes=self.max_bytes)
        sink._test_volume = volume
        return sink

    def published(self, sink):
        volume = sink._test_volume
        return {i for i in volume.indexed() if (volume.media / f"{i}.mp4").is_file()}

    def staging_leftovers(self, sink):
        return sink._test_volume.temporaries()

    def make_volume_unavailable(self, sink):
        sink._test_volume.mounted = False

    def fail_next_registration(self, sink):
        real = sink_module.register_asset
        calls = []

        def failing_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("index write failed")
            return real(*args, **kwargs)
        failing = patch.object(sink_module, "register_asset", failing_once)
        failing.start()
        self.addCleanup(failing.stop)

    def test_it_is_both_seams(self):
        sink = self.make_sink()
        self.assertIsInstance(sink, StagedFileArtifactSink)
        self.assertIsInstance(sink, JobKeyedStagedSink)


class JobKeyedRules(unittest.TestCase):
    def setUp(self):
        self.volume = _Volume(self)
        self.sink = self.volume.sink(max_bytes=4096)
        self.expected = ExternalMediaSink(self.volume.media, self.volume.root).job_asset_id(JOB)

    def adopt(self, data=MP4, job=JOB, sink=None):
        sink = sink or self.sink
        with sink.staged(".mp4") as output:
            output.write(data)
            return sink.adopt_for_job(output, "video/mp4", job)

    def test_the_asset_id_is_the_job_keyed_one_and_the_gallery_lists_it(self):
        asset_id = self.adopt()
        self.assertEqual(asset_id, self.expected)
        self.assertEqual((self.volume.media / f"{asset_id}.mp4").read_bytes(), MP4)
        evidence = ExternalMediaSink(self.volume.media, self.volume.root).inspect_job_asset(JOB)
        self.assertEqual((evidence["extension"], evidence["size_bytes"], evidence["indexed"]), (".mp4", len(MP4), True))
        items = list_gallery(self.volume.media, verified_volume_root=self.volume.root)["items"]
        self.assertEqual([(i["id"], i["kind"]) for i in items], [(asset_id, "video")])
        self.assertEqual(self.volume.temporaries(), [])

    def test_the_staged_file_is_exclusive_private_and_named_like_the_sinks_temporaries(self):
        seen = []
        real_open = os.open

        def spy(path, flags, mode=0o777, **kwargs):
            if Path(str(path)).parent == self.volume.media:
                seen.append((Path(str(path)).name, flags, mode))
            return real_open(path, flags, mode, **kwargs)
        with patch.object(sink_module.os, "open", spy), self.sink.staged(".mp4") as output:
            output.write(MP4)
            name = seen[0][0]
            self.assertIn(name, ExternalMediaSink(self.volume.media, self.volume.root).inspect_temporary_files())
        _, flags, mode = seen[0]
        self.assertTrue(flags & os.O_EXCL and flags & os.O_CREAT)
        self.assertEqual(flags & getattr(os, "O_NOFOLLOW", 0), getattr(os, "O_NOFOLLOW", 0))
        self.assertEqual(mode, 0o600)

    def test_an_identical_retry_returns_the_same_asset_once(self):
        first = self.adopt()
        second = self.adopt(sink=self.volume.sink(max_bytes=4096))  # e.g. after a restart
        self.assertEqual(first, second)
        self.assertEqual(self.volume.indexed(), {first})
        self.assertEqual(sorted(p.name for p in self.volume.media.glob("*.mp4")), [f"{first}.mp4"])

    def test_different_bytes_under_the_same_job_are_a_conflict_and_change_nothing(self):
        first = self.adopt()
        other = MP4[:-1] + b"\x01"
        with self.assertRaisesRegex(ArtifactSinkUnavailable, "asset_job_conflict"):
            self.adopt(data=other)
        self.assertEqual((self.volume.media / f"{first}.mp4").read_bytes(), MP4, "never overwritten")
        self.assertEqual(self.volume.temporaries(), [])

    def test_a_png_under_the_same_job_is_a_conflict(self):
        (self.volume.media / f"{self.expected}.png").write_bytes(b"\x89PNG")
        with self.assertRaisesRegex(ArtifactSinkUnavailable, "asset_job_conflict"):
            self.adopt()
        self.assertFalse((self.volume.media / f"{self.expected}.mp4").exists())

    def test_a_symlink_at_the_destination_is_a_conflict_and_is_not_followed(self):
        target = self.volume.root / "elsewhere.mp4"
        target.write_bytes(MP4)  # even with identical bytes behind it
        try:
            (self.volume.media / f"{self.expected}.mp4").symlink_to(target)
        except OSError:  # Windows without the symlink privilege
            self.skipTest("symlinks cannot be created here")
        with self.assertRaisesRegex(ArtifactSinkUnavailable, "asset_job_conflict"):
            self.adopt()
        self.assertEqual(self.volume.indexed(), set())
        self.assertEqual(target.read_bytes(), MP4)

    def test_a_staged_name_swapped_before_adoption_is_refused_and_kept(self):
        with self.assertRaisesRegex(ArtifactSinkUnavailable, "staged_video_changed"):
            with self.sink.staged(".mp4") as output:
                output.write(MP4)
                name, = self.volume.temporaries()
                intruder = self.volume.media / "intruder"
                intruder.write_bytes(MP4)  # same bytes, another file
                os.replace(intruder, self.volume.media / name)
                self.sink.adopt_for_job(output, "video/mp4", JOB)
        self.assertEqual(self.volume.indexed(), set())
        self.assertFalse((self.volume.media / f"{self.expected}.mp4").exists())
        self.assertEqual(len(self.volume.temporaries()), 1, "not ours: kept, not deleted")

    def test_a_volume_lost_at_staging_creates_nothing(self):
        self.volume.mounted = False
        with self.assertRaises(ArtifactSinkUnavailable), self.sink.staged(".mp4"):
            pass
        self.assertEqual(os.listdir(self.volume.media), [])

    def test_a_volume_lost_before_cleanup_touches_nothing(self):
        with self.sink.staged(".mp4") as output:
            output.write(MP4)
            self.volume.mounted = False
        self.volume.mounted = True
        self.assertEqual(len(self.volume.temporaries()), 1, "left for the read-only inventory, not touched")

    def test_a_failed_registration_removes_only_the_link_this_call_made(self):
        def failing(*args, **kwargs):
            raise OSError("index write failed")
        with patch.object(sink_module, "register_asset", failing):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "gallery_registration_failed"):
                self.adopt()
        self.assertFalse((self.volume.media / f"{self.expected}.mp4").exists())
        self.assertEqual(self.volume.temporaries(), [])
        # A retry whose destination already existed (a crash after the link) keeps that file.
        first = self.adopt()
        self.volume.media.joinpath("gallery-index.json").unlink()  # as if the index write was lost
        with patch.object(sink_module, "register_asset", failing):
            with self.assertRaises(ArtifactSinkUnavailable):
                self.adopt()
        self.assertTrue((self.volume.media / f"{first}.mp4").exists(), "a pre-existing asset is never removed")

    def test_a_failed_registration_closes_the_descriptor_before_the_rollback(self):
        # #2347 review 4485110252: on Windows an open descriptor blocks deleting the new link.
        # Stand in for that platform rule everywhere: unlinking a file whose descriptor is open fails.
        open_inodes = {}
        real_open, real_close, real_unlink = os.open, os.close, os.unlink

        def tracking_open(path, flags, mode=0o777, **kwargs):
            fd = real_open(path, flags, mode, **kwargs)
            open_inodes[fd] = os.fstat(fd).st_ino
            return fd

        def tracking_close(fd):
            open_inodes.pop(fd, None)
            return real_close(fd)

        def windows_like_unlink(path, *args, **kwargs):
            if os.lstat(path).st_ino in open_inodes.values():
                raise PermissionError(32, "The process cannot access the file because it is being used")
            return real_unlink(path, *args, **kwargs)

        def failing(*args, **kwargs):
            raise OSError("index write failed")
        with patch.object(sink_module.os, "open", tracking_open), patch.object(sink_module.os, "close", tracking_close), \
                patch.object(sink_module.os, "unlink", windows_like_unlink), patch.object(sink_module, "register_asset", failing):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "^gallery_registration_failed$"):
                self.adopt()
        self.assertFalse((self.volume.media / f"{self.expected}.mp4").exists(), "rolled back")
        self.assertEqual(self.volume.temporaries(), [])

    def test_a_rollback_that_cannot_happen_is_reported_as_such(self):
        real_unlink = os.unlink

        def refuse_the_destination(path, *args, **kwargs):
            if str(path).endswith(".mp4"):
                raise PermissionError(5, "Access is denied")
            return real_unlink(path, *args, **kwargs)

        def failing(*args, **kwargs):
            raise OSError("index write failed")
        with patch.object(sink_module.os, "unlink", refuse_the_destination), patch.object(sink_module, "register_asset", failing):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "gallery_registration_failed_asset_left_unindexed"):
                self.adopt()
        self.assertEqual(ExternalMediaSink(self.volume.media, self.volume.root).inspect_unindexed_assets(),
                         [f"{self.expected}.mp4"], "visible to the read-only inventory, never indexed")

    def test_no_write_reaches_the_published_file_after_adoption(self):
        with self.sink.staged(".mp4") as output:
            output.write(MP4)
            asset_id = self.sink.adopt_for_job(output, "video/mp4", JOB)
            with self.assertRaises(ValueError):
                output.write(b"tamper")
            self.assertIsNone(output._ticket.fd, "the descriptor that shares the published inode is closed at once")
        self.assertEqual((self.volume.media / f"{asset_id}.mp4").read_bytes(), MP4)

    def test_one_adoption_attempt_per_handle_even_after_a_refused_one(self):
        with self.sink.staged(".mp4") as output:
            output.write(MP4)
            with self.assertRaises(ValueError):
                self.sink.adopt_for_job(output, "video/webm", JOB)
            with self.assertRaises(ValueError):
                self.sink.adopt_for_job(output, "video/mp4", JOB)
        self.assertEqual(self.volume.indexed(), set())

    def test_a_name_swapped_right_after_the_create_is_refused_and_not_deleted(self):
        real_fstat = os.fstat

        def other_file(fd):
            info = real_fstat(fd)
            fields = list(info[:10])
            fields[1] += 1  # st_ino: the name no longer is the file this sink created
            return os.stat_result(fields)
        with patch.object(sink_module.os, "fstat", other_file):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "staged_video_replaced"), self.sink.staged(".mp4"):
                pass
        self.assertEqual(len(self.volume.temporaries()), 1, "not provably ours: left alone")

    def test_a_runaway_writer_cannot_fill_the_volume(self):
        sink = self.volume.sink(max_bytes=64)
        with sink.staged(".mp4") as output:
            for _ in range(100):
                output.write(MP4)
            name, = self.volume.temporaries()
            self.assertLessEqual((self.volume.media / name).stat().st_size, 65)
            with self.assertRaisesRegex(ValueError, "size out of bounds"):
                sink.adopt_for_job(output, "video/mp4", JOB)
        self.assertEqual(self.volume.temporaries(), [])

    def test_a_malformed_job_key_publishes_nothing(self):
        for key in ("", "../x", "a" * 129, "white space", None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.adopt(job=key)
        self.assertEqual(self.volume.indexed(), set())
        self.assertEqual(self.volume.temporaries(), [])

    def test_the_bound_is_capped_by_the_artifact_limit(self):
        from app.media_generation_contract import MAX_ARTIFACT_BYTES
        for bad in (0, 11, MAX_ARTIFACT_BYTES + 1, True, "4096"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.volume.sink(max_bytes=bad)

    def test_only_an_mp4_container_is_adopted(self):
        with self.sink.staged(".mp4") as output:
            output.write(b"\x00" * 64)  # the right size, no "ftyp" box
            with self.assertRaisesRegex(ValueError, "not an MP4"):
                self.sink.adopt_for_job(output, "video/mp4", JOB)
        self.assertEqual(self.volume.indexed(), set())

    def test_a_destination_that_appears_in_the_link_race_is_never_claimed(self):
        # os.link "succeeds", but what now has the name is another file: refuse, touch nothing.
        def racing_link(src, dst, **kwargs):
            Path(dst).write_bytes(MP4)
        with patch.object(sink_module.os, "link", racing_link):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "asset_job_conflict"):
                self.adopt()
        self.assertEqual(self.volume.indexed(), set())
        self.assertTrue((self.volume.media / f"{self.expected}.mp4").exists(), "the other file is kept")

    def test_it_never_logs(self):
        with self.assertNoLogs(level="DEBUG"):
            self.adopt()


if __name__ == "__main__":
    unittest.main()
