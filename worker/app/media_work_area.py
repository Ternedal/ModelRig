"""The private work area on the internal disk (Anders, 6 Nov 2026, #2275 6686905826).

Generation happens here; publication happens on the external media volume (G1, ``media_volume``).
While a job runs, this folder holds:

- ComfyUI's input, output, temp and user folders, so partial frames and videos;
- the staged source image of an image-to-video job;
- the job database, which holds prompts until retention blanks them (#2340).

A finished file is copied into a staged file on the media volume, checked, and published to the
gallery in one atomic step (#2347). Only then is the copy here removed. The cross-volume copy is
not atomic, so the gallery never sees it until the staged file is complete and checked. A crash can
leave residue here; ``scripts/media_volume_repair.py`` reports it (C6).

**Configured** by ``KALIV_MEDIA_WORK_ROOT``: an existing folder the operator creates once, for
example ``C:\\Kaliv\\media-work`` (``docs/MEDIA_WORK_AREA.md`` has the commands). Nothing here
creates, moves or deletes anything.

**Checked at construction.** A failure is ``MediaWorkAreaConfigError``, so the executor exits 78:
the folder is local, so a failure is a configuration that will not fix itself.

- The path is absolute and canonical: no symlink, junction, 8.3 alias, ``..`` or Windows namespace
  prefix (``check_path_syntax`` and a ``realpath`` round trip).
- It is an existing directory, not a link or reparse point.
- It is on a local disk with stable file ids that fit a receipt (NTFS, ext4, xfs or btrfs; not ReFS), never a network
  share: the cleanup after a render deletes only files whose ``(st_dev, st_ino)`` it recorded.
- It is **private**. On POSIX: owned by the process user, and no access at all for group or others
  (mode ``0700`` or stricter). On Windows: owned by the process user, SYSTEM or Administrators, and
  no other principal holds any right beyond ``SYNCHRONIZE``, ``READ_CONTROL`` and
  ``FILE_READ_ATTRIBUTES``. Nobody else can list, read, write, delete or re-permission anything:
  ``credential_acl``'s rule, read through ``lease_dir_acl_windows``'s directory reader.

The root's ``(st_dev, st_ino)`` is pinned then.

**On every ``verify()`` and ``require(path)``**, all of that is checked again, and the pinned identity
must still match. ``require(path)`` also refuses:

- a path outside the root, or one that is not canonical;
- a link or reparse point in any component, or a component on another device;
- anything that is neither a directory nor a regular file;
- on Windows, any folder or file below the root whose own DACL is not private. Windows lets anyone
  traverse, and a file moved in from elsewhere on the same disk keeps its old ACL, so privacy must
  hold for each folder and file that is used, not only for the root.

A failure there is ``ArtifactSinkUnavailable`` (reason ``media_work_*``): the executor stops (75),
and its restart then refuses with 78 if the problem is still there.

**Limits.** As with G1, these are checks, not handles: a process running as the same OS user can
race them. What the private ACL gives is protection from other OS users.
"""
from __future__ import annotations

import ntpath
import os
import posixpath
import re
import stat
from pathlib import Path
from typing import Mapping

from .media_generation_contract import ArtifactSinkUnavailable
from .media_volume import (STABLE_ID_FILESYSTEMS, SystemProbe, _is_link, check_path_syntax, normal_path,
                           walk_within)

WORK_ROOT_ENV = "KALIV_MEDIA_WORK_ROOT"
# ReFS is left out (#2357 review P3-1). Its file ids can be 128-bit, and a hand-off receipt
# stores (st_dev, st_ino) as integers below 2**64 (image_job_store._nonnegative_int). Every
# video receipt on a ReFS work area would then be refused and the job failed. The refusal
# belongs at start, as 78. The media volume (Z:) keeps ReFS: its ids are compared, not stored.
WORK_AREA_FILESYSTEMS = STABLE_ID_FILESYSTEMS - {"refs"}
DRIVE_REMOTE = 4  # GetDriveTypeW


class MediaWorkAreaConfigError(ValueError):
    """The work area configuration can never work as given (exit 78)."""


def _refused(reason: str) -> ArtifactSinkUnavailable:
    return ArtifactSinkUnavailable(reason)


