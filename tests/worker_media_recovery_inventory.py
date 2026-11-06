#!/usr/bin/env python3
"""C6: the read-only recovery inventory for the C:/Z: hand-off (ChatGPT 6689780350 P1).

Each test builds the exact state a crash or a failed publication leaves: a job in the real job
store with the hand-off receipt the executor stores, the work-area file on "C:", staged temps and
assets in the real gallery on "Z:". Only the mount point and the work area's filesystem type are
patched. C2 (tests/worker_media_video_e2e.py) produces the same states with a real executor.

Run: PYTHONPATH=worker python3 tests/worker_media_recovery_inventory.py
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.gpu_lease import acquire_executor_lock  # noqa: E402
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_gallery_index_writer import register_asset  # noqa: E402
from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_recovery_inventory import recovery_inventory  # noqa: E402
from app.media_work_area import PrivateWorkArea  # noqa: E402

GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
DEAD = GPU + ":" + "a" * 16
MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 64
SECRET_PROMPT, SECRET_OWNER = "SECRET-PROMPT-5521", "owner-secret-77"


@unittest.skipIf(os.name == "nt", "POSIX test")
class RecoveryInventoryTests(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="kaliv-inv-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.volume = os.path.join(self.base, "vol")
        self.media = os.path.join(self.volume, "gallery")
        os.makedirs(self.media)
        self.work = os.path.join(self.base, "work")
        self.output = os.path.join(self.work, "comfy", "output")
        os.makedirs(self.output)
        os.makedirs(os.path.join(self.work, "state"))
        os.chmod(self.work, 0o700)
        self.lease = os.path.join(self.base, "lease")
        os.mkdir(self.lease, 0o700)
        for target, kwargs in (("app.media_gallery_catalog.os.path.ismount", {"side_effect": lambda p: str(p) == self.volume}),
                               ("app.media_work_area.WorkAreaProbe.containing_filesystem", {"return_value": ("ext4", False)})):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sink = ExternalMediaSink(self.media, self.volume)
        self.area = PrivateWorkArea(self.work)
        self.db = os.path.join(self.work, "state", "jobs.sqlite3")
        self.store = ImageJobStore(self.db)
        self.counter = 0

    # -- the states a hand-off can leave -----------------------------------------------------------

    def job(self, *, source=None):
        params = {"task": "image_to_video", "input_asset_id": source} if source else {"task": "text_to_video"}
        job = self.store.submit(SECRET_OWNER, SECRET_PROMPT, profile_id="wan", params=params,
                                max_owner_active=16)["job_id"]
        self.assertEqual(self.store.claim_for(["wan"], DEAD)["id"], job)
        return job

    def work_file(self, data=MP4):
        self.counter += 1
        path = Path(self.output, f"kaliv_{self.counter:05d}_.mp4")
        path.write_bytes(data)
        info = path.stat()
        return path, {"name": path.name, "dev": info.st_dev, "ino": info.st_ino, "size": info.st_size}

    def receipt(self, job, output, *, copied=True, data=MP4, volume=None, **extra):
        record = {"stage": "copied" if copied else "copying", "output": output, **extra}
        if copied:
            record.update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        root = os.stat(self.volume)
        record["volume"] = volume or {"dev": root.st_dev, "ino": root.st_ino}
        self.assertTrue(self.store.record_handoff(job, DEAD, record))

    def temp(self, data):
        self.counter += 1
        path = Path(self.media, f".kaliv-{self.counter:016x}.tmp")
        path.write_bytes(data)
        return path.name

    def publish(self, job, data=MP4):
        asset = self.sink.job_asset_id(job)
        Path(self.media, f"{asset}.mp4").write_bytes(data)
        register_asset(self.media, self.volume, asset, ".mp4", len(data))
        return asset

    def restart(self):
        """What the next executor start does: recover_gpu fails the dead instance's jobs."""
        self.store.recover_gpu(GPU, GPU + ":" + "b" * 16)

    def inventory(self):
        return recovery_inventory(self.sink, self.db, work_area=self.area, output_dir=self.output, lease_dir=self.lease)

    def only(self, report):
        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["jobs"]), 1, report)
        return report["jobs"][0]

    # -- the classes -------------------------------------------------------------------------------

    def test_an_interrupted_copy_is_tied_to_its_job_by_a_byte_exact_prefix(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output, copied=False)
        partial = self.temp(MP4[:1000])
        self.temp(b"\x00" * 1000)  # same size, other bytes: not this job's
        self.restart()
        entry = self.only(self.inventory())
        self.assertEqual((entry["job_id"], entry["classification"], entry["state"]), (job, "interrupted_copy", "failed"))
        self.assertEqual(entry["staged"], {"status": "partial", "name": partial, "size_bytes": 1000})
        self.assertEqual(entry["work_file"]["status"], "intact")

    def test_a_crash_after_the_sync_finds_the_complete_copy_by_hash(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        staged = self.temp(MP4)
        self.restart()
        entry = self.only(self.inventory())
        self.assertEqual(entry["classification"], "crash_after_sync_before_publication")
        self.assertEqual(entry["staged"], {"status": "complete", "name": staged})
        self.assertEqual(entry["asset"], {"status": "absent"})

    def test_a_failed_publication_keeps_the_work_file_and_nothing_is_staged(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        self.store.begin_publish(job, DEAD)
        self.store.fail(job, DEAD, "publication_failed")
        entry = self.only(self.inventory())
        self.assertEqual((entry["classification"], entry["error"]), ("publication_failed", "publication_failed"))

    def test_a_crash_after_publication_finds_the_one_published_copy(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        self.store.begin_publish(job, DEAD)
        asset = self.publish(job)
        self.restart()  # died before complete(): "interrupted during publication"
        entry = self.only(self.inventory())
        self.assertEqual(entry["classification"], "crash_after_publication_before_cleanup")
        self.assertEqual(entry["asset"], {"status": "same", "asset_id": asset, "indexed": True})
        self.assertEqual(entry["error"], "interrupted during publication")

    def test_a_failed_index_registration_is_published_unindexed(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        self.store.begin_publish(job, DEAD)
        asset = self.sink.job_asset_id(job)
        Path(self.media, f"{asset}.mp4").write_bytes(MP4)  # the file, but no index row
        self.restart()
        entry = self.only(self.inventory())
        self.assertEqual(entry["classification"], "published_unindexed")
        self.assertEqual(entry["asset"], {"status": "same", "asset_id": asset, "indexed": False})

    def test_a_clean_job_is_not_listed(self):
        job = self.job()
        path, output = self.work_file()
        self.receipt(job, output)
        self.store.begin_publish(job, DEAD)
        self.store.complete(job, DEAD, self.publish(job))
        path.unlink()  # removed after publication, as it should be
        report = self.inventory()
        self.assertEqual((report["jobs"], report["unattributed"]), ([], []))
        self.assertEqual(report["counts"]["jobs_with_receipt"], 1)

    def test_another_disk_at_the_volume_path_correlates_nothing(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output, volume={"dev": 1, "ino": 2})
        staged = self.temp(MP4)
        self.restart()
        report = self.inventory()
        self.assertEqual(self.only(report)["classification"], "volume_changed")
        self.assertIn({"where": "volume", "name": staged, "classification": "unknown", "size_bytes": len(MP4)},
                      report["unattributed"], "nothing on that disk is claimed for the job")

    # -- unknown, never guessed --------------------------------------------------------------------

    def test_two_candidates_or_a_changed_file_are_unknown(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        self.temp(MP4)
        self.temp(MP4)
        self.restart()
        entry = self.only(self.inventory())
        self.assertEqual((entry["classification"], entry["staged"]["status"]), ("unknown", "ambiguous"))

        job2 = self.job()
        path, output2 = self.work_file()
        self.receipt(job2, output2)
        path.write_bytes(MP4[:-1] + b"\x01")  # same inode and size, other bytes
        self.restart()
        entries = {e["job_id"]: e for e in self.inventory()["jobs"]}
        self.assertEqual(entries[job2]["work_file"]["status"], "changed")
        self.assertEqual(entries[job2]["classification"], "unknown")

    def test_a_replaced_work_file_is_unknown_even_with_the_same_bytes(self):
        job = self.job()
        path, output = self.work_file()
        self.receipt(job, output)
        self.temp(MP4)
        twin = path.with_name("twin.tmp")
        twin.write_bytes(MP4)
        os.replace(twin, path)  # same name, same bytes, another file
        self.restart()
        entry = self.only(self.inventory())
        self.assertEqual((entry["work_file"]["status"], entry["classification"]), ("changed", "unknown"))

    def test_the_classes_need_their_whole_evidence(self):
        # The copy started and failed; the adapter cleaned up: nothing left, so nothing listed.
        cleaned = self.job()
        path, output = self.work_file()
        self.receipt(cleaned, output, copied=False)
        path.unlink()
        # A complete staged copy, but the work file is gone: not "after the sync" (that keeps it).
        odd = self.job()
        path, output = self.work_file(MP4 + b"x")
        self.receipt(odd, output, data=MP4 + b"x")
        self.temp(MP4 + b"x")
        path.unlink()
        self.restart()
        entries = {e["job_id"]: e for e in self.inventory()["jobs"]}
        self.assertNotIn(cleaned, entries)
        self.assertEqual(entries[odd]["classification"], "unknown")

    def test_the_hash_reads_only_the_file_it_was_given(self):
        from app.media_recovery_inventory import _hash
        a, _ = self.work_file()
        b, _ = self.work_file()
        self.assertEqual(_hash(a, a.lstat()), hashlib.sha256(MP4).hexdigest())
        self.assertIsNone(_hash(a, b.lstat()), "another file's identity: refused, not read")
        self.assertIsNone(_hash(a, a.lstat(), limit=len(MP4) + 1), "a prefix longer than the file")
        self.assertEqual(_hash(a, a.lstat(), limit=10), hashlib.sha256(MP4[:10]).hexdigest())

    def test_a_different_file_under_the_assets_name_is_unknown(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        self.store.begin_publish(job, DEAD)
        self.publish(job, data=MP4 + b"tail")
        self.restart()
        entry = self.only(self.inventory())
        self.assertEqual((entry["classification"], entry["asset"]["status"]), ("unknown", "different"))

    def test_links_are_never_followed_and_odd_names_are_never_used(self):
        job = self.job()
        real, output = self.work_file()
        self.receipt(job, output)
        moved = Path(self.base, "elsewhere.mp4")
        os.rename(real, moved)
        os.symlink(moved, real)  # the receipt's name is now a link to an identical file outside
        Path(self.media, ".kaliv-link0000000000.tmp").symlink_to(moved)
        Path(self.output, "weird name;rm.mp4").write_bytes(MP4)
        self.restart()
        report = self.inventory()
        entry = self.only(report)
        self.assertEqual(entry["work_file"]["status"], "not_a_plain_file")
        self.assertEqual(entry["classification"], "unknown")
        self.assertNotIn(".kaliv-link0000000000.tmp", json.dumps(report), "a linked temp is not even read")
        self.assertIn({"where": "work_area", "name": "weird name;rm.mp4", "classification": "unknown", "kind": "other"},
                      report["unattributed"])

    # -- the source of an image-to-video job -------------------------------------------------------

    def test_the_source_is_present_missing_changed_or_unverified(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        source = "s" * 32
        Path(self.media, f"{source}.png").write_bytes(png)
        register_asset(self.media, self.volume, source, ".png", len(png))
        cases = {"present": hashlib.sha256(png).hexdigest(), "changed": "0" * 64, "unverified": None}
        seen = {}
        for expected, recorded in cases.items():
            job = self.job(source=source)
            _, output = self.work_file()
            extra = {"source_asset_id": source, **({"source_sha256": recorded} if recorded else {})}
            self.receipt(job, output, **extra)
            self.temp(MP4)  # a crash after the sync; the class does not matter here
            seen[job] = expected
        missing = self.job(source="m" * 32)
        _, output = self.work_file()
        self.receipt(missing, output, source_asset_id="m" * 32)
        seen[missing] = "missing"
        unindexed = "u" * 32  # the file is there, but the gallery does not list it
        Path(self.media, f"{unindexed}.png").write_bytes(png)
        job = self.job(source=unindexed)
        _, output = self.work_file()
        self.receipt(job, output, source_asset_id=unindexed, source_sha256=hashlib.sha256(png).hexdigest())
        seen[job] = "missing"
        self.restart()
        sources = {e["job_id"]: e["source"] for e in self.inventory()["jobs"]}
        self.assertEqual({job: sources[job] for job in seen}, seen)

    # -- what it never does ------------------------------------------------------------------------

    def test_nothing_while_an_executor_runs(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        self.temp(MP4)
        lock = acquire_executor_lock(GPU, lease_dir=self.lease)
        try:
            report = self.inventory()
        finally:
            lock.release()
        self.assertEqual((report["status"], report["executors_running"], report["jobs"]), ("executor_running", [GPU], []))

    def test_it_changes_nothing_and_never_shows_a_prompt_or_owner(self):
        for copied in (False, True):
            job = self.job()
            _, output = self.work_file()
            self.receipt(job, output, copied=copied)
            self.temp(MP4[:500] if not copied else MP4)
        self.restart()

        def snapshot():
            return sorted((str(p), p.lstat().st_size, p.lstat().st_mtime_ns, p.lstat().st_ino)
                          for p in Path(self.base).rglob("*"))
        before, db_before = snapshot(), hashlib.sha256(Path(self.db).read_bytes()).hexdigest()
        text = json.dumps(self.inventory())
        self.assertEqual(snapshot(), before)
        self.assertEqual(hashlib.sha256(Path(self.db).read_bytes()).hexdigest(), db_before)
        self.assertNotIn(SECRET_PROMPT, text)
        self.assertNotIn(SECRET_OWNER, text)
        self.assertNotIn("text_to_video", text, "no job parameters")

    def test_the_cli_prints_the_inventory(self):
        job = self.job()
        _, output = self.work_file()
        self.receipt(job, output)
        self.temp(MP4)
        self.restart()
        spec = importlib.util.spec_from_file_location("media_volume_repair", ROOT / "scripts/media_volume_repair.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(["inventory", "--media-root", self.media, "--volume-root", self.volume,
                                "--job-db", self.db, "--lease-dir", self.lease, "--work-root", self.work,
                                "--work-dir", self.output])
        self.assertEqual(code, 0, err.getvalue())
        report = json.loads(out.getvalue())
        self.assertEqual(report["schema"], "kaliv-media-recovery-inventory/v1")
        self.assertEqual(report["jobs"][0]["classification"], "crash_after_sync_before_publication")


if __name__ == "__main__":
    unittest.main()
