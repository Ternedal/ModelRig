#!/usr/bin/env python3
"""The private work area on the internal disk (Anders, 6 Nov 2026, #2275 6686905826).

Real directories, files, symlinks, FIFOs and modes. A fake probe stands in only for the filesystem
type of the containing mount, a foreign ``st_dev``, a foreign owner and the Windows per-directory ACL.
The real Windows reader is covered by tests/support/windows_media_work_area_contract.py.

Run: PYTHONPATH=worker python3 tests/worker_media_work_area.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.media_generation_contract import ArtifactSinkUnavailable, MediaWorkArea  # noqa: E402
from app.media_work_area import (WORK_ROOT_ENV, MediaWorkAreaConfigError, PrivateWorkArea,  # noqa: E402
                                 WorkAreaProbe, work_area_from_env)


class Probe(WorkAreaProbe):
    """The real probe, with the facts a temp dir cannot have made explicit."""

    windows = False

    def __init__(self, filesystem=("ext4", False)):
        self.fs = filesystem
        self.foreign_dev: set[str] = set()
        self.not_private: set[str] = set()
        self.per_entry = False

    @property
    def acl_per_entry(self) -> bool:
        return self.per_entry

    def containing_filesystem(self, path):
        return self.fs

    def lstat(self, path):
        info = os.lstat(path)
        if path in self.foreign_dev:
            values = list(info)
            values[2] = info.st_dev + 1  # st_dev
            return os.stat_result(values)
        return info

    def private(self, path, info):
        if path in self.not_private:
            return False, "test: a grant for another principal"
        return super().private(path, info)


@unittest.skipIf(os.name == "nt", "POSIX modes; Windows has its own contract")
class WorkAreaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "work"
        self.root.mkdir(mode=0o700)
        os.chmod(self.root, 0o700)
        for name in ("comfy/output", "state"):
            (self.root / name).mkdir(parents=True)
        self.probe = Probe()

    def area(self, root=None, probe=None) -> PrivateWorkArea:
        return PrivateWorkArea(str(root or self.root), probe=probe or self.probe)

    def refused(self, area: PrivateWorkArea, path) -> str | None:
        try:
            area.require(str(path))
        except ArtifactSinkUnavailable as exc:
            return str(exc)
        return None

    def config_error(self, root=None, probe=None) -> str:
        with self.assertRaises(MediaWorkAreaConfigError) as caught:
            self.area(root, probe)
        return str(caught.exception)

    # -- construction -----------------------------------------------------------------------------

    def test_a_private_directory_on_a_stable_filesystem_is_accepted(self):
        area = self.area()
        self.assertIsInstance(area, MediaWorkArea)
        self.assertEqual(area.root, self.root)
        self.assertEqual(area.filesystem, "ext4")
        self.assertEqual(area.device, os.stat(self.root).st_dev)
        self.assertEqual(area.verify(), self.root)
        for inside in (self.root, self.root / "comfy", self.root / "comfy" / "output", self.root / "state"):
            self.assertIsNone(self.refused(area, inside), inside)

    def test_the_setting_is_required_and_never_defaulted(self):
        for env in ({}, {WORK_ROOT_ENV: ""}):
            with self.subTest(env=env), self.assertRaises(MediaWorkAreaConfigError) as caught:
                work_area_from_env(env, probe=self.probe)
            self.assertIn(WORK_ROOT_ENV, str(caught.exception), "the operator is told which setting")
        self.assertEqual(work_area_from_env({WORK_ROOT_ENV: str(self.root)}, probe=self.probe).root, self.root)

    def test_a_root_that_is_not_an_existing_canonical_directory_is_78(self):
        a_file = self.tmp / "a-file"
        a_file.write_bytes(b"x")
        link = self.tmp / "link"
        link.symlink_to(self.root)
        linked_parent = self.tmp / "via"
        linked_parent.symlink_to(self.tmp)
        cases = {
            "relative/work": "media_work_area_root_invalid",
            str(self.tmp / "missing"): "media_work_area_missing",
            str(a_file): "media_work_area_not_directory",
            str(link): "media_work_area_root_link",
            str(linked_parent / "work"): "media_work_area_root_not_canonical",
            str(self.root) + "/../work": "media_work_area_root_invalid",
        }
        for root, reason in cases.items():
            with self.subTest(root=root):
                self.assertEqual(self.config_error(root), reason)

    def test_a_root_others_can_use_is_78(self):
        for mode in (0o750, 0o740, 0o710, 0o705, 0o701, 0o770, 0o777):
            with self.subTest(mode=oct(mode)):
                os.chmod(self.root, mode)
                self.assertTrue(self.config_error().startswith("media_work_area_not_private"))
        os.chmod(self.root, 0o700)
        self.area()

    def test_a_root_owned_by_another_user_is_78(self):
        with patch("app.media_work_area.os.geteuid", return_value=os.geteuid() + 1):
            self.assertEqual(self.config_error(), "media_work_area_not_private: owned by another user")

    def test_a_network_unknown_or_unstable_filesystem_is_78(self):
        cases = {("ntfs", True): "media_work_area_network_drive",
                 (None, False): "media_work_area_filesystem_unknown",
                 ("exfat", False): "media_work_area_filesystem_refused",
                 ("vfat", False): "media_work_area_filesystem_refused",
                 ("nfs4", False): "media_work_area_filesystem_refused",
                 ("cifs", False): "media_work_area_filesystem_refused",
                 ("9p", False): "media_work_area_filesystem_refused",
                 ("tmpfs", False): "media_work_area_filesystem_refused"}
        for fs, reason in cases.items():
            with self.subTest(fs=fs):
                self.assertEqual(self.config_error(probe=Probe(fs)), reason)
        for fs in ("ntfs", "refs", "ext4", "xfs", "btrfs"):
            self.area(probe=Probe((fs, False)))

    # -- require ----------------------------------------------------------------------------------

    def test_paths_outside_the_root_are_refused_including_a_prefix_sibling(self):
        area = self.area()
        sibling = self.tmp / "work2"
        sibling.mkdir(mode=0o700)
        backslash_sibling = self.tmp / "work\\x"  # an ordinary filename character on POSIX
        backslash_sibling.mkdir()
        for outside in (self.tmp, sibling, backslash_sibling, Path("/")):
            with self.subTest(path=outside):
                self.assertEqual(self.refused(area, outside), "media_work_path_outside_work_area")

    def test_links_other_devices_and_odd_files_inside_are_refused(self):
        area = self.area()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (self.root / "jump").symlink_to(elsewhere)
        os.mkfifo(self.root / "a-fifo")
        (self.root / "state" / "jobs.sqlite3").write_bytes(b"")
        # A link is caught twice: its target is not where its name says (canonical check), and the
        # walk refuses a link component even where a probe resolves it to itself (below).
        self.assertEqual(self.refused(area, self.root / "jump"), "media_work_path_not_canonical")
        self.assertEqual(self.refused(area, self.root / "jump" / "x"), "media_work_path_missing")
        self.assertEqual(self.refused(area, self.root / "a-fifo"), "media_work_path_not_file_or_directory")
        self.assertEqual(self.refused(area, self.root / "nope"), "media_work_path_missing")
        self.assertEqual(self.refused(area, str(self.root) + "/state/../comfy"), "media_path_refused")
        self.assertIsNone(self.refused(area, self.root / "state" / "jobs.sqlite3"))
        self.probe.foreign_dev.add(str(self.root / "comfy"))
        self.assertEqual(self.refused(area, self.root / "comfy" / "output"), "media_work_path_other_device")

    def test_a_link_to_inside_the_root_is_still_refused(self):
        area = self.area()
        (self.root / "alias").symlink_to(self.root / "state")
        self.assertEqual(self.refused(area, self.root / "alias"), "media_work_path_not_canonical")
        # A reparse point that realpath does not resolve (a Windows mounted folder) is the walk's case.
        self.probe.realpath = lambda path: path
        self.assertEqual(self.refused(area, self.root / "alias"), "media_work_path_link")

    def test_on_windows_every_directory_used_must_itself_be_private(self):
        area = self.area()
        self.probe.per_entry = True
        os.chmod(self.root / "state", 0o700)
        self.probe.not_private.add(str(self.root / "comfy"))
        self.assertEqual(self.refused(area, self.root / "comfy" / "output"), "media_work_path_not_private")
        self.assertEqual(self.refused(area, self.root / "comfy"), "media_work_path_not_private")
        self.assertIsNone(self.refused(area, self.root / "state"))
        self.probe.per_entry = False  # POSIX: the private root already stops every other user
        self.assertIsNone(self.refused(area, self.root / "comfy" / "output"))

    def test_on_windows_a_file_moved_in_with_its_old_grants_is_refused(self):
        area = self.area()
        db = self.root / "state" / "jobs.sqlite3"
        db.write_bytes(b"")
        os.chmod(self.root / "state", 0o700)
        os.chmod(db, 0o600)
        self.probe.per_entry = True
        self.assertIsNone(self.refused(area, db))
        self.probe.not_private.add(str(db))  # e.g. moved from C:\\ModelRig, where Users could read it
        self.assertEqual(self.refused(area, db), "media_work_path_not_private")
        self.assertIsNone(self.refused(area, self.root / "state"), "its folder is still fine")

    # -- after start ------------------------------------------------------------------------------

    def test_a_root_that_changes_after_start_is_refused_until_a_restart(self):
        area = self.area()
        os.chmod(self.root, 0o755)
        self.assertTrue(self.refused(area, self.root / "state").startswith("media_work_area_not_private"))
        with self.assertRaises(ArtifactSinkUnavailable):
            area.verify()
        os.chmod(self.root, 0o700)
        self.assertIsNone(self.refused(area, self.root / "state"))

        self.root.rename(self.tmp / "work-old")
        self.root.mkdir(mode=0o700)
        (self.root / "state").mkdir()
        self.assertEqual(self.refused(area, self.root / "state"), "media_work_area_identity_changed")

        shutil.rmtree(self.root)
        self.root.symlink_to(self.tmp / "work-old")
        self.assertEqual(self.refused(area, self.root / "state"), "media_work_area_root_link")
        self.root.unlink()
        self.assertEqual(self.refused(area, self.root / "state"), "media_work_area_missing")

    def test_nothing_is_created_moved_or_deleted(self):
        before = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob("*"))
        area = self.area()
        area.verify()
        self.refused(area, self.root / "not-there")
        self.refused(area, self.tmp)
        self.assertEqual(sorted(p.relative_to(self.tmp) for p in self.tmp.rglob("*")), before)


@unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc/self/mountinfo")
class RealProbeTests(unittest.TestCase):
    def test_the_containing_mount_is_the_longest_mount_point_prefix(self):
        probe = WorkAreaProbe()
        fs, remote = probe.containing_filesystem("/")
        self.assertIsNotNone(fs)
        self.assertFalse(remote)
        if os.path.ismount("/dev/shm"):
            self.assertEqual(probe.containing_filesystem("/dev/shm/x/y")[0], "tmpfs")
            self.assertEqual(probe.containing_filesystem("/dev/shm")[0], "tmpfs")
            self.assertNotEqual(probe.containing_filesystem("/dev/shmx")[0], "tmpfs", "a prefix sibling is not inside")

    def test_the_longest_mount_wins_whatever_the_order_and_escapes_are_decoded(self):
        with tempfile.TemporaryDirectory() as td:
            info = Path(td, "mountinfo")
            info.write_text("36 25 8:2 / /data rw - xfs /dev/sdb1 rw\n"
                            "25 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
                            "40 36 8:3 / /data/my\\040disk rw - btrfs /dev/sdc1 rw\n"
                            "41 25 0:5 / /dat rw - tmpfs tmpfs rw\n"
                            "not a mount line\n")
            probe = WorkAreaProbe()
            probe.mountinfo = str(info)
            self.assertEqual(probe.containing_filesystem("/data/kaliv/work"), ("xfs", False))
            self.assertEqual(probe.containing_filesystem("/data"), ("xfs", False))
            self.assertEqual(probe.containing_filesystem("/data/my disk/work"), ("btrfs", False))
            self.assertEqual(probe.containing_filesystem("/datax/work"), ("ext4", False))
            self.assertEqual(probe.containing_filesystem("/home"), ("ext4", False))
            probe.mountinfo = str(Path(td, "absent"))
            self.assertEqual(probe.containing_filesystem("/data"), (None, False), "unreadable: unknown, so refused")

    def test_the_real_probe_judges_posix_modes(self):
        with tempfile.TemporaryDirectory() as td:
            os.chmod(td, 0o700)
            probe = WorkAreaProbe()
            self.assertTrue(probe.private(td, os.lstat(td))[0])
            os.chmod(td, 0o750)
            self.assertFalse(probe.private(td, os.lstat(td))[0])
            self.assertFalse(probe.acl_per_entry)

        class OnWindows(WorkAreaProbe):
            windows = True

        self.assertTrue(OnWindows().acl_per_entry, "Windows checks every folder and file used")


if __name__ == "__main__":
    unittest.main()
