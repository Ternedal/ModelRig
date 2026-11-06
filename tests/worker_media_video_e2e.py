#!/usr/bin/env python3
"""C2: the image-to-video pipeline end to end: generated in the work area, published on the volume (test only).

Anders, 6 Nov 2026 (#2275 6686905826): ComfyUI and the job database work in a private folder on the
internal disk (the work area); a finished file is copied to the external volume, synced, published.

**Real components:**
- `ImageJobStore` in the work area, guarded like the entry point does it: the work area, then
  `MountedMediaVolume.verify` (G1), before every access;
- `MediaExecutor`;
- `ComfySupervisor`, whose `work_area` is a real `PrivateWorkArea`;
- `ComfyVideoAdapter` (#2346) driving the fake ComfyUI child process;
- the owner-gated `read_owned_source_png` (#2339);
- `ExternalStagedVideoSink` (#2347) with the real gallery index writer and catalog.

**Faked:** only the mount facts (FakeProbe: is this a mount point, which filesystem; the work area's
filesystem type) and the GPU (the fake ComfyUI).

**Asserted:**
- submit, lease, render, stage, adopt, index, get;
- another owner's source never reaches ComfyUI;
- cancel mid-render publishes nothing;
- the volume vanishing mid-render is exit 75 with nothing published. After the volume returns,
  the restart records the interrupted job as failed (the store's recovery rule; the owner
  resubmits), and a new job completes;
- after every outcome, nothing orphaned is visible: no temp or unindexed files, and nothing left
  in ComfyUI's output;
- the state a crash leaves (during the copy, or after the work-area copy is removed but before
  publication) is recovered as a failed job, never published, and C6 reports every leftover.

Run: PYTHONPATH=worker python3 tests/worker_media_video_e2e.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from app.comfy_supervisor import ComfyLaunch  # noqa: E402
from app.comfy_video_adapter import ComfyVideoAdapter  # noqa: E402
from app.gpu_lease import acquire_gpu_lease  # noqa: E402
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_executor import EXIT_SINK_UNAVAILABLE, MediaExecutor  # noqa: E402
from app.media_gallery_catalog import list_gallery  # noqa: E402
from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_source_image import read_owned_source_png  # noqa: E402
from app.media_staged_video_sink import ExternalStagedVideoSink  # noqa: E402
from app.media_volume import MARKER_NAME, MountedMediaVolume  # noqa: E402
from app.media_repair import reconcile, remove_stale_temp, remove_work_file  # noqa: E402
from app.media_work_area import PrivateWorkArea  # noqa: E402
import worker_media_volume as g1  # noqa: E402  (module import: its test classes must not run here)
from worker_comfy_image_to_video import I2V, png  # noqa: E402
from worker_comfy_supervisor import FAKE_MAIN, FakeSupervisor, free_port, wait_gone  # noqa: E402
from worker_comfy_video_adapter import raw, sha  # noqa: E402
from worker_media_generation_profiles import video_profile  # noqa: E402

GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
IMAGE_INSTANCE = "GPU-00000000-0000-0000-0000-000000000009:0123456789abcdef"
VOLUME_ID = "kaliv-e2e-volume-01"


@unittest.skipIf(os.name == "nt", "POSIX test; Windows path checks are in windows_media_volume_contract.py")
class VideoPipelineEndToEnd(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="kaliv-c2-"))
        self.root = os.path.join(self.base, "vol")
        os.mkdir(self.root)
        Path(self.root, MARKER_NAME).write_text(VOLUME_ID)
        self.media = os.path.join(self.root, "gallery")
        # The work area on the internal disk: ComfyUI's folders and the job database.
        self.work = os.path.join(self.base, "work")
        self.comfy = {n: os.path.join(self.work, "comfy", n) for n in ("input", "output", "temp", "user")}
        self.job_dir = os.path.join(self.work, "state")
        for d in (self.media, *self.comfy.values(), self.job_dir):
            os.makedirs(d)
        os.chmod(self.work, 0o700)
        fs = patch("app.media_work_area.WorkAreaProbe.containing_filesystem", return_value=("ext4", False))
        fs.start()
        self.addCleanup(fs.stop)
        # Not media: these may live anywhere.
        self.lease_dir = os.path.join(self.base, "lease")
        os.mkdir(self.lease_dir, 0o700)
        self.templates = os.path.join(self.base, "templates")
        self.state = os.path.join(self.base, "fake-comfy-state")
        os.mkdir(self.templates)
        os.mkdir(self.state)
        Path(self.templates, "wan-i2v.json").write_bytes(raw(I2V))
        self.probe = g1.FakeProbe({self.root})
        # One source of truth for "mounted": the gallery's own check asks the same probe.
        mounted = patch("app.media_gallery_catalog.os.path.ismount", side_effect=lambda p: str(p) in self.probe.mounts)
        mounted.start()
        self.addCleanup(mounted.stop)
        self.port = free_port()
        self.adapters, self.executors = [], []
        self.boot()

    def tearDown(self):
        self.stop_all()
        shutil.rmtree(self.base, ignore_errors=True)

    # -- a process lifetime: volume, store, sinks, executor ----------------------------------------

    def boot(self):
        self.volume = MountedMediaVolume(self.root, VOLUME_ID, probe=self.probe)
        self.work_area = PrivateWorkArea(self.work)
        volume, work_area, job_dir = self.volume, self.work_area, self.job_dir

        def guard():  # what media_executor_main.build_from_env installs
            work_area.require(job_dir)
            volume.verify()

        self.store = ImageJobStore(os.path.join(self.job_dir, "jobs.sqlite3"), volume_guard=guard)
        self.image_sink = ExternalMediaSink(self.media, str(self.volume.root))
        self.video_sink = ExternalStagedVideoSink(self.media, str(self.volume.root))

    def stop_all(self):
        """What process exit does: release the executor lock and stop ComfyUI."""
        for ex in self.executors:
            ex.release_lock()
        for adapter in self.adapters:
            try:
                adapter.close()
            except Exception:
                pass
        self.executors, self.adapters = [], []

    def executor(self, render_seconds="0.2"):
        profile = parse_profile(video_profile(
            profile_id="wan-i2v", tasks=["image_to_video"],
            limits={"max_prompt_chars": 200, "sizes": [[832, 480]], "max_steps": 30, "max_frames": 81},
            backend_options={"template_name": "wan-i2v.json", "template_sha256": sha(raw(I2V)), "fps": 16,
                             "max_render_seconds": 60, "max_output_bytes": 1024 * 1024, "port": self.port}))
        work_area = self.work_area

        def factory(p):
            launch = ComfyLaunch(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                                 input_directory=self.comfy["input"], output_directory=self.comfy["output"],
                                 temp_directory=self.comfy["temp"], user_directory=self.comfy["user"])
            sup = FakeSupervisor(fake_env={"FAKE_COMFY_STATE_DIR": self.state,
                                           "FAKE_COMFY_RENDER_SECONDS": render_seconds},
                                 work_area=work_area, gpu_uuid=GPU, lease_dir=self.lease_dir, launch=launch,
                                 reserve_gib=2, min_usable_gib=8, ready_timeout_s=15, stop_timeout_s=5, poll_s=0.05,
                                 base_env={"PATH": os.environ.get("PATH", "")})
            adapter = ComfyVideoAdapter(p, supervisor=sup, template_dir=self.templates,
                                        output_directory=self.comfy["output"], poll_s=0.05, settle_s=0.05)
            self.adapters.append(adapter)
            return adapter

        store, image_sink = self.store, self.image_sink
        ex = MediaExecutor(store, gpu_uuid=GPU, profiles={profile.profile_id: profile}, adapter_factory=factory,
                           lease_dir=self.lease_dir, video_sink=self.video_sink, cancel_poll_s=0.1,
                           source_reader=lambda owner, asset: read_owned_source_png(image_sink, store, owner, asset))
        self.executors.append(ex)
        return ex

    # -- fixtures --------------------------------------------------------------------------------

    def owned_source(self, owner="anders"):
        """A completed image job of `owner` whose PNG is in the gallery: what #2339 authorizes."""
        job = self.store.submit(owner, "source still", profile_id="sdxl-src", params={})["job_id"]
        self.assertEqual(self.store.claim_for(["sdxl-src"], IMAGE_INSTANCE)["id"], job)
        self.assertTrue(self.store.begin_publish(job, IMAGE_INSTANCE))
        asset = self.image_sink.publish(png(), ".png")
        self.assertTrue(self.store.complete(job, IMAGE_INSTANCE, asset))
        return asset

    def submit_video(self, asset, owner="anders"):
        return self.store.submit(owner, "the kite takes off", profile_id="wan-i2v",
                                 params={"task": "image_to_video", "width": 832, "height": 480, "steps": 20,
                                         "frames": 33, "input_asset_id": asset})["job_id"]

    def gallery(self):
        return {item["id"]: item for item in list_gallery(self.media, limit=100,
                                                          verified_volume_root=str(self.volume.root))["items"]}

    def assert_nothing_orphaned(self, temporary=()):
        self.assertEqual(sorted(self.image_sink.inspect_temporary_files()), sorted(temporary),
                         "no temporary file in the gallery beyond the expected ones")
        self.assertEqual(self.image_sink.inspect_unindexed_assets(), [], "no published but unindexed asset")
        self.assertEqual(os.listdir(self.comfy["output"]), [], "nothing left in ComfyUI's output")

    def assert_lease_free(self):
        lease = acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
        lease.release()

    # -- the tests -------------------------------------------------------------------------------

    def test_owned_source_becomes_an_indexed_video(self):
        source = self.owned_source()
        job = self.submit_video(source)
        ex = self.executor()
        ex.start()
        self.assertEqual(ex.step(), "completed")
        row = self.store.get(job, "anders")
        self.assertEqual(row["state"], "completed")
        items = self.gallery()
        self.assertIn(source, items)
        self.assertIn(row["asset_id"], items)
        self.assertEqual(items[row["asset_id"]]["kind"], "video")
        self.assertEqual(items[row["asset_id"]]["mime_type"], "video/mp4")
        self.assertIsNone(self.store.get(job, "someone-else"), "another owner cannot even see the job")
        self.assert_nothing_orphaned()
        self.stop_all()
        self.assert_lease_free()

    def test_another_owners_source_never_reaches_comfyui(self):
        source = self.owned_source(owner="sofie")
        job = self.submit_video(source, owner="anders")
        ex = self.executor()
        ex.start()
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.store.get(job, "anders")["state"], "failed")
        self.assertEqual(list(self.gallery()), [source], "only the source; no video")
        self.assertEqual(os.listdir(self.comfy["input"]), [], "the source was never staged for ComfyUI")
        self.assert_nothing_orphaned()

    def test_cancel_mid_render_publishes_nothing(self):
        source = self.owned_source()
        job = self.submit_video(source)
        ex = self.executor(render_seconds="5")
        ex.start()
        threading.Timer(1.0, lambda: self.store.request_cancel(job, "anders")).start()
        self.assertEqual(ex.step(), "cancelled")
        self.assertEqual(self.store.get(job, "anders")["state"], "cancelled")
        self.assertEqual(list(self.gallery()), [source])
        self.stop_all()
        self.assert_nothing_orphaned()
        self.assert_lease_free()

    def test_volume_lost_mid_render_is_exit_75_and_the_restart_recovers(self):
        source = self.owned_source()
        job = self.submit_video(source)
        ex = self.executor(render_seconds="3")
        threading.Timer(1.0, self.probe.mounts.clear).start()  # the disk is pulled while ComfyUI renders
        self.assertEqual(ex.run(max_steps=1), EXIT_SINK_UNAVAILABLE)
        with self.assertRaises(ArtifactSinkUnavailable):
            self.volume.verify()
        self.stop_all()  # the process exits; its ComfyUI goes with it
        # The disk comes back; the supervisor starts a new process, which pins the volume afresh.
        self.probe.mounts.add(self.root)
        self.boot()
        self.assertEqual(self.store.get(job, "anders")["state"], "running", "left for recovery, not failed")
        self.assertEqual(list(self.gallery()), [source], "nothing was published by the lost run")
        # The sink would not touch the volume while it was gone, so its staged file is still there.
        # It is never indexed (invisible in the gallery) and is left for the read-only temp inventory;
        # removing it is an operator action (C6), never automatic.
        leftover = self.image_sink.inspect_temporary_files()
        self.assertEqual(len(leftover), 1)
        self.assertRegex(leftover[0], r"^\.kaliv-[0-9a-f]{16}\.tmp$")
        self.assertNotIn(leftover[0], str(self.gallery()))
        ex2 = self.executor()
        self.assertEqual(ex2.start(), 1, "the interrupted job is recovered")
        lost = self.store.get(job, "anders")
        self.assertEqual((lost["state"], lost["asset_id"]), ("failed", None))
        again = self.submit_video(source)
        self.assertEqual(ex2.step(), "completed")
        row = self.store.get(again, "anders")
        self.assertEqual(row["state"], "completed")
        self.assertEqual(sorted(self.gallery()), sorted([source, row["asset_id"]]))
        self.assert_nothing_orphaned(temporary=leftover)

    def test_a_different_disk_at_the_same_path_stops_the_executor(self):
        source = self.owned_source()
        self.submit_video(source)
        ex = self.executor()
        ex.start()
        # Same mount point, same marker text, but another directory (another disk) is there now.
        os.rename(self.root, self.root + ".old")
        os.mkdir(self.root)
        Path(self.root, MARKER_NAME).write_text(VOLUME_ID)
        with self.assertRaises(ArtifactSinkUnavailable):
            ex.step()
        self.assertEqual(os.listdir(self.root), [MARKER_NAME], "nothing was written to the other disk")

    # -- crashes in the hand-off from the work area to the volume (ChatGPT 6686968292 items 1 and 2) --

    def crash_at(self, target: str, crash) -> int:
        """Run one job in a forked process that dies (os._exit: no finally, no cleanup) at `target`.
        Returns the job id. Afterwards the orphaned ComfyUI is killed, as the OS would on a reboot."""
        source = self.owned_source()
        job = self.submit_video(source)
        pid = os.fork()
        if pid == 0:  # the executor process
            try:
                with patch(target, crash):
                    self.executor().run(max_steps=1)
            finally:
                os._exit(3)  # never back into unittest; reaching here means it did not crash
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0, "the executor died at the crash point")
        comfy = int(Path(self.state, "pid").read_text())
        try:
            os.kill(comfy, 9)
        except ProcessLookupError:
            pass
        self.assertTrue(wait_gone(comfy, 10))
        self.assertIn(self.store.get(job, "anders")["state"], ("running", "publishing"), "nobody recorded an outcome")
        # Time passes before the operator looks: every leftover is older than C6's minimum age.
        hours_ago = time.time() - 7 * 3600
        for top in (self.media, *self.comfy.values()):
            for dirpath, _, files in os.walk(top):
                for name in files:
                    os.utime(os.path.join(dirpath, name), (hours_ago, hours_ago), follow_symlinks=False)
        return job, source

    def restart_and_report(self, job, source):
        """The next process: recovery fails the job; nothing reaches the gallery; C6 sees the rest."""
        self.boot()
        ex = self.executor()
        self.assertEqual(ex.start(), 1, "the interrupted job is recovered")
        self.assertEqual(self.store.get(job, "anders")["state"], "failed")
        self.assertEqual(list(self.gallery()), [source], "nothing partial or unrecorded is visible")
        self.assertEqual(self.image_sink.inspect_unindexed_assets(), [], "and nothing was published unindexed")
        ex.release_lock()
        return reconcile(self.image_sink, os.path.join(self.job_dir, "jobs.sqlite3"), lease_dir=self.lease_dir,
                         work_area=self.work_area,
                         work_dirs=[self.comfy["input"], self.comfy["output"], self.comfy["temp"]])

    @unittest.skipUnless(hasattr(os, "fork"), "needs fork to die without running cleanup")
    def test_a_crash_during_the_copy_leaves_nothing_visible_and_c6_finds_every_leftover(self):
        def die_halfway(adapter, source, sink_file):
            data = Path(source).read_bytes()
            sink_file.write(data[:len(data) // 2])
            os._exit(0)

        job, source = self.crash_at("app.comfy_video_adapter.ComfyVideoAdapter._copy_validated", die_halfway)
        report = self.restart_and_report(job, source)
        temp = report["stale_temporary_files"]
        self.assertEqual(len(temp), 1, "the partial staged copy on the volume")
        work = {(os.path.basename(f["directory"]), f["kind"]) for f in report["work_area_residue"]}
        self.assertEqual(work, {("output", "file"), ("input", "file")}, "the render and the staged source on C:")
        self.assertEqual(report["unindexed_assets"], [])
        # The operator removes each one, named exactly (C6); then the pipeline works as before.
        for f in report["work_area_residue"]:
            remove_work_file(self.work_area, f["directory"], f["path"], device=f["device"], inode=f["inode"],
                             lease_dir=self.lease_dir, job_db=os.path.join(self.job_dir, "jobs.sqlite3"))
        remove_stale_temp(self.image_sink, temp[0]["name"], device=temp[0]["device"], inode=temp[0]["inode"],
                          lease_dir=self.lease_dir)
        again = self.submit_video(source)
        ex = self.executor()
        ex.start()
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(self.store.get(again, "anders")["state"], "completed")
        self.assert_nothing_orphaned()
        self.assertEqual(os.listdir(self.comfy["input"]), [])

    @unittest.skipUnless(hasattr(os, "fork"), "needs fork to die without running cleanup")
    def test_a_crash_after_the_work_area_copy_is_removed_leaves_a_complete_unpublished_copy(self):
        sizes = []

        def die_before_publishing(sink, handle, mime_type, job_key):
            sizes.append(handle._ticket.written)
            os._exit(0)

        job, source = self.crash_at("app.media_staged_video_sink.ExternalStagedVideoSink.adopt_for_job",
                                    die_before_publishing)
        self.assertEqual(os.listdir(self.comfy["output"]), [], "the work-area copy was already removed")
        self.assertEqual(os.listdir(self.comfy["input"]), [], "and the staged source with it")
        report = self.restart_and_report(job, source)
        self.assertEqual(report["work_area_residue"], [], "nothing left on C:")
        temp = report["stale_temporary_files"]
        self.assertEqual(len(temp), 1, "the complete, synced copy waits on the volume, unpublished")
        staged = Path(self.media, temp[0]["name"]).read_bytes()
        self.assertEqual(staged[4:8], b"ftyp", "a whole MP4, not a partial one")
        self.assertGreater(len(staged), 12)


if __name__ == "__main__":
    unittest.main()
