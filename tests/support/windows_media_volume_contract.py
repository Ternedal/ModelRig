"""Real-Windows contract for the production media volume check (G1, C1 of #2275 6669445071).

Run on the Windows gate: ``PYTHONPATH=worker python tests/support/windows_media_volume_contract.py``.

It uses the real SystemProbe throughout:
- ``GetVolumeInformationW`` for the filesystem;
- the volume serial as ``st_dev``;
- ``os.path.ismount``;
- ``os.path.realpath`` (which resolves junctions and long names).

**What it checks:**
- The system drive is refused even though it is a mounted NTFS volume.
- On the workspace's own volume (a separate disk on hosted runners):
  - a canonical directory is accepted;
  - a junction, an alternate data stream, a trailing-dot alias, an 8.3 short name and a path on
    the system drive are each refused.
  - ``require_descriptor``: an open file on the volume passes (``os.fstat`` and ``os.lstat``
    agree on volume serial and file id on NTFS); a descriptor on the system drive is refused; a
    file opened through a junction that is then swapped for a real folder is refused.

**What it changes:** it writes the marker ``<volume>\\.kaliv-media-volume`` for the run and removes it
afterwards. If the workspace shares the system drive, or the volume root cannot be written, those
cases are reported as NOT RUN with the reason. They are never counted as passes.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.media_generation_contract import ArtifactSinkUnavailable, VerifiedMediaVolume  # noqa: E402
from app.media_volume import (  # noqa: E402
    FILE_ATTRIBUTE_REPARSE_POINT, MARKER_NAME, MediaVolumeConfigError, MountedMediaVolume, SystemProbe,
)

VOLUME_ID = "kaliv-contract-0001"
passed = failed = not_run = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def skip(name: str, why: str) -> None:
    global not_run
    not_run += 1
    print(f"  NOT RUN: {name} ({why})")


def refused(volume: MountedMediaVolume, path: str) -> str | None:
    try:
        volume.require(path)
    except ArtifactSinkUnavailable as exc:
        return str(exc)
    return None


def descriptor_refused(volume: MountedMediaVolume, fd: int, path: str) -> str | None:
    try:
        volume.require_descriptor(fd, path)
        return None
    except ArtifactSinkUnavailable as exc:
        return str(exc)


def opened(path: str) -> int:
    return os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))


def short_name(path: str) -> str:
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))  # type: ignore[attr-defined]
    return buf.value if n else path


def main() -> int:
    if os.name != "nt":
        print("windows_media_volume_contract: Windows only")
        return 2
    probe = SystemProbe()
    system_root = os.environ.get("SystemDrive", "C:") + "\\"
    print(f"system drive {system_root}: filesystem={probe.filesystem(system_root)} mount={probe.ismount(system_root)}")
    check(probe.filesystem(system_root) in ("ntfs", "refs"), "GetVolumeInformationW reads the system drive's filesystem")
    try:
        MountedMediaVolume(system_root, VOLUME_ID)
        check(False, "the system drive is refused as the media volume")
    except MediaVolumeConfigError as exc:
        check(str(exc) == "media_volume_is_system_volume", f"the system drive is refused as the media volume ({exc})")

    workspace = os.path.realpath(os.environ.get("GITHUB_WORKSPACE") or os.getcwd())
    volume_root = os.path.splitdrive(workspace)[0] + "\\"
    print(f"workspace volume {volume_root}: filesystem={probe.filesystem(volume_root)} "
          f"mount={probe.ismount(volume_root)} dev={os.stat(volume_root).st_dev} "
          f"system_dev={probe.system_volume_dev()}")
    positive = ("a canonical directory on a separate volume is accepted, and its aliases refused")
    if os.path.normcase(volume_root) == os.path.normcase(system_root):
        skip(positive, "the workspace is on the system drive")
        return summary()
    marker = Path(volume_root, MARKER_NAME)
    if marker.exists():
        skip(positive, f"{marker} already exists; not touching it")
        return summary()
    try:
        marker.write_text(VOLUME_ID, encoding="ascii")
    except OSError as exc:
        skip(positive, f"cannot write {marker}: {exc}")
        return summary()
    try:
        volume = MountedMediaVolume(volume_root, VOLUME_ID)
        check(isinstance(volume, VerifiedMediaVolume), "the volume satisfies the VerifiedMediaVolume protocol")
        check(volume.filesystem in ("ntfs", "refs"), f"filesystem accepted: {volume.filesystem}")
        work = os.path.realpath(tempfile.mkdtemp(prefix="kaliv-g1-", dir=workspace))
        target = os.path.join(work, "LongTargetDirectoryName")
        os.mkdir(target)
        Path(target, "frame.png").write_bytes(b"x")
        check(refused(volume, work) is None, "a canonical directory on the volume is accepted")
        check(refused(volume, os.path.join(target, "frame.png")) is None, "a regular file on the volume is accepted")
        check(refused(volume, work.upper()) is None, "a case-only difference is the same path on Windows")

        junction = os.path.join(work, "junction")
        made = subprocess.run(["cmd", "/c", "mklink", "/J", junction, target], capture_output=True, text=True)
        if made.returncode == 0:
            attrs = os.lstat(junction).st_file_attributes
            check(bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT), "the junction carries the reparse attribute")
            check(refused(volume, junction) is not None, f"a junction is refused ({refused(volume, junction)})")
            inner = os.path.join(junction, "frame.png")
            check(refused(volume, inner) is not None, f"a path through a junction is refused ({refused(volume, inner)})")
        else:
            skip("junction refused", f"mklink /J failed: {made.stdout} {made.stderr}")

        ads = os.path.join(target, "frame.png:hidden")
        check(refused(volume, ads) == "media_path_refused", "an alternate data stream is refused")
        check(refused(volume, target + ".") == "media_path_refused", "a trailing-dot alias is refused")
        check(refused(volume, target + " ") == "media_path_refused", "a trailing-space alias is refused")
        check(refused(volume, "\\\\?\\" + target) == "media_path_refused", "the \\\\?\\ namespace is refused")
        short = short_name(target)
        if os.path.normcase(short) != os.path.normcase(target):
            check(refused(volume, short) == "media_path_not_canonical", f"an 8.3 short name is refused ({short})")
        else:
            skip("8.3 short name refused", "8.3 names are disabled on this volume")
        windows_dir = os.path.join(system_root, "Windows")
        check(refused(volume, windows_dir) == "media_path_outside_volume", "a path on the system drive is refused")

        # require_descriptor: the gallery's reads (#2275 6702693683). Windows has no O_NOFOLLOW, so
        # these are the cases the descriptor check exists for.
        on_volume = os.path.join(target, "frame.png")
        fd = opened(on_volume)
        try:
            check(descriptor_refused(volume, fd, on_volume) is None,
                  "an open file on the volume passes require_descriptor (fstat and lstat agree)")
        finally:
            os.close(fd)
        elsewhere = tempfile.NamedTemporaryFile(delete=False)  # %TEMP%: the system drive
        elsewhere.write(b"x")
        elsewhere.close()
        fd = opened(elsewhere.name)
        try:
            reason = descriptor_refused(volume, fd, on_volume)
            check(reason == "media_descriptor_other_device",
                  f"a descriptor on the system drive is refused for a path on the volume ({reason})")
        finally:
            os.close(fd)
            os.unlink(elsewhere.name)
        swap = os.path.join(work, "swap")
        made = subprocess.run(["cmd", "/c", "mklink", "/J", swap, target], capture_output=True, text=True)
        if made.returncode == 0:
            fd = opened(os.path.join(swap, "frame.png"))  # follows the junction into target
            try:
                subprocess.run(["cmd", "/c", "rmdir", swap], check=True, capture_output=True)  # the junction only
                os.mkdir(swap)
                Path(swap, "frame.png").write_bytes(b"x")  # same name, same size, another file
                reason = descriptor_refused(volume, fd, os.path.join(swap, "frame.png"))
                check(reason == "media_descriptor_not_path",
                      f"a file opened through a junction later swapped for a folder is refused ({reason})")
            finally:
                os.close(fd)
        else:
            skip("junction swap refused by require_descriptor", f"mklink /J failed: {made.stdout} {made.stderr}")
        marker.write_text("kaliv-contract-9999", encoding="ascii")
        check(refused(volume, work) == "media_volume_marker_mismatch", "a changed marker is refused after start")
    finally:
        try:
            marker.unlink()
        except OSError as exc:
            print(f"  WARN: could not remove {marker}: {exc}")
    return summary()


def summary() -> int:
    print(f"\n===== Windows media volume contract: {passed} passed, {failed} failed, {not_run} not run =====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
