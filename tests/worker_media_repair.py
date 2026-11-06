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
from app.media_repair import RepairRefused, adopt, reconcile, remove_stale_temp  # noqa: E402

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
        patcher = patch("app.media_gallery_catalog.os.path.ismount", side_effect=lambda p: str(p) in self.mounted)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sink = ExternalMediaSink(self.media, self.volume)
        self.db = os.path.join(self.volume, "jobs.sqlite3")
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
        self.assertEqual((entry["status"], entry["job_error"]), ("job_failed", "interrupted during publication"))
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
        jobs.assert_not_called()  # the job database lives on the volume: not opened

    # -- the CLI ---------------------------------------------------------------------------------

    def cli(self, *args):
        spec = importlib.util.spec_from_file_location("media_volume_repair", ROOT / "scripts/media_volume_repair.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_cli_report_adopt_and_exit_codes(self):
        _, asset = self.job()
        common = ["--media-root", self.media, "--volume-root", self.volume]
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


if __name__ == "__main__":
    unittest.main()
