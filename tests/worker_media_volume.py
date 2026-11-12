#!/usr/bin/env python3
"""G1: the production VerifiedMediaVolume (C1, #2275 6669445071).

Real directories, files and symlinks. Only the facts a test machine cannot produce on demand come
from a fake probe:
- which path is a mount point;
- the filesystem type;
- which device is the system volume;
- a foreign ``st_dev`` or a Windows reparse attribute on one chosen path.

Real Windows (junctions, alternate data streams, 8.3 aliases, NTFS, the system drive) is covered by
tests/support/windows_media_volume_contract.py.

Run: PYTHONPATH=worker python3 tests/worker_media_volume.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable, VerifiedMediaVolume  # noqa: E402
from app.media_volume import (  # noqa: E402
    FILE_ATTRIBUTE_REPARSE_POINT, MARKER_NAME, VOLUME_ID_ENV, VOLUME_ROOT_ENV, MediaVolumeConfigError,
    MountedMediaVolume, SystemProbe, check_path_syntax, media_volume_from_env,
)

VOLUME_ID = "kaliv-media-0001"


class FakeProbe(SystemProbe):
    windows = False

    def __init__(self, mounts, filesystem="ext4", system_dev=-1, mount_ids=None):
        self.mounts = set(mounts)
        self.mount_ids = dict(mount_ids or {})  # path -> mount id; absent = none known (as on Windows)
        self.fs = filesystem
        self.system_dev = system_dev
        self.overrides = {}  # path -> dict of st_* fields to replace

    def lstat(self, path):
        info = os.lstat(path)
        extra = self.overrides.get(path)
        if not extra:
            return info
        fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        fields.update(extra)
        return SimpleNamespace(**fields)

    def ismount(self, path):
        return path in self.mounts

    def system_volume_dev(self):
        return self.system_dev

    def filesystem(self, root):
        return self.fs

    def mount_instance(self, root):
        return self.mount_ids.get(root)


@unittest.skipIf(os.name == "nt", "POSIX paths; Windows runs tests/support/windows_media_volume_contract.py")
class MediaVolumeTests(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="kaliv-g1-"))
        self.root = os.path.join(self.base, "vol")
        os.mkdir(self.root)
        self.write_marker(VOLUME_ID)
        self.out = os.path.join(self.root, "comfy", "output")
        os.makedirs(self.out)
        self.probe = FakeProbe({self.root})

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def write_marker(self, text, name=MARKER_NAME):
        with open(os.path.join(self.root, name), "w", encoding="ascii") as handle:
            handle.write(text + "\n")

    def volume(self, **kw):
        return MountedMediaVolume(self.root, VOLUME_ID, probe=self.probe, **kw)

    def assertRefused(self, reason, fn, *args, **kw):
        with self.assertRaises(ArtifactSinkUnavailable) as caught:
            fn(*args, **kw)
        self.assertEqual(str(caught.exception), reason)

    def assertConfig(self, reason, fn, *args, **kw):
        with self.assertRaises(MediaVolumeConfigError) as caught:
            fn(*args, **kw)
        self.assertEqual(str(caught.exception), reason)

    # -- construction ----------------------------------------------------------------------------

    def test_valid_volume_satisfies_the_protocol(self):
        volume = self.volume()
        self.assertIsInstance(volume, VerifiedMediaVolume)
        self.assertEqual(volume.root, Path(self.root))
        self.assertEqual(volume.filesystem, "ext4")
        volume.require(self.root)
        volume.require(self.out)
        file_path = os.path.join(self.out, "frame.png")
        Path(file_path).write_bytes(b"x")
        volume.require(file_path)
        volume.require(Path(self.out))  # PathLike is accepted

    def test_trailing_separator_on_root_is_the_same_root(self):
        volume = MountedMediaVolume(self.root + "/", VOLUME_ID, probe=self.probe)
        volume.require(self.out)

    def test_volume_id_must_be_well_formed(self):
        for bad in ("", "short", "-leading-dash", "has space 1234", "x" * 65, None, 12345678):
            self.assertConfig("media_volume_id_invalid", MountedMediaVolume, self.root, bad, probe=self.probe)

    def test_root_must_be_absolute_and_without_dot_segments(self):
        for bad in ("relative/vol", self.root + "/../vol", self.root + "/./x", ""):
            self.assertConfig("media_volume_root_invalid", MountedMediaVolume, bad, VOLUME_ID, probe=self.probe)

    def test_root_must_be_a_mount_point(self):
        self.probe.mounts.clear()
        self.assertRefused("media_volume_not_mounted", self.volume)

    def test_missing_root_is_unavailable_not_config(self):
        shutil.rmtree(self.root)
        self.assertRefused("media_volume_missing", self.volume)

    def test_root_that_is_a_symlink_is_refused(self):
        real = os.path.join(self.base, "real")
        os.rename(self.root, real)
        os.symlink(real, self.root)
        self.assertRefused("media_volume_root_link", self.volume)

    def test_root_behind_a_symlinked_parent_is_refused(self):
        os.symlink(self.base, os.path.join(self.base, "alias"))
        alias_root = os.path.join(self.base, "alias", "vol")
        self.probe.mounts.add(alias_root)
        self.assertRefused("media_volume_root_not_canonical",
                           MountedMediaVolume, alias_root, VOLUME_ID, probe=self.probe)

    def test_filesystems_without_stable_ids_are_refused(self):
        for fs in ("vfat", "exfat", "fat32", "tmpfs", "ntfs3-but-unknown"):
            self.probe.fs = fs
            self.assertConfig("media_volume_filesystem_refused", self.volume)
        self.probe.fs = None
        self.assertConfig("media_volume_filesystem_unknown", self.volume)

    def test_each_stable_id_filesystem_is_accepted(self):
        for fs in ("ntfs", "refs", "ext4", "xfs", "btrfs"):
            self.probe.fs = fs
            self.assertEqual(self.volume().filesystem, fs)

    def test_system_volume_is_refused(self):
        self.probe.system_dev = os.lstat(self.root).st_dev
        self.assertConfig("media_volume_is_system_volume", self.volume)

    # -- the marker ------------------------------------------------------------------------------

    def test_marker_missing_or_wrong_is_unavailable(self):
        os.unlink(os.path.join(self.root, MARKER_NAME))
        self.assertRefused("media_volume_marker_missing", self.volume)
        self.write_marker("kaliv-media-9999")
        self.assertRefused("media_volume_marker_mismatch", self.volume)

    def test_marker_symlink_oversize_or_binary_is_refused(self):
        marker = os.path.join(self.root, MARKER_NAME)
        os.unlink(marker)
        elsewhere = os.path.join(self.base, "marker-elsewhere")
        Path(elsewhere).write_text(VOLUME_ID)
        os.symlink(elsewhere, marker)
        self.assertRefused("media_volume_marker_refused", self.volume)
        os.unlink(marker)
        Path(marker).write_text(VOLUME_ID + " " * 200)
        self.assertRefused("media_volume_marker_refused", self.volume)
        Path(marker).write_bytes(VOLUME_ID.encode() + b"\xff")
        self.assertRefused("media_volume_marker_refused", self.volume)
        os.unlink(marker)
        os.mkdir(marker)
        self.assertRefused("media_volume_marker_refused", self.volume)

    def test_marker_with_crlf_is_accepted(self):
        Path(self.root, MARKER_NAME).write_bytes(VOLUME_ID.encode() + b"\r\n")
        self.volume()

    # -- after start: disappearance and remount ---------------------------------------------------

    def test_unmount_after_start_is_detected_by_verify_and_require(self):
        volume = self.volume()
        self.probe.mounts.clear()
        self.assertRefused("media_volume_not_mounted", volume.verify)
        self.assertRefused("media_volume_not_mounted", volume.require, self.out)

    def test_a_different_disk_at_the_same_path_is_refused_until_restart(self):
        volume = self.volume()
        # Same path, same marker, but another directory there now (a remount of something else).
        # The old one is moved aside, not deleted, so the new one cannot reuse its inode.
        os.rename(self.root, self.root + ".old")
        os.mkdir(self.root)
        self.write_marker(VOLUME_ID)
        os.makedirs(self.out)
        self.assertRefused("media_volume_identity_changed", volume.verify)
        self.assertRefused("media_volume_identity_changed", volume.require, self.out)
        # A fresh start pins the new identity (exit 75 -> restart is the recovery path).
        self.volume().require(self.out)

    # -- Codex P2 #2349 4498174484: the same disk unplugged and plugged back in ---------------------

    def test_the_same_disk_mounted_again_is_refused_until_restart(self):
        """A remount keeps st_dev and the root inode; the mount instance (Linux mount id) changes."""
        self.probe.mount_ids[self.root] = "41"
        volume = self.volume()
        volume.require(self.out)
        self.probe.mount_ids[self.root] = "57"  # same disk, same identity, a new mount
        self.assertRefused("media_volume_remounted", volume.verify)
        self.assertRefused("media_volume_remounted", volume.require, self.out)  # never matches again
        self.volume().require(self.out)  # exit 75 -> restart pins the new mount

    def test_an_observed_loss_holds_even_when_the_disk_comes_back(self):
        """Without a mount id (Windows), an observed loss still ends this verifier for good."""
        volume = self.volume()
        self.probe.mounts.clear()
        self.assertRefused("media_volume_not_mounted", volume.verify)  # the real reason, while it lasts
        self.probe.mounts.add(self.root)  # plugged back in: same disk, same identity, same marker
        self.assertRefused("media_volume_lost", volume.verify)
        self.assertRefused("media_volume_lost", volume.require, self.out)
        self.volume().require(self.out)

    def test_every_root_refusal_is_sticky_but_a_path_refusal_is_not(self):
        volume = self.volume()
        self.assertRefused("media_path_outside_volume", volume.require, self.base)
        volume.require(self.out)  # a bad path says nothing about the volume
        self.write_marker("kaliv-media-other")
        self.assertRefused("media_volume_marker_mismatch", volume.verify)
        self.write_marker(VOLUME_ID)
        self.assertRefused("media_volume_lost", volume.verify)

    def test_without_a_mount_id_an_unobserved_remount_is_not_detectable(self):
        """The documented limit (MEDIA_VOLUME.md): with no mount instance (Windows) and no check
        while it was gone, the same disk back with the same identity passes. Writes through
        handles of the old mount fail, so a copy in flight fails and its C: copy is kept."""
        volume = self.volume()
        self.assertIsNone(self.probe.mount_instance(self.root))
        volume.verify()  # nothing observed in between: the same disk, the same identity
        volume.require(self.out)

    def test_marker_swapped_after_start_is_refused(self):
        volume = self.volume()
        self.write_marker("kaliv-media-other")
        self.assertRefused("media_volume_marker_mismatch", volume.require, self.out)

    def test_volume_is_usable_as_the_job_store_guard(self):
        volume = self.volume()
        store = ImageJobStore(os.path.join(self.root, "jobs.sqlite"), volume_guard=volume.verify)
        store.submit("owner-a", "prompt", profile_id="p")
        self.probe.mounts.clear()
        with self.assertRaises(ArtifactSinkUnavailable):
            store.submit("owner-a", "prompt", profile_id="p")

    # -- require() ------------------------------------------------------------------------------

    def test_paths_outside_the_root_are_refused(self):
        volume = self.volume()
        sibling = self.root + "2"  # shares the root's string prefix
        os.mkdir(sibling)
        self.assertRefused("media_path_outside_volume", volume.require, sibling)
        self.assertRefused("media_path_outside_volume", volume.require, self.base)
        self.assertRefused("media_path_outside_volume", volume.require, "/")

    def test_traversal_and_malformed_paths_are_refused(self):
        volume = self.volume()
        for bad in (self.out + "/../../..", self.root + "/./comfy", "comfy/output", "", self.out + "\x00x"):
            self.assertRefused("media_path_refused", volume.require, bad)
        for bad in (None, b"/bytes/path", 3):
            with self.assertRaises((ArtifactSinkUnavailable, TypeError)):
                volume.require(bad)

    def test_missing_path_is_refused(self):
        self.assertRefused("media_path_missing", self.volume().require, os.path.join(self.root, "nope"))

    def test_symlink_inside_the_volume_is_refused_wherever_it_points(self):
        volume = self.volume()
        inside = os.path.join(self.root, "link-inside")
        os.symlink(self.out, inside)
        self.assertRefused("media_path_not_canonical", volume.require, inside)
        outside = os.path.join(self.root, "link-outside")
        os.symlink(self.base, outside)
        self.assertRefused("media_path_not_canonical", volume.require, outside)
        Path(self.out, "x").write_bytes(b"x")
        self.assertRefused("media_path_not_canonical", volume.require, os.path.join(inside, "x"))

    def test_component_on_another_device_is_refused(self):
        volume = self.volume()
        comfy = os.path.join(self.root, "comfy")
        self.probe.overrides[comfy] = {"st_dev": os.lstat(comfy).st_dev + 1}  # e.g. a bind mount of the internal disk
        self.assertRefused("media_path_other_device", volume.require, self.out)
        volume.require(self.root)

    def test_reparse_point_component_is_refused(self):
        volume = self.volume()
        comfy = os.path.join(self.root, "comfy")
        self.probe.overrides[comfy] = {"st_file_attributes": FILE_ATTRIBUTE_REPARSE_POINT}
        self.assertRefused("media_path_link", volume.require, self.out)

    def test_a_backslash_is_part_of_a_posix_name_not_a_separator(self):
        # #2349 review 4491252681: on POSIX "a\\b" is one name. The walk must inspect that entry,
        # not a/b. Here "a\\b" is a FIFO and "a/b" a regular file.
        if not hasattr(os, "mkfifo"):
            self.skipTest("no FIFOs here")
        volume = self.volume()
        os.mkdir(os.path.join(self.root, "a"))
        Path(self.root, "a", "b").write_bytes(b"regular")
        os.mkfifo(os.path.join(self.root, "a\\b"))
        self.assertRefused("media_path_not_file_or_directory", volume.require, os.path.join(self.root, "a\\b"))
        volume.require(os.path.join(self.root, "a", "b"))
        # and a foreign device is found under its real POSIX name
        Path(self.root, "c\\d").mkdir()
        self.probe.overrides[os.path.join(self.root, "c\\d")] = {"st_dev": os.lstat(self.root).st_dev + 1}
        self.assertRefused("media_path_other_device", volume.require, os.path.join(self.root, "c\\d"))

    def test_a_sibling_of_a_root_ending_in_a_backslash_is_outside(self):
        # #2349 review 4491286902: on POSIX "vol\\" is a name, so its containment prefix is
        # "vol\\/", not "vol\\". A sibling "vol\\outside" must not pass.
        if not hasattr(os, "mkfifo"):
            self.skipTest("no FIFOs here")
        root = os.path.join(self.base, "vol\\")
        os.mkdir(root)
        Path(root, MARKER_NAME).write_text(VOLUME_ID)
        Path(root, "outside").write_bytes(b"inside the volume")
        sibling = os.path.join(self.base, "vol\\outside")
        os.mkfifo(sibling)
        self.probe.mounts.add(root)
        volume = MountedMediaVolume(root, VOLUME_ID, probe=self.probe)
        self.assertRefused("media_path_outside_volume", volume.require, sibling)
        volume.require(os.path.join(root, "outside"))

    def test_fifo_is_neither_file_nor_directory(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("no FIFOs here")
        fifo = os.path.join(self.out, "pipe")
        os.mkfifo(fifo)
        self.assertRefused("media_path_not_file_or_directory", self.volume().require, fifo)

    # -- descriptors (the gallery's reads; #2275 6702693683 findings 1 and 3) -------------------------

    def opened(self, path, flags=os.O_RDONLY):
        fd = os.open(path, flags)
        self.addCleanup(os.close, fd)
        return fd

    def asset(self, name="a.png", data=b"MINE"):
        path = os.path.join(self.out, name)
        Path(path).write_bytes(data)
        return path

    def test_descriptor_of_the_named_file_passes(self):
        path = self.asset()
        info = self.volume().require_descriptor(self.opened(path), path)
        self.assertEqual((info.st_dev, info.st_ino), (os.stat(path).st_dev, os.stat(path).st_ino))
        self.volume().require_descriptor(self.opened(self.out), self.out)  # a directory too

    def test_parent_swapped_around_the_open_is_refused(self):
        # The probe's attack: a parent is a link to elsewhere ON THE SAME VOLUME at the open, and is
        # swapped back afterwards. The path walks clean again, but the descriptor is another file.
        path = self.asset(data=b"MINE")
        elsewhere = os.path.join(self.root, "elsewhere")
        os.makedirs(elsewhere)
        Path(elsewhere, "a.png").write_bytes(b"EVIL")
        output = self.out
        os.rename(output, output + ".real")
        os.symlink(elsewhere, output)  # the parent is a link at the open; O_NOFOLLOW covers the last part only
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        self.addCleanup(os.close, fd)
        os.unlink(output)
        os.rename(output + ".real", output)  # swapped back: the path walks clean again
        self.assertEqual(os.read(fd, 4), b"EVIL")
        os.lseek(fd, 0, os.SEEK_SET)
        self.assertRefused("media_descriptor_not_path", self.volume().require_descriptor, fd, path)

    def test_parent_still_a_link_after_the_open_is_refused(self):
        path = self.asset()
        comfy = os.path.join(self.root, "comfy")
        os.rename(comfy, comfy + ".real")
        os.symlink(comfy + ".real", comfy)
        fd = self.opened(path)
        self.assertRefused("media_path_not_canonical", self.volume().require_descriptor, fd, path)

    def test_descriptor_on_another_device_is_refused(self):
        path = self.asset()
        fd = self.opened(path)
        real = os.fstat(fd)
        foreign = SimpleNamespace(st_dev=real.st_dev + 1, st_ino=real.st_ino, st_mode=real.st_mode)
        volume = self.volume()
        self.probe.fstat = lambda _fd: foreign
        self.assertRefused("media_descriptor_other_device", volume.require_descriptor, fd, path)

    def test_a_real_file_on_another_filesystem_is_refused(self):
        shm = "/dev/shm"
        if not os.path.isdir(shm) or os.stat(shm).st_dev == os.stat(self.root).st_dev:
            self.skipTest("no second filesystem here")
        other = tempfile.mkdtemp(prefix="kaliv-g1-other-", dir=shm)
        self.addCleanup(shutil.rmtree, other, True)
        Path(other, "a.png").write_bytes(b"EVIL")
        path = self.asset()
        fd = self.opened(os.path.join(other, "a.png"))
        self.assertRefused("media_descriptor_other_device", self.volume().require_descriptor, fd, path)

    def test_a_fifo_descriptor_is_refused(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("no FIFOs here")
        fifo = os.path.join(self.out, "pipe")
        os.mkfifo(fifo)
        fd = self.opened(fifo, os.O_RDONLY | os.O_NONBLOCK)
        self.assertRefused("media_descriptor_not_file_or_directory",
                           self.volume().require_descriptor, fd, fifo)

    def test_a_closed_descriptor_is_refused(self):
        path = self.asset()
        fd = os.open(path, os.O_RDONLY)
        os.close(fd)
        self.assertRefused("media_descriptor_unavailable", self.volume().require_descriptor, fd, path)

    def test_a_lost_volume_refuses_the_descriptor_first(self):
        path = self.asset()
        fd = self.opened(path)
        volume = self.volume()
        os.unlink(os.path.join(self.root, MARKER_NAME))
        self.assertRefused("media_volume_marker_missing", volume.require_descriptor, fd, path)
        self.write_marker(VOLUME_ID)
        self.assertRefused("media_volume_lost", volume.require_descriptor, fd, path)

    def test_a_path_outside_the_volume_is_refused(self):
        outside = os.path.join(self.base, "outside.png")
        Path(outside).write_bytes(b"MINE")
        fd = self.opened(outside)
        self.assertRefused("media_path_outside_volume", self.volume().require_descriptor, fd, outside)

    # -- configuration ---------------------------------------------------------------------------

    def test_from_env_requires_both_settings(self):
        self.assertConfig(f"{VOLUME_ROOT_ENV} is required", media_volume_from_env, {}, probe=self.probe)
        self.assertConfig(f"{VOLUME_ID_ENV} is required", media_volume_from_env,
                          {VOLUME_ROOT_ENV: self.root}, probe=self.probe)
        volume = media_volume_from_env({VOLUME_ROOT_ENV: self.root, VOLUME_ID_ENV: VOLUME_ID}, probe=self.probe)
        volume.require(self.out)


@unittest.skipUnless(sys.platform.startswith("linux") and os.path.ismount("/dev/shm"),
                     "needs Linux with /dev/shm mounted")
class RealProbeLinuxTests(unittest.TestCase):
    """The real SystemProbe end to end: mountinfo parsing, ismount and the system-volume check."""

    def test_real_tmpfs_mount_is_read_from_mountinfo(self):
        marker = os.path.join("/dev/shm", MARKER_NAME)
        if os.path.lexists(marker):
            self.skipTest("a marker already exists in /dev/shm; not touching it")
        Path(marker).write_text(VOLUME_ID)
        work = tempfile.mkdtemp(prefix="kaliv-g1-", dir="/dev/shm")
        try:
            probe = SystemProbe()
            self.assertEqual(probe.filesystem("/dev/shm"), "tmpfs")
            self.assertNotEqual(probe.system_volume_dev(), os.lstat("/dev/shm").st_dev)
            with self.assertRaises(MediaVolumeConfigError):  # tmpfs has no stable ids on disk
                MountedMediaVolume("/dev/shm", VOLUME_ID)
            volume = MountedMediaVolume("/dev/shm", VOLUME_ID, allowed_filesystems=frozenset({"tmpfs"}))
            volume.require(work)
            with self.assertRaises(ArtifactSinkUnavailable):
                volume.require(tempfile.gettempdir() if os.path.realpath(tempfile.gettempdir()) != "/dev/shm"
                               else "/")
        finally:
            os.unlink(marker)
            shutil.rmtree(work, ignore_errors=True)

    def test_the_real_probe_reads_the_mount_id_from_mountinfo(self):
        probe = SystemProbe()
        ids = {}
        with open("/proc/self/mountinfo", encoding="utf-8") as mounts:
            for line in mounts:
                fields = line.split()
                ids[fields[4]] = fields[0]  # the last mount at a point is the visible one
        self.assertEqual(probe.mount_instance("/"), ids["/"])
        self.assertIsNone(probe.mount_instance("/no/such/mount/point"))

    def test_root_filesystem_is_the_system_volume(self):
        self.assertEqual(SystemProbe().system_volume_dev(), os.stat("/").st_dev)


class PathSyntaxTests(unittest.TestCase):
    def test_windows_accepts_plain_drive_paths(self):
        for good in ("E:\\", "E:\\media", "e:/media/comfy/output", "E:\\media\\frame.png", "E:\\a\\b~1"):
            self.assertEqual(check_path_syntax(good, windows=True), good)

    def test_windows_refuses_aliases_namespaces_and_streams(self):
        for bad in ("\\\\?\\E:\\media", "\\\\.\\PhysicalDrive0", "\\\\server\\share\\media", "//server/share",
                    "E:media", "E:", "media\\x", "E:\\a\\..\\b", "E:\\a\\.\\b", "E:\\a\\file.png:secret",
                    "E:\\a\\name.", "E:\\a\\name ", "E:\\NUL", "E:\\a\\con.txt", "E:\\a\\COM1.log",
                    "E:\\a\\b<c", "E:\\a\\b|c", "E:\\a\\b?c", "E:\\a\\b*c", "E:\\a\\\x01b", "E:\\a\x00"):
            with self.assertRaises(ArtifactSinkUnavailable, msg=bad):
                check_path_syntax(bad, windows=True)

    def test_posix_refuses_relative_and_dot_segments(self):
        self.assertEqual(check_path_syntax("/mnt/media", windows=False), "/mnt/media")
        for bad in ("mnt/media", "./x", "/mnt/../etc", "/mnt/./media", "", "/a\x00b"):
            with self.assertRaises(ArtifactSinkUnavailable, msg=bad):
                check_path_syntax(bad, windows=False)


if __name__ == "__main__":
    unittest.main()