def _unescape_mount(field: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


class WorkAreaProbe(SystemProbe):
    """The operating-system facts the work-area check relies on. Tests replace parts of it."""

    mountinfo = "/proc/self/mountinfo"

    @property
    def acl_per_entry(self) -> bool:
        """Whether every folder and file used must itself be private. On Windows anyone may traverse
        (``SeChangeNotifyPrivilege``), and a folder or file can carry its own grants: a file moved in
        from elsewhere on the same disk keeps the ACL it had there. So the root's ACL alone proves
        nothing about what is below it. On POSIX a private root stops every other user."""
        return self.windows

    def containing_filesystem(self, path: str) -> tuple[str | None, bool]:
        """``(filesystem type, is a network drive)`` of the volume that holds ``path``."""
        if self.windows:
            import ctypes
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            volume = ctypes.create_unicode_buffer(261)
            if not k32.GetVolumePathNameW(ctypes.c_wchar_p(path), volume, len(volume)):
                return None, False
            remote = k32.GetDriveTypeW(ctypes.c_wchar_p(volume.value)) == DRIVE_REMOTE
            name = ctypes.create_unicode_buffer(64)
            ok = k32.GetVolumeInformationW(ctypes.c_wchar_p(volume.value), None, 0, None, None, None,
                                           name, len(name))
            return (name.value.lower() if ok and name.value else None), remote
        found, longest = None, -1
        try:
            with open(self.mountinfo, encoding="utf-8", errors="replace") as mounts:
                for line in mounts:
                    left, sep, right = line.partition(" - ")
                    fields = left.split()
                    if not sep or len(fields) < 5:
                        continue
                    point = _unescape_mount(fields[4])
                    inside = path == point or point == "/" or path.startswith(point.rstrip("/") + "/")
                    if inside and len(point) >= longest:  # the last mount at a point is the visible one
                        found, longest = right.split()[0].lower(), len(point)
        except OSError:
            return None, False
        # Network filesystems are simply not on the allowlist (nfs, cifs, smb3, 9p, fuse.*).
        return found, False

    def private(self, path: str, info: os.stat_result) -> tuple[bool, str]:
        """Whether only this user (and on Windows SYSTEM and Administrators) can use ``path``."""
        if self.windows:
            from .credential_acl import evaluate_credential_acl
            from .credential_acl_windows import CredentialAclUnavailable, read_credential_security
            from .lease_dir_acl_windows import read_lease_dir_security
            reader = read_lease_dir_security if stat.S_ISDIR(info.st_mode) else read_credential_security
            try:
                owner, dacl, process = reader(path)
            except CredentialAclUnavailable as exc:
                return False, f"security descriptor could not be verified: {exc}"
            except (OSError, ValueError, TypeError):
                return False, "security descriptor could not be verified"
            return evaluate_credential_acl(owner, dacl, process)
        if info.st_uid != os.geteuid():
            return False, "owned by another user"
        if info.st_mode & 0o077:
            return False, "group or others have access (needs mode 0700)"
        return True, "only the process user can use it"


class PrivateWorkArea:
    """Where generation happens: implements ``MediaWorkArea`` in ``media_generation_contract``."""

    def __init__(self, root: str, *, probe: WorkAreaProbe | None = None,
                 allowed_filesystems: frozenset[str] = WORK_AREA_FILESYSTEMS):
        self._probe = probe or WorkAreaProbe()
        self._paths = ntpath if self._probe.windows else posixpath
        try:
            check_path_syntax(root, windows=self._probe.windows)
        except ArtifactSinkUnavailable:
            raise MediaWorkAreaConfigError("media_work_area_root_invalid") from None
        self._root = normal_path(root, windows=self._probe.windows)
        try:
            info = self._observe_root()
        except ArtifactSinkUnavailable as exc:
            raise MediaWorkAreaConfigError(str(exc)) from None
        filesystem, remote = self._probe.containing_filesystem(self._root)
        if remote:
            raise MediaWorkAreaConfigError("media_work_area_network_drive")
        if filesystem is None:
            raise MediaWorkAreaConfigError("media_work_area_filesystem_unknown")
        if filesystem not in allowed_filesystems:
            raise MediaWorkAreaConfigError("media_work_area_filesystem_refused")
        self._identity = (info.st_dev, info.st_ino)
        self.filesystem = filesystem
        self.root = Path(self._root)

    @property
    def device(self) -> int:
        """``st_dev`` of the work area, pinned at construction."""
        return self._identity[0]

    def _observe_root(self) -> os.stat_result:
        try:
            info = self._probe.lstat(self._root)
        except OSError:
            raise _refused("media_work_area_missing") from None
        if _is_link(info):
            raise _refused("media_work_area_root_link")
        if not stat.S_ISDIR(info.st_mode):
            raise _refused("media_work_area_not_directory")
        try:
            real = self._probe.realpath(self._root)
        except OSError:
            raise _refused("media_work_area_missing") from None
        if self._paths.normcase(normal_path(real, windows=self._probe.windows)) != self._paths.normcase(self._root):
            raise _refused("media_work_area_root_not_canonical")
        private, why = self._probe.private(self._root, info)
        if not private:
            raise _refused(f"media_work_area_not_private: {why}")
        return info

    def verify(self) -> Path:
        """Re-check the root: still the pinned, canonical, private directory. Returns the root."""
        info = self._observe_root()
        if (info.st_dev, info.st_ino) != self._identity:
            raise _refused("media_work_area_identity_changed")
        return self.root

    def require(self, path: str | os.PathLike) -> None:
        """Return only if ``path`` is an existing directory or regular file in the work area."""
        raw = check_path_syntax(os.fspath(path), windows=self._probe.windows)
        self.verify()
        walked = walk_within(self._root, raw, probe=self._probe, device=self._identity[0],
                             prefix="media_work_path", outside="media_work_path_outside_work_area")
        if self._probe.acl_per_entry:
            for current, info in walked:
                if not self._probe.private(current, info)[0]:  # every folder, and the file itself
                    raise _refused("media_work_path_not_private")


def work_area_from_env(env: Mapping[str, str] | None = None, *,
                       probe: WorkAreaProbe | None = None) -> PrivateWorkArea:
    """Build the work area from ``KALIV_MEDIA_WORK_ROOT``. A missing setting is 78, never a default."""
    env = os.environ if env is None else env
    root = env.get(WORK_ROOT_ENV, "")
    if not root:
        raise MediaWorkAreaConfigError(f"{WORK_ROOT_ENV} is required")
    return PrivateWorkArea(root, probe=probe)
