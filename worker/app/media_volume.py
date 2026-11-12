"""G1: the production ``VerifiedMediaVolume`` (C1 of #2275 6669445071).

The protocol lives in ``media_generation_contract``. ``require(path)`` returns only if ``path`` lies
on the verified, currently mounted external media volume. Otherwise it raises
``ArtifactSinkUnavailable``.

This is where media is **published**: the gallery and every staged file. Generation happens in a
private work area on the internal disk (Anders, 6 Nov 2026, #2275; checked separately). A finished
file reaches the gallery only by being copied into a staged file here, checked, and published in
one atomic step.

**One volume.** The operator configures one external volume with two settings:

- ``KALIV_MEDIA_VOLUME_ROOT``: the volume's mount point, for example ``E:\\`` or ``/mnt/kaliv-media``.
- ``KALIV_MEDIA_VOLUME_ID``: an id the operator writes once into ``<root>/.kaliv-media-volume``.

**What is verified, fail-closed.**

At construction:

- The root is canonical. It has no symlink, junction, 8.3 alias, ``..`` or Windows namespace prefix.
- The root is a directory and a mount point.
- The root is not the system volume.
- The root is a local disk: not a network drive (``GetDriveTypeW``) and not a ``subst`` drive letter
  (``QueryDosDeviceW``), on Windows. POSIX network filesystems are already outside the allowed list.
- Its filesystem has stable file ids: NTFS, ReFS, ext4, xfs or btrfs. FAT32 and exFAT are refused,
  because they reuse ids after a rename (docs/MEDIA_VIDEO_GENERATION.md, rig item 9).
- The marker exists and matches the configured id.

The root's ``(st_dev, st_ino)`` is pinned at that moment.

On every ``verify()`` and ``require()``, all of that is checked again. The pinned identity must still
match, so a volume that went away, or came back as a different disk at the same path, is refused
until the executor restarts. That restart is exit 75, the same as a volume that is gone.

**What ``require(path)`` additionally refuses:**

- a path that is not canonical (it would resolve elsewhere);
- a path outside the root;
- any component that is a symlink or a Windows reparse point (junction, mounted folder);
- any component on another device (a filesystem mounted inside the volume);
- anything that is neither a directory nor a regular file.

**Limits.** These are checks, not handles. A process running as the same OS user could swap a
directory between the check and its use. That limit is shared with the rest of the media stack,
and the private work area guards against it (rig item 9). Nothing here mounts, creates or
deletes anything.

**Exit codes.** A configuration that can never work is ``MediaVolumeConfigError``, so the executor
exits 78. Examples: a malformed id, a FAT volume, the system disk. A volume that is not there right
now is ``ArtifactSinkUnavailable``, so the executor exits 75.
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

VOLUME_ROOT_ENV = "KALIV_MEDIA_VOLUME_ROOT"
VOLUME_ID_ENV = "KALIV_MEDIA_VOLUME_ID"
MARKER_NAME = ".kaliv-media-volume"
STABLE_ID_FILESYSTEMS = frozenset({"ntfs", "refs", "ext4", "xfs", "btrfs"})
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
DRIVE_REMOTE = 4  # GetDriveTypeW

_VOLUME_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{7,63}\Z")
_MAX_MARKER_BYTES = 128
_WINDOWS_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                               *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))})
_WINDOWS_BAD_CHARS = re.compile(r'[<>"|?*\x00-\x1f]')


class MediaVolumeConfigError(ValueError):
    """The media volume configuration can never work as given (exit 78)."""


def _refused(reason: str = "media_path_refused") -> ArtifactSinkUnavailable:
    return ArtifactSinkUnavailable(reason)


def check_path_syntax(path: object, *, windows: bool) -> str:
    """Return ``path`` if its meaning cannot depend on normalisation; otherwise raise.

    Refused on both platforms:
    - a non-string;
    - an empty path or a NUL;
    - a relative path;
    - ``.`` or ``..`` components.

    Refused on Windows only:
    - UNC and device namespaces (``\\\\server``, ``\\\\?\\``, ``\\\\.\\``);
    - alternate data streams (``:`` after the drive);
    - components with trailing dots or spaces (Win32 strips them, so they are aliases);
    - reserved device names (``NUL``, ``COM1`` and so on);
    - characters Win32 refuses.
    """
    if type(path) is not str or not path or "\x00" in path:
        raise _refused()
    if windows:
        if path.startswith(("\\\\", "//", "\\/", "/\\")):
            raise _refused()
        drive, rest = ntpath.splitdrive(path)
        if not re.fullmatch(r"[A-Za-z]:", drive) or not rest.startswith(("\\", "/")):
            raise _refused()
        for part in re.split(r"[\\/]", rest)[1:]:
            if not part:
                continue
            if (part in (".", "..") or ":" in part or part != part.rstrip(" .")
                    or _WINDOWS_BAD_CHARS.search(part)
                    or part.split(".")[0].rstrip(" ").upper() in _WINDOWS_RESERVED):
                raise _refused()
    else:
        if not path.startswith("/"):
            raise _refused()
        if any(part in (".", "..") for part in path.split("/")):
            raise _refused()
    return path


class SystemProbe:
    """The operating-system facts the volume check relies on. Tests replace parts of it."""

    windows = os.name == "nt"

    def lstat(self, path: str):
        return os.lstat(path)

    def fstat(self, fd: int):
        return os.fstat(fd)

    def ismount(self, path: str) -> bool:
        return os.path.ismount(path)

    def realpath(self, path: str) -> str:
        return os.path.realpath(path, strict=True)

    def system_volume_dev(self) -> int:
        """``st_dev`` of the volume the operating system runs from."""
        if self.windows:
            return os.stat(os.environ.get("SystemDrive", "C:") + "\\").st_dev
        return os.stat("/").st_dev

    def filesystem(self, root: str) -> str | None:
        """The filesystem type of the mount at ``root``, lower-case, or None if unknown."""
        if self.windows:
            import ctypes
            name = ctypes.create_unicode_buffer(64)
            target = root if root.endswith("\\") else root + "\\"
            ok = ctypes.windll.kernel32.GetVolumeInformationW(  # type: ignore[attr-defined]
                ctypes.c_wchar_p(target), None, 0, None, None, None, name, len(name))
            return name.value.lower() if ok and name.value else None
        mount = self._mountinfo(root)
        return mount[1] if mount else None

    def drive_kind(self, root: str) -> str | None:
        """Windows only: "remote" for a network drive, "subst" for a drive letter that ``subst`` maps to
        a folder, "local" otherwise, None if it cannot be read (for example no such letter). POSIX: always "local" (a network
        filesystem is already refused by ``STABLE_ID_FILESYSTEMS``).

        Without this the two cases relied only on ``realpath`` turning the letter into its UNC path or
        its target folder (#2275 backlog item 16). ``GetVolumeInformationW`` reports NTFS for many SMB
        shares, so the filesystem check alone does not catch them."""
        if not self.windows:
            return "local"
        import ctypes
        drive = root[:2]
        if len(drive) != 2 or drive[1] != ":":
            return None
        kind = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive + "\\"))  # type: ignore[attr-defined]
        if kind == DRIVE_REMOTE:
            return "remote"
        target = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.QueryDosDeviceW(ctypes.c_wchar_p(drive), target, len(target)):  # type: ignore[attr-defined]
            return None
        # A real volume is a \Device\... name; subst gives \??\<target folder>.
        return "subst" if target.value.startswith("\\??\\") else "local"

    def mount_instance(self, root: str) -> str | None:
        """This mounting of ``root``, where the platform names one: Linux's mount id, which a new
        mount of the same disk does not reuse. None on Windows, which has no such id (a volume's
        GUID and serial survive an unplug and replug), and wherever it cannot be read."""
        if self.windows:
            return None
        mount = self._mountinfo(root)
        return mount[0] if mount else None

    @staticmethod
    def _mountinfo(root: str) -> tuple[str, str] | None:
        """(mount id, filesystem type) of the visible mount at ``root``, from /proc/self/mountinfo."""
        found = None
        try:
            with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as mounts:
                for line in mounts:
                    left, sep, right = line.partition(" - ")
                    fields = left.split()
                    if not sep or len(fields) < 5 or not right.split():
                        continue
                    point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[4])
                    if point == root:
                        found = (fields[0], right.split()[0].lower())  # the last mount at a point is the visible one
        except OSError:
            return None
        return found


def _is_link(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0)
                                                & FILE_ATTRIBUTE_REPARSE_POINT)


class MountedMediaVolume:
    """The production ``VerifiedMediaVolume``.

    It is constructed once when the executor starts. A failure there raises
    ``MediaVolumeConfigError`` (exit 78) or ``ArtifactSinkUnavailable`` (exit 75).

    Integration (#2347; wiring follows in its own PR, and video stays default-off):
    - ``ExternalStagedVideoSink(media_root, verified_volume_root=volume.root)``;
    - the executor calls ``verify()`` before it claims a job.
    ComfyUI's folders and the job database are in the work area on the internal disk, not here.
    """

    def __init__(self, root: str, volume_id: str, *, probe: SystemProbe | None = None,
                 allowed_filesystems: frozenset[str] = STABLE_ID_FILESYSTEMS):
        self._probe = probe or SystemProbe()
        self._paths = ntpath if self._probe.windows else posixpath
        if type(volume_id) is not str or not _VOLUME_ID.fullmatch(volume_id):
            raise MediaVolumeConfigError("media_volume_id_invalid")
        try:
            check_path_syntax(root, windows=self._probe.windows)
        except ArtifactSinkUnavailable:
            raise MediaVolumeConfigError("media_volume_root_invalid") from None
        self._root = self._normal(root)
        self._volume_id = volume_id
        # Before anything else, so a network or subst letter is a configuration error (78) that stops
        # the executor, not "the disk is not here right now" (75) that it would wait on forever. A
        # letter that cannot be read (unplugged) is left to _observe_root: that is 75, as before.
        kind = self._probe.drive_kind(self._root)
        if kind in ("remote", "subst"):
            raise MediaVolumeConfigError(f"media_volume_{kind}_refused")
        info = self._observe_root()
        filesystem = self._probe.filesystem(self._root)
        if filesystem is None:
            raise MediaVolumeConfigError("media_volume_filesystem_unknown")
        if filesystem not in allowed_filesystems:
            raise MediaVolumeConfigError("media_volume_filesystem_refused")
        if info.st_dev == self._probe.system_volume_dev():
            raise MediaVolumeConfigError("media_volume_is_system_volume")
        self._identity = (info.st_dev, info.st_ino)
        self._mount = self._probe.mount_instance(self._root)
        self._lost: str | None = None
        self.filesystem = filesystem
        self._check_marker()
        self.root = Path(self._root)

    # -- helpers -------------------------------------------------------------------------------

    def _normal(self, path: str) -> str:
        return normal_path(path, windows=self._probe.windows)

    def _same(self, a: str, b: str) -> bool:
        return self._paths.normcase(a) == self._paths.normcase(b)

    def _observe_root(self):
        try:
            info = self._probe.lstat(self._root)
        except OSError:
            raise _refused("media_volume_missing") from None
        if _is_link(info):
            raise _refused("media_volume_root_link")
        if not stat.S_ISDIR(info.st_mode):
            raise _refused("media_volume_missing")
        if not self._probe.ismount(self._root):
            raise _refused("media_volume_not_mounted")
        try:
            real = self._probe.realpath(self._root)
        except OSError:
            raise _refused("media_volume_missing") from None
        if not self._same(self._normal(real), self._root):
            raise _refused("media_volume_root_not_canonical")
        return info

    def _check_marker(self) -> None:
        marker = self._paths.join(self._root, MARKER_NAME)
        try:
            before = self._probe.lstat(marker)
        except OSError:
            raise _refused("media_volume_marker_missing") from None
        if _is_link(before) or not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_MARKER_BYTES:
            raise _refused("media_volume_marker_refused")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(marker, flags)
        except OSError:
            raise _refused("media_volume_marker_missing") from None
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or not stat.S_ISREG(opened.st_mode):
                raise _refused("media_volume_marker_refused")
            data = os.read(fd, _MAX_MARKER_BYTES + 1)
        except OSError:
            raise _refused("media_volume_marker_missing") from None
        finally:
            os.close(fd)
        try:
            text = data.decode("ascii").strip()
        except UnicodeDecodeError:
            raise _refused("media_volume_marker_refused") from None
        if len(data) > _MAX_MARKER_BYTES or text != self._volume_id:
            raise _refused("media_volume_marker_mismatch")

    # -- the protocol --------------------------------------------------------------------------

    def verify(self) -> Path:
        """Re-check the volume itself: still the pinned, mounted, marked root. Returns the root.

        Once a check has failed, this verifier is done for good (Codex #2349 4498174484): while
        the volume is still wrong the real reason is raised, and once it looks right again,
        ``media_volume_lost``. Only a new verifier, i.e. an executor restart (exit 75), resumes,
        so a disk that went away and came back is never silently used again."""
        try:
            info = self._observe_root()
            if (info.st_dev, info.st_ino) != self._identity:
                raise _refused("media_volume_identity_changed")
            if self._mount is not None and self._probe.mount_instance(self._root) != self._mount:
                raise _refused("media_volume_remounted")  # the same disk, mounted again
            self._check_marker()
        except ArtifactSinkUnavailable as exc:
            self._lost = self._lost or str(exc)
            raise
        if self._lost is not None:
            raise _refused("media_volume_lost")
        return self.root

    def require(self, path: str | os.PathLike) -> None:
        """Return only if ``path`` is an existing directory or regular file on this volume."""
        raw = check_path_syntax(os.fspath(path), windows=self._probe.windows)
        self.verify()
        walk_within(self._root, raw, probe=self._probe, device=self._identity[0],
                    prefix="media_path", outside="media_path_outside_volume")

    def require_descriptor(self, fd: int, path: str | os.PathLike) -> os.stat_result:
        """Return only if the open descriptor ``fd`` is the file or directory ``path`` names here.

        Call it right after the open and before any byte is read or served. ``require(path)``
        proves where a name pointed when it was walked, but the descriptor is what is read.
        Between the two, a parent swapped for a link (``O_NOFOLLOW`` covers only the last
        component, and Windows has none), a reparse point, or an unmount that lets the mount
        point or drive letter fall back to the system disk can hand back another file. So the
        descriptor must be on the pinned device, be a regular file or directory, and be the very
        file (``st_dev``, ``st_ino``) that a verified walk of ``path`` finds after the open.
        Refuses with ``media_descriptor_unavailable|other_device|not_file_or_directory|not_path``
        or any reason of ``verify()`` and ``require()``. Written for the gallery's reads
        (#2275 6702693683, findings 1 and 3)."""
        raw = check_path_syntax(os.fspath(path), windows=self._probe.windows)
        self.verify()
        try:
            opened = self._probe.fstat(fd)
        except OSError:
            raise _refused("media_descriptor_unavailable") from None
        if opened.st_dev != self._identity[0]:
            raise _refused("media_descriptor_other_device")
        if not (stat.S_ISREG(opened.st_mode) or stat.S_ISDIR(opened.st_mode)):
            raise _refused("media_descriptor_not_file_or_directory")
        walked = walk_within(self._root, raw, probe=self._probe, device=self._identity[0],
                             prefix="media_path", outside="media_path_outside_volume")
        named = walked[-1][1] if walked else self._observe_root()
        if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
            raise _refused("media_descriptor_not_path")
        return opened


def normal_path(path: str, *, windows: bool) -> str:
    """Collapse doubled separators and drop a trailing one, but keep a drive root's (``E:\\``)."""
    norm = (ntpath if windows else posixpath).normpath(path)
    if windows and re.fullmatch(r"[A-Za-z]:", norm):
        norm += "\\"
    return norm


def walk_within(root: str, raw: str, *, probe: SystemProbe, device: int, prefix: str,
                outside: str) -> list[tuple[str, os.stat_result]]:
    """The walk behind ``require``, shared by the media volume and the work area.

    ``root`` is already normalised and verified; ``raw`` has passed ``check_path_syntax``. Returns
    only if ``raw`` is a canonical, existing directory or regular file under ``root``, with no link
    or reparse point and no other device in any component below the root. Returns every component
    walked, with its ``lstat``. Raises ``ArtifactSinkUnavailable`` with ``outside`` or
    ``<prefix>_missing|not_canonical|link|other_device|not_file_or_directory``.
    """
    windows = probe.windows
    paths = ntpath if windows else posixpath
    # Only this platform's separators, everywhere below: a backslash is an ordinary filename
    # character on POSIX, so treating it as one would check a different path, or let a sibling
    # of a root ending in a backslash pass containment (#2349 reviews 4491252681, 4491286902).
    separators = "\\/" if windows else "/"
    target = normal_path(raw, windows=windows)
    root_key = paths.normcase(root)
    target_key = paths.normcase(target)
    contained = root_key if root_key.endswith(tuple(separators)) else root_key + paths.sep
    if target_key != root_key and not target_key.startswith(contained):
        raise _refused(outside)
    try:
        real = probe.realpath(target)
    except OSError:
        raise _refused(f"{prefix}_missing") from None
    if paths.normcase(normal_path(real, windows=windows)) != target_key:
        raise _refused(f"{prefix}_not_canonical")
    # Walk every component below the root: no link or reparse point, no other device.
    relative = target[len(root):].lstrip(separators)
    current = root
    parts = [p for p in re.split(f"[{re.escape(separators)}]", relative) if p] if relative else []
    walked: list[tuple[str, os.stat_result]] = []
    info = None
    for part in parts:
        current = paths.join(current, part)
        try:
            info = probe.lstat(current)
        except OSError:
            raise _refused(f"{prefix}_missing") from None
        if _is_link(info):
            raise _refused(f"{prefix}_link")
        if info.st_dev != device:
            raise _refused(f"{prefix}_other_device")
        walked.append((current, info))
    if info is not None and not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise _refused(f"{prefix}_not_file_or_directory")
    return walked


def media_volume_from_env(env: Mapping[str, str] | None = None, *,
                          probe: SystemProbe | None = None) -> MountedMediaVolume:
    """Build the volume from ``KALIV_MEDIA_VOLUME_ROOT`` and ``KALIV_MEDIA_VOLUME_ID``.

    A missing setting is a configuration error (78), never a default.
    """
    env = os.environ if env is None else env
    root, volume_id = env.get(VOLUME_ROOT_ENV, ""), env.get(VOLUME_ID_ENV, "")
    if not root:
        raise MediaVolumeConfigError(f"{VOLUME_ROOT_ENV} is required")
    if not volume_id:
        raise MediaVolumeConfigError(f"{VOLUME_ID_ENV} is required")
    return MountedMediaVolume(root, volume_id, probe=probe)
