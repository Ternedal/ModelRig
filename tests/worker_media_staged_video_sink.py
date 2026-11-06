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
        # Canonical spelling: the gallery's root check refuses a path that resolves differently,
        # and on the Windows runner TEMP is an 8.3 short name (C:\\Users\\RUNNER~1\\...).
        self.root = Path(tempfile.mkdtemp()).resolve()
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

    def test_an_io_error_checking_the_new_staged_file_stops_the_sink_and_leaves_the_name(self):
        """Codex P2 (#2347 4498227150): an OSError from the identity check right after the create
        went up raw, so the executor failed the job and kept working on a broken volume. It must be
        the fatal ArtifactSinkUnavailable (exit 75), with the descriptor closed and the unproven
        name left alone."""
        import errno
        for failing in ("fstat", "lstat"):
            with self.subTest(failing=failing):
                real = getattr(os, failing)
                opened, closed = [], []
                real_open, real_close = os.open, os.close

                def spy_open(path, flags, *args, **kwargs):
                    fd = real_open(path, flags, *args, **kwargs)
                    if Path(str(path)).parent == self.volume.media:
                        opened.append(fd)
                    return fd

                def spy_close(fd):
                    closed.append(fd)
                    return real_close(fd)

                def broken(target, *args, **kwargs):
                    if isinstance(target, int) or Path(str(target)).parent == self.volume.media:
                        raise OSError(errno.EIO, "Input/output error")
                    return real(target, *args, **kwargs)
                with patch("app.media_staged_video_sink.os.open", side_effect=spy_open), \
                        patch("app.media_staged_video_sink.os.close", side_effect=spy_close), \
                        patch(f"app.media_staged_video_sink.os.{failing}", side_effect=broken), \
                        self.assertRaisesRegex(ArtifactSinkUnavailable, "^staged_video_unavailable$"):
                    with self.sink.staged(".mp4"):
                        self.fail("never yields")
                self.assertEqual(len(opened), 1)
                self.assertEqual(opened, closed, "the descriptor is closed")
                self.assertEqual(len(self.volume.temporaries()), 1, "the unproven name is left alone")
                for name in self.volume.temporaries():
                    (self.volume.media / name).unlink()

    def test_an_io_error_probing_the_destination_is_a_sink_failure_not_a_raw_error(self):
        """Path.exists() raises for anything but 'not found': a denied or failing name at the
        destination must stop the sink too (same class as Codex 4498227150)."""
        import errno
        real_exists = Path.exists

        def failing(path, *args, **kwargs):
            if path.parent == self.volume.media and path.suffix in (".mp4", ".png") and not path.name.startswith("."):
                raise OSError(errno.EIO, "Input/output error")
            return real_exists(path, *args, **kwargs)
        with patch.object(Path, "exists", autospec=True, side_effect=failing), \
                self.assertRaisesRegex(ArtifactSinkUnavailable, "^staged_video_unavailable$"):
            self.adopt()
        self.assertEqual(self.volume.indexed(), set())

    def test_a_late_error_from_close_never_turns_a_published_asset_into_an_error(self):
        """Adoption fsyncs before it links, so a deferred I/O error reported by close() cannot
        concern the published bytes; it must not surface as a raw OSError after the asset exists."""
        import errno
        if not os.path.isdir("/proc/self/fd"):
            self.skipTest("needs /proc/self/fd to tell the sink's descriptors apart")
        real_close = os.close
        media = os.path.realpath(self.volume.media)

        def failing_close(fd):
            try:
                target = os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                target = ""
            real_close(fd)
            if target == media or (os.path.dirname(target) == media and os.path.basename(target).startswith(".kaliv-")):
                raise OSError(errno.EIO, "Input/output error")  # only the sink's own staged file and folder
        with patch("app.media_staged_video_sink.os.close", side_effect=failing_close):
            asset_id = self.adopt()
        self.assertEqual(asset_id, self.expected)
        self.assertEqual(self.volume.indexed(), {asset_id})

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFOs")
    def test_a_fifo_at_the_destination_is_a_conflict_and_never_blocks(self):
        """Codex P2 (#2347 4498178920): a blocking open of a FIFO with no writer never returned."""
        import threading
        os.mkfifo(self.volume.media / f"{self.expected}.mp4")
        outcome = []

        def adopt():
            try:
                self.adopt()
                outcome.append("adopted")
            except ArtifactSinkUnavailable as exc:
                outcome.append(str(exc))
        worker = threading.Thread(target=adopt, daemon=True)
        worker.start()
        worker.join(timeout=5)
        if worker.is_alive():  # unblock the hung open so the test process can exit
            fd = os.open(self.volume.media / f"{self.expected}.mp4", os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
            worker.join(timeout=5)
            self.fail("adoption blocked on a FIFO")
        self.assertEqual(outcome, ["asset_job_conflict"])
        self.assertEqual(self.volume.indexed(), set())

    def test_a_destination_swapped_between_its_check_and_its_open_is_a_conflict(self):
        """The type is checked before the open and the descriptor after it: a swap in between fails."""
        first = self.adopt()
        destination = self.volume.media / f"{first}.mp4"
        real_open = os.open

        def swap_then_open(path, flags, *args, **kwargs):
            if Path(path) == destination and not flags & (os.O_WRONLY | os.O_RDWR):
                destination.rename(destination.with_name("kept-aside.mp4"))  # alive: no inode reuse
                destination.write_bytes(MP4)  # same bytes, different file
            return real_open(path, flags, *args, **kwargs)
        with patch("app.media_staged_video_sink.os.open", side_effect=swap_then_open), \
                self.assertRaisesRegex(ArtifactSinkUnavailable, "asset_job_conflict"):
            self.adopt(sink=self.volume.sink(max_bytes=4096))

    def test_a_staged_name_swapped_before_adoption_is_refused_and_kept(self):
        real_lstat = os.lstat
        swapped = []

        def other_file_at(path, *args, **kwargs):  # Windows: the name now reports another file
            info = real_lstat(path, *args, **kwargs)
            if swapped and Path(str(path)).name == swapped[0]:
                fields = list(info[:10])
                fields[1] += 1
                return os.stat_result(fields)
            return info
        with self.assertRaisesRegex(ArtifactSinkUnavailable, "staged_video_changed"), \
                patch.object(sink_module.os, "lstat", other_file_at):
            with self.sink.staged(".mp4") as output:
                output.write(MP4)
                name, = self.volume.temporaries()
                if os.name == "nt":
                    # A real replacement of a file that is open without delete sharing is refused
                    # by Windows itself (#2347 review 4485170951); emulate what the name reports.
                    swapped.append(name)
                else:
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

    def test_a_failed_registration_keeps_the_asset_unindexed_and_says_so(self):
        def failing(*args, **kwargs):
            raise OSError("index write failed")
        with patch.object(sink_module, "register_asset", failing):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "gallery_registration_failed_asset_left_unindexed"):
                self.adopt()
        destination = self.volume.media / f"{self.expected}.mp4"
        self.assertEqual(destination.read_bytes(), MP4, "kept: never unlinked")
        self.assertEqual(self.volume.indexed(), set(), "not published: invisible in the gallery")
        self.assertEqual(ExternalMediaSink(self.volume.media, self.volume.root).inspect_unindexed_assets(),
                         [f"{self.expected}.mp4"], "listed for reconciliation")
        self.assertEqual(self.volume.temporaries(), [])
        # An identical retry adopts it.
        self.assertEqual(self.adopt(sink=self.volume.sink(max_bytes=4096)), self.expected)
        self.assertEqual(self.volume.indexed(), {self.expected})

    def test_a_failed_registration_still_cleans_the_staged_name_under_windows_rules(self):
        # #2347 review 4485110252: on Windows an open descriptor blocks deleting any name of the file.
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
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "gallery_registration_failed_asset_left_unindexed"):
                self.adopt()
        self.assertEqual(self.volume.temporaries(), [], "the staged name is removed once the descriptor is closed")

    def test_a_writer_that_fails_after_committing_the_index_does_not_unpublish(self):
        # #2347 review 4485170944: register_asset replaced the index, then its lock cleanup raised.
        real = sink_module.register_asset

        def committed_then_failed(*args, **kwargs):
            real(*args, **kwargs)
            raise PermissionError(5, "lock cleanup failed")
        with patch.object(sink_module, "register_asset", committed_then_failed):
            asset_id = self.adopt()
        self.assertEqual(asset_id, self.expected, "durably registered: reported as published")
        self.assertEqual((self.volume.media / f"{asset_id}.mp4").read_bytes(), MP4, "never deleted")
        self.assertEqual(self.volume.indexed(), {asset_id})
        self.assertEqual(self.volume.temporaries(), [])

    def test_an_unknowable_registration_keeps_the_asset_for_reconciliation(self):
        def failed(*args, **kwargs):
            raise OSError("index write failed")

        def unreadable(root):
            raise sink_module.GalleryUnavailable("invalid_index")
        with patch.object(sink_module, "register_asset", failed), patch.object(sink_module, "_index", unreadable):
            (self.volume.media / "gallery-index.json").write_text("[]")  # present, but cannot be read
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "gallery_registration_unknown_asset_kept"):
                self.adopt()
        self.assertTrue((self.volume.media / f"{self.expected}.mp4").exists(), "kept: it may be indexed")

    def test_a_conflicting_row_for_the_id_is_not_taken_as_ours(self):
        def failed(*args, **kwargs):
            raise OSError("index write failed")

        def other_row(root):
            return [{"id": self.expected, "kind": "video", "mime_type": "video/mp4", "size_bytes": 1}]
        with patch.object(sink_module, "register_asset", failed), patch.object(sink_module, "_index", other_row):
            (self.volume.media / "gallery-index.json").write_text("[]")
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "gallery_registration_unknown_asset_kept"):
                self.adopt()
        self.assertTrue((self.volume.media / f"{self.expected}.mp4").exists())

    def test_a_concurrent_identical_adoption_that_holds_the_lock_is_never_undermined(self):
        # #2347 review 4485232710: the creator's registration fails because an identical adoption
        # of the same job holds the gallery lock and is registering the creator's link right now.
        lock = self.volume.media / ".gallery-index.lock"
        real = sink_module.register_asset

        def other_adopter_holds_the_lock(*args, **kwargs):
            lock.write_bytes(b"")  # the other adoption is inside register_asset
            raise sink_module.GalleryUnavailable("gallery_index_locked")
        with patch.object(sink_module, "register_asset", other_adopter_holds_the_lock):
            with self.assertRaisesRegex(ArtifactSinkUnavailable, "gallery_registration_failed_asset_left_unindexed"):
                self.adopt()
        self.assertTrue(lock.exists(), "the other registration's lock is not ours to remove")
        destination = self.volume.media / f"{self.expected}.mp4"
        self.assertTrue(destination.exists(), "kept: the other adoption may be indexing it")
        lock.unlink()  # the other adoption commits
        real(self.volume.media, self.volume.root, self.expected, ".mp4", len(MP4))
        self.assertEqual(self.volume.indexed(), {self.expected})
        self.assertEqual(destination.read_bytes(), MP4, "the successful caller's asset exists")

    def test_a_failed_adoption_unlinks_nothing_but_its_own_staged_name(self):
        # #2347 review 4485290339: an identical retry may have validated the file inside
        # register_asset and be about to take the lock; any unlink of the published name could
        # leave it indexing a missing file. The sink therefore never unlinks the published name.
        unlinked = []
        real_unlink = os.unlink
        real_register = sink_module.register_asset
        retry_validated = []

        def recording_unlink(path, *args, **kwargs):
            unlinked.append(Path(str(path)).name)
            return real_unlink(path, *args, **kwargs)

        def creator_fails(*args, **kwargs):
            retry_validated.append((self.volume.media / f"{self.expected}.mp4").exists())  # the retry checked it
            raise sink_module.GalleryUnavailable("gallery_index_locked")
        with patch.object(sink_module.os, "unlink", recording_unlink), \
                patch.object(sink_module, "register_asset", creator_fails):
            with self.assertRaises(ArtifactSinkUnavailable):
                self.adopt()
        self.assertEqual(retry_validated, [True])
        self.assertTrue(all(name.startswith(".kaliv-") and name.endswith(".tmp") for name in unlinked), unlinked)
        real_register(self.volume.media, self.volume.root, self.expected, ".mp4", len(MP4))  # the retry commits
        self.assertEqual((self.volume.media / f"{self.expected}.mp4").read_bytes(), MP4, "its row has its file")

    def test_no_write_reaches_the_published_file_after_adoption(self):
        with self.sink.staged(".mp4") as output:
            output.write(MP4)
            asset_id = self.sink.adopt_for_job(output, "video/mp4", JOB)
            with self.assertRaises(ValueError):
                output.write(b"tamper")
            self.assertIsNone(output._ticket.fd, "the descriptor that shares the published inode is closed at once")
        self.assertEqual((self.volume.media / f"{asset_id}.mp4").read_bytes(), MP4)

    # -- sync(): durable before the work-area copy goes (Anders, 6 Nov: generate on C:, publish on Z:) --
    def test_sync_fsyncs_the_staged_descriptor_without_revealing_it(self):
        synced = []
        real_fsync = os.fsync
        with self.sink.staged(".mp4") as output:
            output.write(MP4)
            fd = output._ticket.fd
            with patch.object(sink_module.os, "fsync", side_effect=lambda f: (synced.append(f), real_fsync(f))[1]):
                self.assertIsNone(output.sync())
            self.assertEqual(synced, [fd])
            self.assertFalse(hasattr(output, "fileno"), "sync() is not a way to the descriptor")
            asset_id = self.sink.adopt_for_job(output, "video/mp4", JOB)
            with self.assertRaises(ValueError):
                output.sync()  # after adoption the handle is spent
        self.assertEqual((self.volume.media / f"{asset_id}.mp4").read_bytes(), MP4)
        with self.assertRaises(ValueError):
            output.sync()  # and after the context

    def test_a_failed_sync_is_the_volume_being_unusable_and_publishes_nothing(self):
        import errno
        with self.sink.staged(".mp4") as output:
            output.write(MP4)
            with patch.object(sink_module.os, "fsync", side_effect=OSError(errno.ENOSPC, "No space left on device")):
                with self.assertRaisesRegex(ArtifactSinkUnavailable, "staged_video_unavailable"):
                    output.sync()
        self.assertEqual(self.volume.indexed(), set())
        self.assertEqual(self.sink._media.inspect_temporary_files(), [], "the staged name is cleaned up")

    def test_a_failed_write_is_the_volume_being_unusable_and_the_handle_is_spent(self):
        import errno
        with self.sink.staged(".mp4") as output:
            output.write(MP4[:16])
            with patch.object(sink_module.os, "write", side_effect=OSError(errno.ENOSPC, "No space left on device")):
                with self.assertRaisesRegex(ArtifactSinkUnavailable, "staged_video_unavailable"):
                    output.write(MP4[16:])
            for spent in (lambda: output.write(b"x"), output.sync,
                          lambda: self.sink.adopt_for_job(output, "video/mp4", JOB)):
                with self.assertRaises(ValueError):
                    spent()
        self.assertEqual(self.volume.indexed(), set())
        self.assertEqual(self.sink._media.inspect_temporary_files(), [], "the staged name is cleaned up")

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
