"""G1: the production ``VerifiedMediaVolume`` (C1 of #2275 6669445071).

The protocol lives in ``media_generation_contract``. ``require(path)`` returns only if ``path`` lies
on the verified, currently mounted external media volume. Otherwise it raises
``ArtifactSinkUnavailable``. Media never lands on the internal disk, not even transiently.

**One volume.** The operator configures one external volume with two settings:

- ``KALIV_MEDIA_VOLUME_ROOT``: the volume's mount point, for example ``E:\\`` or ``/mnt/kaliv-media``.
- ``KALIV_MEDIA_VOLUME_ID``: an id the operator writes once into ``<root>/.kaliv-media-volume``.

**What is verified, fail-closed.**

At construction:

- The root is canonical. It has no symlink, junction, 8.3 alias, ``..`` or Windows namespace prefix.
- The root is a directory and a mount point.
- The root is not the system volume.
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
and the private output root guards against it (rig item 9). Nothing here mounts, creates or
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
        found = None
        try:
            with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as mounts:
                for line in mounts:
                    left, sep, right = line.partition(" - ")
                    fields = left.split()
                    if not sep or len(fields) < 5:
                        continue
                    point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[4])
                    if point == root:
                        found = right.split()[0].lower()  # the last mount at a point is the visible one
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

    Integration (#2346 / #2347; wiring follows in its own PR, and video stays default-off):
    - ``ExternalStagedVideoSink(media_root, verified_volume_root=volume.root)``;
    - the ComfyUI supervisor takes ``media_volume=volume``;
    - ``ImageJobStore(db, volume_guard=volume.verify)``.
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
        info = self._observe_root()
        filesystem = self._probe.filesystem(self._root)
        if filesystem is None:
            raise MediaVolumeConfigError("media_volume_filesystem_unknown")
        if filesystem not in allowed_filesystems:
            raise MediaVolumeConfigError("media_volume_filesystem_refused")
        if info.st_dev == self._probe.system_volume_dev():
            raise MediaVolumeConfigError("media_volume_is_system_volume")
        self._identity = (info.st_dev, info.st_ino)
        self.filesystem = filesystem
        self._check_marker()
        self.root = Path(self._root)

    # -- helpers -------------------------------------------------------------------------------

    def _normal(self, path: str) -> str:
        """Collapse doubled separators and drop a trailing one, but keep a drive root's (``E:\\``)."""
        norm = self._paths.normpath(path)
        if self._probe.windows and re.fullmatch(r"[A-Za-z]:", norm):
            norm += "\\"
        return norm

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
        """Re-check the volume itself: still the pinned, mounted, marked root. Returns the root."""
        info = self._observe_root()
        if (info.st_dev, info.st_ino) != self._identity:
            raise _refused("media_volume_identity_changed")
        self._check_marker()
        return self.root

    def require(self, path: str | os.PathLike) -> None:
        """Return only if ``path`` is an existing directory or regular file on this volume."""
        raw = check_path_syntax(os.fspath(path), windows=self._probe.windows)
        self.verify()
        target = self._normal(raw)
        root_key = self._paths.normcase(self._root)
        target_key = self._paths.normcase(target)
        prefix = root_key if root_key.endswith(("\\", "/")) else root_key + self._paths.sep
        if target_key != root_key and not target_key.startswith(prefix):
            raise _refused("media_path_outside_volume")
        try:
            real = self._probe.realpath(target)
        except OSError:
            raise _refused("media_path_missing") from None
        if not self._same(self._normal(real), target):
            raise _refused("media_path_not_canonical")
        # Walk every component below the root: no link or reparse point, no other device.
        # Only this platform's separators: a backslash is an ordinary filename character on POSIX,
        # so splitting on it there would inspect a different path (#2349 review 4491252681).
        separators = "\\/" if self._probe.windows else "/"
        relative = target[len(self._root):].lstrip(separators)
        current = self._root
        parts = [p for p in re.split(f"[{re.escape(separators)}]", relative) if p] if relative else []
        info = None
        for part in parts:
            current = self._paths.join(current, part)
            try:
                info = self._probe.lstat(current)
            except OSError:
                raise _refused("media_path_missing") from None
            if _is_link(info):
                raise _refused("media_path_link")
            if info.st_dev != self._identity[0]:
                raise _refused("media_path_other_device")
        if info is not None and not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise _refused("media_path_not_file_or_directory")


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
