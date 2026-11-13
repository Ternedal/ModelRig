#!/usr/bin/env python3
"""C6: media volume reconciliation and the two explicit operator repairs.

The fixtures use the real gallery store, the index writer, ImageJobStore and the executor
locks. Only "is the volume root a mount point" is patched.

Run: PYTHONPATH=worker python3 tests/worker_media_repair.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.gpu_lease import acquire_executor_lock  # noqa: E402
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_gallery_catalog import list_gallery  # noqa: E402
from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable  # noqa: E402
from app.media_repair import RepairRefused, adopt, reconcile, remove_stale_temp, remove_work_file  # noqa: E402
from app.media_volume import MARKER_NAME  # noqa: E402
from app.media_work_area import PrivateWorkArea  # noqa: E402
from worker_media_volume import VOLUME_ID, FakeProbe  # noqa: E402

GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
DEAD = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab:00000000000000aa"
LIVE = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab:00000000000000bb"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SECRET_PROMPT, SECRET_OWNER = "SECRET-PROMPT-7731", "owner-secret-42"


class MediaRepairTests(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="kaliv-c6-"))
        self.volume = os.path.join(self.base, "vol")
        self.media = os.path.join(self.volume, "gallery")
        os.makedirs(self.media)
        self.lease = os.path.join(self.base, "lease")
        os.mkdir(self.lease, 0o700)
        self.mounted = {self.volume}
        Path(self.volume, MARKER_NAME).write_text(VOLUME_ID, encoding="ascii")  # G1's marker
        self.probe = FakeProbe(())
        self.probe.mounts = self.mounted  # the same set: unmounting in a test unmounts for the CLI too
        patcher = patch("app.media_gallery_catalog.os.path.ismount", side_effect=lambda p: str(p) in self.mounted)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sink = ExternalMediaSink(self.media, self.volume)
        # Anders, 6 Nov: the job database is in the private work area on the internal disk.
        self.work = os.path.join(self.base, "work")
        for sub in ("state", "comfy/output", "comfy/temp", "comfy/input"):
            os.makedirs(os.path.join(self.work, sub))
        os.chmod(self.work, 0o700)
        fs = patch("app.media_work_area.WorkAreaProbe.containing_filesystem", return_value=("ext4", False))
        fs.start()
        self.addCleanup(fs.stop)
        self.area = PrivateWorkArea(self.work)
        self.output = os.path.join(self.work, "comfy", "output")
        self.temp = os.path.join(self.work, "comfy", "temp")
        self.db = os.path.join(self.work, "state", "jobs.sqlite3")
        self.store = ImageJobStore(self.db)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    # -- fixtures --------------------------------------------------------------------------------

    def job(self, *, publish=True, complete=True, register=False, data=PNG):
        """An executor job that got as far as the flags say."""
        job = self.store.submit(SECRET_OWNER, SECRET_PROMPT, profile_id="sdxl", params={})["job_id"]
        self.assertEqual(self.store.claim_for(["sdxl"], DEAD)["id"], job)
        self.assertTrue(self.store.begin_publish(job, DEAD))
        asset = None
        if publish:
            asset = (self.sink.publish_and_register_for_job if register else self.sink.publish_for_job)(job, data, ".png")
        if complete:
            self.assertTrue(self.store.complete(job, DEAD, asset))
        return job, asset

    def stale(self, name=".kaliv-abcdef1234.tmp", age_s=7 * 3600):
        path = Path(self.media, name)
        path.write_bytes(b"partial")
        then = time.time() - age_s
        os.utime(path, (then, then))
        info = path.lstat()
        return name, info.st_dev, info.st_ino

    def report(self, **kw):
        return reconcile(self.sink, self.db, lease_dir=self.lease, **kw)

    # -- report ----------------------------------------------------------------------------------

    def test_a_clean_volume_reports_nothing(self):
        self.job(register=True)
        r = self.report()
        self.assertEqual(r["schema"], "kaliv-media-repair-report/v1")
        for key in ("unindexed_assets", "indexed_but_missing", "completed_jobs_without_asset",
                    "stale_temporary_files", "quarantined", "executors_running"):
            self.assertEqual(r[key], [], key)

    def test_the_report_never_contains_a_prompt_or_owner(self):
        self.job()
        self.job(complete=False)
        text = json.dumps(self.report())
        self.assertNotIn(SECRET_PROMPT, text)
        self.assertNotIn(SECRET_OWNER, text)

    def test_completed_job_whose_index_row_is_missing_is_adoptable_and_adopt_registers_it(self):
        job, asset = self.job()  # crash between publication and registration, completion recorded
        (entry,) = self.report()["unindexed_assets"]
        self.assertEqual((entry["asset_id"], entry["status"], entry["job_id"]), (asset, "adoptable", job))
        result = adopt(self.sink, self.db, asset, lease_dir=self.lease)
        self.assertEqual(result, {"adopted": asset, "kind": "image", "job_id": job})
        items = list_gallery(self.media, verified_volume_root=self.volume)["items"]
        self.assertEqual([i["id"] for i in items], [asset])
        self.assertEqual(self.report()["unindexed_assets"], [])
        with self.assertRaisesRegex(RepairRefused, "not_an_unindexed_asset"):
            adopt(self.sink, self.db, asset, lease_dir=self.lease)

    def test_interrupted_publication_is_reported_but_never_adopted(self):
        job, asset = self.job(complete=False)
        self.store.recover_gpu(GPU, LIVE)  # the restart fails the publishing job
        (entry,) = self.report()["unindexed_assets"]
        self.assertEqual((entry["status"], entry["job_error"]), ("job_failed", "interrupted_during_publication"))
        with self.assertRaisesRegex(RepairRefused, "not_adoptable:job_failed"):
            adopt(self.sink, self.db, asset, lease_dir=self.lease)
        self.assertFalse(Path(self.media, "gallery-index.json").exists(), "nothing was registered")

    def test_a_file_without_any_job_is_reported_as_such(self):
        Path(self.media, "f" * 32 + ".png").write_bytes(PNG)
        (entry,) = self.report()["unindexed_assets"]
        self.assertEqual((entry["status"], entry["job_id"]), ("no_job", None))
        with self.assertRaisesRegex(RepairRefused, "not_adoptable:no_job"):
            adopt(self.sink, self.db, "f" * 32, lease_dir=self.lease)

    def test_index_rows_without_files_and_completed_jobs_without_assets(self):
        _, asset = self.job(register=True)
        os.unlink(os.path.join(self.media, asset + ".png"))
        job, lost = self.job()  # completed, never indexed, and then its file is gone too
        os.unlink(os.path.join(self.media, lost + ".png"))
        r = self.report()
        self.assertEqual(r["indexed_but_missing"], [{"asset_id": asset, "kind": "image"}])
        self.assertEqual(r["completed_jobs_without_asset"], [{"job_id": job, "asset_id": lost}])

    # -- stale temporary files ---------------------------------------------------------------

    def test_only_old_temp_files_are_candidates(self):
        name, dev, ino = self.stale()
        self.stale(name=".kaliv-young00001.tmp", age_s=0)
        r = self.report()
        self.assertEqual([c["name"] for c in r["stale_temporary_files"]], [name])
        self.assertEqual((r["stale_temporary_files"][0]["device"], r["stale_temporary_files"][0]["inode"]), (dev, ino))

    def test_remove_stale_temp_removes_exactly_the_named_file(self):
        name, dev, ino = self.stale()
        self.assertEqual(remove_stale_temp(self.sink, name, device=dev, inode=ino, lease_dir=self.lease),
                         {"removed": name, "size_bytes": 7})
        self.assertFalse(Path(self.media, name).exists())
        self.assertEqual(self.report()["quarantined"], [])

    def test_remove_stale_temp_refuses_anything_else(self):
        name, dev, ino = self.stale()
        with patch("app.media_repair.os.rename") as rename:
            with self.assertRaisesRegex(RepairRefused, "identity_changed"):
                remove_stale_temp(self.sink, name, device=dev, inode=ino + 1, lease_dir=self.lease)
        rename.assert_not_called()  # refused before anything is captured
        young, ydev, yino = self.stale(name=".kaliv-young00001.tmp", age_s=0)
        with self.assertRaisesRegex(RepairRefused, "not_a_stale_candidate"):
            remove_stale_temp(self.sink, young, device=ydev, inode=yino, lease_dir=self.lease)
        for bad in ("gallery-index.json", "../x.tmp", ".kaliv-x.tmp", "a" * 32 + ".png"):
            with self.assertRaisesRegex(RepairRefused, "not_a_temporary_name"):
                remove_stale_temp(self.sink, bad, device=dev, inode=ino, lease_dir=self.lease)
        self.assertTrue(Path(self.media, name).exists() and Path(self.media, young).exists())

    def test_a_swapped_file_is_put_back_not_removed(self):
        name, dev, ino = self.stale()
        # The name now holds a different file (same name, new inode), but the report still matches the
        # old identity: simulate the swap between the candidate check and the capture.
        real_rename = os.rename

        def swap_then_rename(src, dst):
            if str(src).endswith(name):
                # Another file takes the name first (both exist at once, so the inode cannot be reused).
                Path(str(src) + ".new").write_bytes(b"someone else's")
                real_rename(str(src) + ".new", src)
            return real_rename(src, dst)
        with patch("app.media_repair.os.rename", side_effect=swap_then_rename):
            with self.assertRaisesRegex(RepairRefused, "identity_changed"):
                remove_stale_temp(self.sink, name, device=dev, inode=ino, lease_dir=self.lease)
        self.assertEqual(Path(self.media, name).read_bytes(), b"someone else's")
        self.assertEqual(self.report()["quarantined"], [])

    # -- executors and the volume ----------------------------------------------------------------

    def test_repairs_refuse_while_an_executor_runs_and_the_report_says_so(self):
        _, asset = self.job()
        name, dev, ino = self.stale()
        lock = acquire_executor_lock(GPU, lease_dir=self.lease)
        try:
            self.assertEqual(self.report()["executors_running"], [GPU])
            with self.assertRaisesRegex(RepairRefused, "executor_running"):
                adopt(self.sink, self.db, asset, lease_dir=self.lease)
            with self.assertRaisesRegex(RepairRefused, "executor_running"):
                remove_stale_temp(self.sink, name, device=dev, inode=ino, lease_dir=self.lease)
        finally:
            lock.release()
        self.assertEqual(self.report()["executors_running"], [])
        adopt(self.sink, self.db, asset, lease_dir=self.lease)

    def test_an_absent_volume_inspects_nothing(self):
        self.mounted.clear()
        with patch("app.media_repair._jobs") as jobs, self.assertRaises(ArtifactSinkUnavailable):
            self.report()
        jobs.assert_not_called()  # nothing is inspected without the volume

    # -- the work area on the internal disk (Anders, 6 Nov; ChatGPT 6686968292 item 2) -----------

    def leftover(self, directory, relative, data=b"partial render", age_s=7 * 3600):
        path = Path(directory, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        then = time.time() - age_s
        os.utime(path, (then, then))
        info = path.lstat()
        return relative, info.st_dev, info.st_ino

    def residue(self, *dirs, **kw):
        return self.report(work_area=self.area, work_dirs=list(dirs or (self.output, self.temp)), **kw)["work_area_residue"]

    def test_work_area_residue_is_reported_old_files_only_never_the_job_database(self):
        self.job(complete=False)
        rel, dev, ino = self.leftover(self.output, "kaliv_00001_.mp4")
        self.leftover(self.temp, os.path.join("frames", "f001.png"))
        self.leftover(self.output, "young.mp4", age_s=0)
        os.symlink(self.volume, os.path.join(self.temp, "a-link"))
        found = self.residue(self.output, self.temp)
        self.assertEqual(sorted((os.path.basename(f["directory"]), f["path"], f["kind"]) for f in found),
                         [("output", "kaliv_00001_.mp4", "file"), ("temp", "a-link", "link"),
                          ("temp", os.path.join("frames", "f001.png"), "file")])
        # The job database and its sidecars are never residue, even in a folder that is scanned.
        # (Called directly: fake sidecars next to the real database would make SQLite refuse to read it.)
        from app.media_repair import work_area_residue
        side = os.path.join(self.work, "comfy", "input")
        fake_db = os.path.join(side, "jobs.sqlite3")
        for suffix in ("", "-wal", "-shm", "-journal"):
            self.leftover(side, "jobs.sqlite3" + suffix)
        self.leftover(side, "source.png")
        listed = work_area_residue(self.area, [side], job_db=fake_db)
        self.assertEqual([f["path"] for f in listed], ["source.png"])
        self.assertEqual(len(work_area_residue(self.area, [side], job_db=None)), 5, "only the named database is excluded")
        entry = next(f for f in found if f["path"] == rel)
        self.assertEqual((entry["device"], entry["inode"], entry["size_bytes"]), (dev, ino, 14))
        r = self.report(work_area=self.area, work_dirs=[self.output])
        self.assertEqual(r["counts"]["work_area_residue"], 1)
        self.assertNotIn(SECRET_PROMPT, json.dumps(r))
        self.assertIsNone(self.report()["work_area_residue"], "not asked for: not reported")

    def test_a_file_that_vanishes_or_is_denied_while_listed_is_skipped_or_refused(self):
        """ChatGPT 6694053328 P1: between the listing and the stat, a file can be removed, or (on
        Windows) a locked or denied entry can refuse even its attributes."""
        from app.media_repair import RepairRefused, work_area_residue
        self.leftover(self.output, "gone.mp4")
        self.leftover(self.output, "kept.mp4")
        real = os.scandir

        class Entry:
            def __init__(self, entry, error):
                self._entry, self._error = entry, error

            def __getattr__(self, name):
                return getattr(self._entry, name)

            def stat(self, **kwargs):
                if self._error:
                    raise self._error
                return self._entry.stat(**kwargs)

        def listing(error):
            def scandir(path="."):
                with real(path) as it:
                    return iter([Entry(e, error if e.name == "gone.mp4" else None) for e in it])
            return patch("app.media_repair.os.scandir", side_effect=scandir)

        with listing(FileNotFoundError(2, "removed")):
            self.assertEqual([f["path"] for f in work_area_residue(self.area, [self.output])], ["kept.mp4"])
        for error in (PermissionError(13, "Access is denied"), OSError(32, "in use by another process")):
            with self.subTest(error=error), listing(error), self.assertRaisesRegex(RepairRefused, "^work_directory_unreadable$"):
                work_area_residue(self.area, [self.output])

    def test_work_dirs_must_be_scratch_folders_inside_the_private_work_area(self):
        with self.assertRaisesRegex(RepairRefused, "not_a_work_scratch_directory"):
            self.residue(self.work)
        with self.assertRaisesRegex(ArtifactSinkUnavailable, "media_work_path_outside_work_area"):
            self.residue(self.media)
        os.symlink(self.output, os.path.join(self.work, "linked"))
        with self.assertRaises(ArtifactSinkUnavailable):
            self.residue(os.path.join(self.work, "linked"))
        os.chmod(self.work, 0o755)
        with self.assertRaisesRegex(ArtifactSinkUnavailable, "media_work_area_not_private"):
            self.residue(self.output)

    def test_remove_work_file_removes_exactly_the_named_file(self):
        rel, dev, ino = self.leftover(self.output, "kaliv_00001_.mp4")
        self.assertEqual(remove_work_file(self.area, self.output, rel, device=dev, inode=ino, lease_dir=self.lease,
                                          job_db=self.db),
                         {"removed": rel, "directory": self.output, "size_bytes": 14})
        self.assertFalse(Path(self.output, rel).exists())
        self.assertEqual(self.report(work_area=self.area, work_dirs=[self.output])["quarantined"], [])

    def test_remove_work_file_refuses_anything_else(self):
        rel, dev, ino = self.leftover(self.output, "kaliv_00001_.mp4")
        young, ydev, yino = self.leftover(self.output, "young.mp4", age_s=0)
        os.symlink(Path(self.output, rel), Path(self.output, "a-link"))
        state = os.path.join(self.work, "state")
        db = Path(self.db).lstat()
        cases = [
            (self.output, rel, dev, ino + 1, "identity_changed"),
            (self.output, young, ydev, yino, "not_a_residue_file"),
            (self.output, "a-link", dev, ino, "not_a_residue_file"),
            (state, "jobs.sqlite3", db.st_dev, db.st_ino, "not_a_residue_file"),
            (self.output, "../temp/x", dev, ino, "not_a_relative_path"),
            (self.output, "/etc/passwd", dev, ino, "not_a_relative_path"),
            (self.output, "C:/Windows/x", dev, ino, "not_a_relative_path"),
            (self.output, "kaliv.mp4:stream", dev, ino, "not_a_relative_path"),
            (self.work, "state/jobs.sqlite3", db.st_dev, db.st_ino, "not_a_work_scratch_directory"),
        ]
        with patch("app.media_repair.os.rename") as rename:
            for directory, name, d, i, reason in cases:
                with self.subTest(name=name, reason=reason), self.assertRaisesRegex(RepairRefused, reason):
                    remove_work_file(self.area, directory, name, device=d, inode=i, lease_dir=self.lease, job_db=self.db)
        rename.assert_not_called()  # refused before anything is captured
        self.assertTrue(Path(self.output, rel).exists() and Path(self.output, young).exists() and Path(self.db).exists())

    def test_a_swapped_work_file_is_put_back_not_removed(self):
        rel, dev, ino = self.leftover(self.output, "kaliv_00001_.mp4")
        real_rename = os.rename

        def swap_then_rename(src, dst):
            if str(src).endswith(rel):
                Path(str(src) + ".new").write_bytes(b"someone else's")
                real_rename(str(src) + ".new", src)
            return real_rename(src, dst)
        with patch("app.media_repair.os.rename", side_effect=swap_then_rename):
            with self.assertRaisesRegex(RepairRefused, "identity_changed"):
                remove_work_file(self.area, self.output, rel, device=dev, inode=ino, lease_dir=self.lease, job_db=self.db)
        self.assertEqual(Path(self.output, rel).read_bytes(), b"someone else's")

    def test_remove_work_file_refuses_while_an_executor_runs(self):
        rel, dev, ino = self.leftover(self.output, "kaliv_00001_.mp4")
        lock = acquire_executor_lock(GPU, lease_dir=self.lease)
        try:
            with self.assertRaisesRegex(RepairRefused, "executor_running"):
                remove_work_file(self.area, self.output, rel, device=dev, inode=ino, lease_dir=self.lease, job_db=self.db)
        finally:
            lock.release()
        self.assertTrue(Path(self.output, rel).exists())

    # -- the CLI ---------------------------------------------------------------------------------

    @staticmethod
    def tool():
        spec = importlib.util.spec_from_file_location("media_volume_repair", ROOT / "scripts/media_volume_repair.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def cli(self, *args, module=None):
        module = module or self.tool()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(list(args), volume_probe=self.probe)
        return code, out.getvalue(), err.getvalue()

    def test_cli_report_adopt_and_exit_codes(self):
        _, asset = self.job()
        common = ["--media-root", self.media, "--volume-root", self.volume, "--volume-id", VOLUME_ID]
        code, out, _ = self.cli("report", *common, "--job-db", self.db, "--lease-dir", self.lease)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["counts"]["adoptable"], 1)
        code, _, err = self.cli("adopt", *common, "--job-db", self.db, "--lease-dir", self.lease, "--asset", "0" * 32)
        self.assertEqual((code, err.strip()), (1, "refused: not_an_unindexed_asset"))
        code, out, _ = self.cli("adopt", *common, "--job-db", self.db, "--lease-dir", self.lease, "--asset", asset)
        self.assertEqual((code, json.loads(out)["adopted"]), (0, asset))
        self.mounted.clear()
        code, _, err = self.cli("report", *common, "--job-db", self.db)
        self.assertEqual(code, 75)

    def test_cli_work_area_report_and_removal(self):
        rel, dev, ino = self.leftover(self.output, "kaliv_00001_.mp4")
        common = ["--media-root", self.media, "--volume-root", self.volume, "--volume-id", VOLUME_ID,
                  "--job-db", self.db]
        work = ["--work-root", self.work, "--work-dir", self.output]
        code, out, err = self.cli("report", *common, *work)
        self.assertEqual(code, 0, err)
        self.assertEqual([f["path"] for f in json.loads(out)["work_area_residue"]], [rel])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.cli("report", *common, "--work-root", self.work)  # the two go together
        code, out, err = self.cli("remove-work-file", "--job-db", self.db, "--lease-dir", self.lease, *work,
                                  "--path", rel, "--device", str(dev), "--inode", str(ino))
        self.assertEqual((code, json.loads(out)["removed"]), (0, rel), err)
        os.chmod(self.work, 0o750)
        code, _, err = self.cli("report", *common, *work)
        self.assertEqual(code, 75)
        self.assertIn("work area refused", err)

    def test_cli_verifies_the_pinned_volume_before_it_reads_or_repairs(self):
        """H1 (#2390): the tool takes the volume id and runs G1's checks, as the executor does."""
        _, asset = self.job()
        index = Path(self.media, "index.json")
        before = index.read_bytes() if index.exists() else None
        common = ["--media-root", self.media, "--volume-root", self.volume]
        repair = ["--job-db", self.db, "--lease-dir", self.lease]
        # Another disk under the same letter, carrying another disk's marker: nothing is read or adopted.
        Path(self.volume, MARKER_NAME).write_text("kaliv-media-9999", encoding="ascii")
        for command in (["report"], ["adopt", "--asset", asset]):
            code, out, err = self.cli(*command, *common, "--volume-id", VOLUME_ID, *repair)
            self.assertEqual((code, out), (75, ""), err)
            self.assertIn("media_volume_marker_mismatch", err)
        self.assertEqual(index.read_bytes() if index.exists() else None, before, "nothing was adopted")
        Path(self.volume, MARKER_NAME).write_text(VOLUME_ID, encoding="ascii")
        # A network or subst letter, or an invalid id, is a configuration error (78), not "not here".
        for kind in ("remote", "subst"):
            self.probe.kind = kind
            code, _, err = self.cli("report", *common, "--volume-id", VOLUME_ID, *repair)
            self.assertEqual(code, 78, err)
            self.assertIn(f"media_volume_{kind}_refused", err)
        self.probe.kind = "local"
        code, _, err = self.cli("report", *common, "--volume-id", "not an id", *repair)
        self.assertEqual(code, 78, err)
        self.assertIn("media_volume_id_invalid", err)
        # The gallery folder must be on that volume.
        elsewhere = os.path.join(self.base, "elsewhere")
        os.mkdir(elsewhere)
        code, _, err = self.cli("report", "--media-root", elsewhere, "--volume-root", self.volume,
                                "--volume-id", VOLUME_ID, *repair)
        self.assertEqual(code, 75, err)
        self.assertIn("media_path_outside_volume", err)
        # The id is required.
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.cli("report", *common, *repair)
        # With the right disk it works, and adopts.
        code, out, err = self.cli("adopt", *common, "--volume-id", VOLUME_ID, *repair, "--asset", asset)
        self.assertEqual((code, json.loads(out)["adopted"]), (0, asset), err)

    def test_cli_says_so_when_the_disk_changes_while_it_runs(self):
        module = self.tool()

        def swap_during_report(*args, **kwargs):
            Path(self.volume, MARKER_NAME).write_text("kaliv-media-9999", encoding="ascii")
            return {"counts": {}}

        with patch.object(module, "reconcile", side_effect=swap_during_report):
            code, out, err = self.cli("report", "--media-root", self.media, "--volume-root", self.volume,
                                      "--volume-id", VOLUME_ID, "--job-db", self.db, module=module)
        self.assertEqual((code, out), (75, ""), err)
        self.assertIn("media_volume_marker_mismatch", err)


if __name__ == "__main__":
    unittest.main()
