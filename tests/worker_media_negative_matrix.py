#!/usr/bin/env python3
"""C2 negatives: a crash at every step of the C:/Z: hand-off, a symlink swapped in at the copy, and
no prompt or owner in any log, event or report (ChatGPT 6694053328, P1 and P2).

Same real pipeline as worker_media_video_e2e.py (its setup and helpers are reused, its tests are
not): the job store in the private work area, the executor, the supervised fake ComfyUI, the
adapter, the staged sink, the gallery index, C6.

**Simulated, not physical.** POSIX only, with the mount facts faked. The Windows behaviour
(reparse points, DACLs, sharing violations, a real Z: unplugged) is proven only by the Windows
contract tests and the R17 rig pack; physical Windows proof is BLOCKED until Anders runs it.

**The crash matrix.** Each point kills the executor with os._exit (no finally, no cleanup), then
starts a new one. After every point:
- the job is terminal (failed, with the code for where it died) and is never claimed again;
- nothing partial is visible, and every index row has its whole file (no orphan index);
- nobody can retrieve a file whose job did not complete, and the store's owner authority
  (`owns_completed_asset`, `completed_assets_for`) never counts it, so an owner-filtered gallery
  never lists it (ChatGPT's projection is checked too once it is on this branch);
- C6 attributes what is left to the job, with a definite class (never "unknown"), read-only;
- a new job completes.

Run: PYTHONPATH=worker python3 tests/worker_media_negative_matrix.py
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from app.image_job_store import INTERRUPTED_BY_RESTART, INTERRUPTED_DURING_PUBLICATION  # noqa: E402
from app.media_executor import EXIT_SINK_UNAVAILABLE  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable  # noqa: E402
from app.media_recovery_inventory import recovery_inventory  # noqa: E402
from app.media_repair import reconcile  # noqa: E402
import worker_media_video_e2e as e2e  # noqa: E402  (module import: its test classes must not run here)

# The e2e class's setup and helpers, without its tests (they run in their own file).
Harness = type("Harness", (unittest.TestCase,), {
    k: v for k, v in vars(e2e.VideoPipelineEndToEnd).items()
    if not k.startswith("test_") and (not k.startswith("__") or k.startswith("__unittest"))})


def die(*args, **kwargs):
    os._exit(0)


def die_mid_write():
    from app.media_staged_video_sink import _StagedVideoWriter
    real, calls = _StagedVideoWriter.write, []

    def write(writer, data):  # the header went through; the process dies mid-chunk
        calls.append(len(data))
        if len(calls) == 1:
            return real(writer, data)
        real(writer, bytes(data)[:len(data) // 2])
        os._exit(0)
    return write


# (name, patch target, crash, stage when it died, C6 class, the C: copy left, published files left unindexed)
CRASH_POINTS = (
    ("mid_copy", "app.media_staged_video_sink._StagedVideoWriter.write", die_mid_write,
     "running", "interrupted_copy", True, 0),
    ("before_sync", "app.media_staged_video_sink._StagedVideoWriter.sync", lambda: die,
     "running", "interrupted_copy", True, 0),
    ("after_sync_before_publication", "app.media_staged_video_sink.ExternalStagedVideoSink.adopt_for_job",
     lambda: die, "publishing", "crash_after_sync_before_publication", True, 0),
    ("published_before_index", "app.media_staged_video_sink.register_asset", lambda: die,
     "publishing", "published_unindexed", True, 1),
    ("indexed_before_cleanup", "app.comfy_video_adapter.ComfyVideoAdapter._remove_job_outputs", lambda: die,
     "publishing", "crash_after_publication_before_cleanup", True, 0),
    ("cleaned_before_complete", "app.image_job_store.ImageJobStore.complete", lambda: die,
     "publishing", "published_not_recorded", False, 0),
)


@unittest.skipIf(os.name == "nt", "POSIX test; Windows path checks are in the windows_* contract tests")
@unittest.skipUnless(hasattr(os, "fork"), "needs fork to die without running cleanup")
class CrashMatrix(Harness):
    def raw_row(self, job):
        with sqlite3.connect(os.path.join(self.job_dir, "jobs.sqlite3")) as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute("SELECT * FROM image_jobs WHERE id=?", (job,)).fetchone())

    def assert_owner_projection(self, source):
        """ChatGPT's owner-filtered gallery (feat/media-owner-gallery-filter), once it is on this
        branch: after any crash, only completed assets are listed or opened, and only for their owner."""
        try:
            from app.media_gallery_owner import list_owned_gallery, open_owned_asset
            from app.media_gallery_asset import GalleryAssetNotFound
        except ImportError:
            return  # not merged here yet; the store authority above is checked either way
        listed = list_owned_gallery(self.store, "anders", self.media, verified_volume_root=self.root, limit=50)
        self.assertEqual([i["id"] for i in listed["items"]], [source])
        for asset_id in self.gallery():
            if asset_id != source:
                with self.assertRaises(GalleryAssetNotFound):
                    open_owned_asset(self.store, "anders", self.media, self.root, asset_id)
        with self.assertRaises(GalleryAssetNotFound):
            open_owned_asset(self.store, "mallory", self.media, self.root, source)
        handle, _ = open_owned_asset(self.store, "anders", self.media, self.root, source)
        handle.close()

    def run_point(self, target, crash, died_in, expected_class, c_copy_left, unindexed):
        job, source = self.crash_at(target, crash())
        dead = self.raw_row(job)
        self.assertEqual(dead["state"], died_in)
        self.boot()
        ex = self.executor()
        self.assertEqual(ex.start(), 1, "the interrupted job is recovered")
        row = self.raw_row(job)
        expected_error = INTERRUPTED_DURING_PUBLICATION if died_in == "publishing" else INTERRUPTED_BY_RESTART
        self.assertEqual((row["state"], row["error"], row["asset_id"]), ("failed", expected_error, None))
        self.assertEqual(row["claimed_by"], dead["claimed_by"], "recovery fails the job; it never claims it")
        self.assertEqual(ex.step(), "idle", "a recovered job is never run again")
        self.assertEqual(self.raw_row(job), row)

        # Nothing partial is visible; every index row has its file; nobody can fetch an unowned file.
        db = os.path.join(self.job_dir, "jobs.sqlite3")
        report = reconcile(self.image_sink, db, lease_dir=self.lease_dir, work_area=self.work_area,
                           work_dirs=[self.comfy["output"]])
        self.assertEqual(report["indexed_but_missing"], [], "no orphan index row")
        self.assertEqual(report["counts"]["unindexed"], unindexed)
        owned = self.store.completed_assets_for("anders")
        self.assertIn(source, owned)
        for asset_id, item in self.gallery().items():
            if asset_id == source:
                continue
            path = Path(self.media, asset_id + ".mp4")
            self.assertEqual(path.stat().st_size, item["size_bytes"], "an indexed file is whole")
            self.assertIsNone(self.retrieve("anders", asset_id), "its job failed: nobody may fetch it")
            # The authority a gallery list filters with (#2275 6697074518): never owned, by anyone.
            self.assertNotIn(asset_id, owned)
            self.assertFalse(self.store.owns_completed_asset("anders", asset_id))
        self.assert_owner_projection(source)
        self.assertEqual(bool(report["work_area_residue"]), c_copy_left, "the C: copy is kept until published")

        # C6 names it: attributed to the job, a definite class, and it changes nothing.
        ex.release_lock()
        before = {p: p.stat().st_mtime_ns for p in Path(self.base).rglob("*") if p.is_file()}
        inventory = recovery_inventory(self.image_sink, db, work_area=self.work_area,
                                       output_dir=self.comfy["output"], lease_dir=self.lease_dir)
        self.assertEqual(inventory["status"], "ok")
        entries = {e["job_id"]: e for e in inventory["jobs"]}
        self.assertIn(job, entries, inventory)
        self.assertEqual(entries[job]["classification"], expected_class, entries[job])
        self.assertEqual({p: p.stat().st_mtime_ns for p in Path(self.base).rglob("*") if p.is_file()}, before,
                         "the inventory is read-only")

        # The pipeline still works.
        ex2 = self.executor()
        ex2.start()
        again = self.submit_video(source)
        self.assertEqual(ex2.step(), "completed")
        self.assertEqual(self.store.get(again, "anders")["state"], "completed")


def _point_test(point):
    name, target, crash, died_in, expected_class, c_copy_left, unindexed = point

    def test(self):
        self.run_point(target, crash, died_in, expected_class, c_copy_left, unindexed)
    test.__name__ = f"test_crash_{name}"
    test.__doc__ = f"killed at {target.rsplit('.', 1)[-1]}: {expected_class}"
    return test


for _point in CRASH_POINTS:
    setattr(CrashMatrix, f"test_crash_{_point[0]}", _point_test(_point))


@unittest.skipIf(os.name == "nt", "POSIX test; Windows path checks are in the windows_* contract tests")
class SwappedOutput(Harness):
    """A link swapped in after the output was found, before the copy opens it, is never followed."""

    def outside_copy(self, name):
        """A valid MP4 outside the work area, different from the render: what an attacker would plant."""
        outside = Path(self.base, "outside")
        outside.mkdir(exist_ok=True)
        planted = outside / name
        return outside, planted

    def run_swapped(self, swap):
        from app.comfy_video_adapter import ComfyVideoAdapter
        real = ComfyVideoAdapter._copy_validated
        planted_bytes = {}

        def swapped(adapter, source, sink_file):
            planted_bytes["data"] = swap(Path(source))
            return real(adapter, source, sink_file)
        source = self.owned_source()
        job = self.submit_video(source)
        ex = self.executor()
        ex.start()
        with patch.object(ComfyVideoAdapter, "_copy_validated", swapped):
            self.assertEqual(ex.step(), "failed")
        row = self.store.get(job, "anders")
        self.assertEqual((row["state"], row["asset_id"]), ("failed", None))
        self.assertEqual(list(self.gallery()), [source], "nothing published")
        self.assertEqual(self.image_sink.inspect_temporary_files(), [], "the staged copy was removed")
        data = planted_bytes["data"]
        for path in Path(self.root).rglob("*"):
            if path.is_file():
                self.assertNotIn(data[-64:], path.read_bytes(), f"the planted file reached the volume: {path}")
        return data

    def test_a_file_swapped_for_a_link_is_refused_and_its_target_never_read(self):
        def swap(source):
            outside, planted = self.outside_copy(source.name)
            data = source.read_bytes()[:-8] + b"PLANTED!"
            planted.write_bytes(data)
            source.unlink()
            source.symlink_to(planted)
            return data
        data = self.run_swapped(swap)
        self.assertEqual(Path(self.base, "outside", os.listdir(Path(self.base, "outside"))[0]).read_bytes(), data,
                         "the link's target is untouched")
        self.assertFalse(any(Path(self.comfy["output"]).iterdir()), "the link itself is cleaned up, not followed")

    def test_an_output_folder_swapped_for_a_link_is_refused(self):
        def swap(source):
            outside, planted = self.outside_copy(source.name)
            data = source.read_bytes()[:-8] + b"PLANTED!"
            planted.write_bytes(data)
            moved = Path(self.base, "real-output")
            os.rename(self.comfy["output"], moved)
            os.symlink(outside, self.comfy["output"])
            return data
        self.run_swapped(swap)
        self.assertTrue(Path(self.base, "outside").is_dir(), "the link's target folder is untouched")


@unittest.skipIf(os.name == "nt", "POSIX test")
class TamperedSource(Harness):
    """ChatGPT 6698426548 (#2346 boundary): the adapter delegates PNG validation to the source
    reader, so prove it end to end. The owner's completed source PNG is altered on Z: after it was
    published (bit rot, a tool, a person). The job must fail with source_image_unavailable before
    any GPU work: nothing staged for ComfyUI, nothing published, the altered file left as it is."""

    def tamper_and_run(self, tamper):
        source = self.owned_source()
        path = Path(self.media, source + ".png")
        tamper(path)
        altered = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        job = self.submit_video(source)
        ex = self.executor()
        ex.start()
        self.assertEqual(ex.step(), "failed")
        row = self.store.get(job, "anders")
        self.assertEqual((row["state"], row["error"], row["asset_id"]), ("failed", "source_image_unavailable", None))
        self.assertEqual(os.listdir(self.comfy["input"]), [], "the source was never staged for ComfyUI")
        self.assertEqual(os.listdir(self.comfy["output"]), [], "no render")
        self.assertEqual(list(self.gallery()), [source], "no video published")
        if altered is not None:
            self.assertEqual(path.read_bytes(), altered, "the reader never repairs or rewrites the source")

    def test_a_flipped_byte_fails_the_png_crc(self):
        def flip(path):
            data = bytearray(path.read_bytes())
            at = data.index(b"IDAT") + 8  # inside the image data: the chunk CRC no longer matches
            data[at] ^= 0xFF
            path.write_bytes(bytes(data))
        self.tamper_and_run(flip)

    def test_a_truncated_png(self):
        self.tamper_and_run(lambda path: path.write_bytes(path.read_bytes()[:-20]))

    def test_other_bytes_of_the_same_size(self):
        self.tamper_and_run(lambda path: path.write_bytes(b"\0" * path.stat().st_size))

    def test_a_link_in_place_of_the_source(self):
        def link(path):
            elsewhere = Path(self.base, "elsewhere.png")
            elsewhere.write_bytes(path.read_bytes())  # even the identical image, behind a link
            path.unlink()
            path.symlink_to(elsewhere)
        self.tamper_and_run(link)

    def test_a_source_gone_from_the_volume(self):
        self.tamper_and_run(lambda path: path.unlink())


@unittest.skipIf(os.name == "nt", "POSIX test")
class NoPromptOrOwnerAnywhere(Harness):
    """ChatGPT 6694053328 P1/P4: across success, failure, cancel, a lost volume, restart recovery
    and C6, no log record, executor event or report contains the prompt or the owner."""

    PROMPT = "PROMPT-SENTINEL-7f3a a kite over the harbour"
    OWNER = "owner-sentinel-91c2"

    def submit(self):
        return self.store.submit(self.OWNER, self.PROMPT, profile_id="wan-t2v",
                                 params={"task": "text_to_video", "width": 832, "height": 480, "steps": 20,
                                         "frames": 33})["job_id"]

    def test_nothing_operator_facing_ever_carries_the_prompt_or_owner(self):
        records: list[str] = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))
                if record.exc_info:
                    records.append(logging.Formatter().formatException(record.exc_info))
        handler = Capture(level=logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        events: list[str] = []

        def run(ex, **kwargs):
            ex.events.sink = lambda event: events.append(json.dumps({"event": event}))
            return ex

        # A job that completes, one whose volume sync fails, one cancelled, one whose volume vanishes.
        ex = run(self.executor())
        ex.start()
        self.submit()
        self.assertEqual(ex.step(), "completed")
        self.stop_all()
        self.boot()
        ex = run(self.executor())  # run() starts the executor itself
        failing = self.submit()
        with patch("app.media_staged_video_sink._StagedVideoWriter.sync",
                   side_effect=ArtifactSinkUnavailable("staged_video_unavailable")):
            self.assertEqual(ex.run(max_steps=1), EXIT_SINK_UNAVAILABLE)
        self.stop_all()
        self.boot()
        ex = run(self.executor(render_seconds="5"))
        ex.start()
        cancelled = self.submit()
        import threading
        threading.Timer(1.0, lambda: self.store.request_cancel(cancelled, self.OWNER)).start()
        self.assertEqual(ex.step(), "cancelled")
        self.stop_all()
        self.boot()
        ex = run(self.executor(render_seconds="3"))
        self.submit()
        threading.Timer(1.0, self.probe.mounts.clear).start()
        self.assertEqual(ex.run(max_steps=1), EXIT_SINK_UNAVAILABLE)
        self.stop_all()
        self.probe.mounts.add(self.root)
        self.boot()
        ex = run(self.executor())
        self.assertGreaterEqual(ex.start(), 1, "restart recovery")
        ex.release_lock()
        db = os.path.join(self.job_dir, "jobs.sqlite3")
        report = reconcile(self.image_sink, db, lease_dir=self.lease_dir, work_area=self.work_area,
                           work_dirs=[self.comfy["output"], self.comfy["temp"]])
        inventory = recovery_inventory(self.image_sink, db, work_area=self.work_area,
                                       output_dir=self.comfy["output"], lease_dir=self.lease_dir)
        self.assertEqual(self.store.get(failing, self.OWNER)["state"], "failed")

        text = "\n".join(records + events + [json.dumps(report), json.dumps(inventory)])
        self.assertTrue(events and records, "something was captured, or the check proves nothing")
        for secret in (self.PROMPT, "PROMPT-SENTINEL", self.OWNER, "owner-sentinel"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
