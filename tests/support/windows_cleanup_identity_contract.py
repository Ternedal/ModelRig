"""Native contract: ComfyUI output cleanup deletes only its own file (#2316 review 6505072747).

Windows has no dir_fd, so the adapter's cleanup runs by path there. This proves,
on a real Windows filesystem (NTFS on the runner), the assumptions the
by-path cleanup rests on:

1. a file keeps its (st_dev, st_ino) across a rename in the same directory,
   so the job's own output is recognised after it is captured and removed;
2. a file swapped in under the same name has another identity and survives
   under its own name;
3. the restore never overwrites: if the name has been taken again, both
   files survive and the captured one is reported under its quarantine name;
4. a file that is still open (Windows: no FILE_SHARE_DELETE) cannot be
   captured and is left in place, reported, never half-handled.

Wired into the Windows isolation gate:
``PYTHONPATH=worker python tests/support/windows_cleanup_identity_contract.py``.
It also runs on POSIX (where (4) does not apply and says so). On the rig, pass
a directory on the media volume (rig check 9) to prove it on that filesystem;
a temporary folder is created inside it and removed afterwards:
``PYTHONPATH=worker python tests/support/windows_cleanup_identity_contract.py E:\\kaliv-media``.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

import app.comfy_video_adapter as adapter_module  # noqa: E402
from app.comfy_video_adapter import ComfyVideoAdapter  # noqa: E402

WINDOWS = os.name == "nt"
failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message)
    if not condition:
        failures.append(message)


def identity(path: Path) -> tuple[int, int]:
    info = os.stat(path, follow_symlinks=False)
    return info.st_dev, info.st_ino


def windows_filesystem(path: str) -> str | None:
    """The filesystem name of the volume holding `path` (e.g. NTFS, ReFS, exFAT), or None."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    k32.GetVolumePathNameW.restype = wintypes.BOOL
    k32.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.LPDWORD,
                                          wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPWSTR, wintypes.DWORD]
    k32.GetVolumeInformationW.restype = wintypes.BOOL
    root = ctypes.create_unicode_buffer(1024)
    if not k32.GetVolumePathNameW(path, root, len(root)):
        return None
    name = ctypes.create_unicode_buffer(64)
    if not k32.GetVolumeInformationW(root.value, None, 0, None, None, None, name, len(name)):
        return None
    return name.value


def write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        print("usage: windows_cleanup_identity_contract.py [directory on the volume to test]")
        return 64
    base = argv[0] if argv else None
    if base is not None and not os.path.isdir(base):
        print(f"FAILED: {base} is not an existing directory")
        return 64
    with tempfile.TemporaryDirectory(dir=base, prefix="kaliv-cleanup-contract-") as tmp:
        print(f"testing in {tmp}")
        out = Path(tmp)
        adapter = object.__new__(ComfyVideoAdapter)  # only output_directory is used by the cleanup step
        adapter.output_directory = out
        cleanup = adapter._delete_if_same  # by path: dir_fd=None, as on Windows

        def leftovers() -> list[str]:
            return sorted(os.listdir(out))

        # 0. the volume's filesystem keeps file ids stable (FAT32/exFAT derive them from entry positions)
        if WINDOWS:
            filesystem = windows_filesystem(tmp)
            check(filesystem in ("NTFS", "ReFS"), f"the volume's filesystem has stable file ids: {filesystem}")
        else:
            print("skip (0) filesystem name: checked on Windows only")

        # 1. our own file: identity survives the capture rename, so it is removed
        ours = out / "kaliv_ours.mp4"
        ours.write_bytes(b"ours")
        dev, ino = identity(ours)
        check(ino != 0, f"the filesystem reports a file id (st_ino={ino})")
        moved = out / "renamed-probe"
        os.rename(ours, moved)
        check(identity(moved) == (dev, ino), "a rename in the same directory keeps (st_dev, st_ino)")
        os.rename(moved, ours)
        check(cleanup("kaliv_ours.mp4", dev, ino, None) == "removed", "the job's own file is removed")
        check(leftovers() == [], f"nothing left behind: {leftovers()}")

        # 1b. already gone
        check(cleanup("kaliv_ours.mp4", dev, ino, None) == "gone", "a missing file is reported as gone")

        # 2. replaced under the same name before cleanup: kept, under its name, untouched
        target = out / "kaliv_job.mp4"
        target.write_bytes(b"ours")
        dev, ino = identity(target)
        write(target, b"someone else's")
        check(identity(target) != (dev, ino), "a swapped-in file has another identity")
        check(cleanup("kaliv_job.mp4", dev, ino, None) == "kept", "a replaced file is kept")
        check(leftovers() == ["kaliv_job.mp4"] and target.read_bytes() == b"someone else's",
              f"the replacement survives under its own name: {leftovers()}")
        target.unlink()

        # 3. the name is taken again between capture and restore: no overwrite, both survive
        target.write_bytes(b"ours")
        dev, ino = identity(target)
        write(target, b"first stranger")
        real_rename, real_link = adapter_module.os.rename, adapter_module.os.link
        calls = {"n": 0}

        def retake(dst) -> None:
            Path(out, os.path.basename(str(dst))).write_bytes(b"second stranger")

        def rename(src, dst, **kw):
            calls["n"] += 1
            if calls["n"] == 2:  # the restore (Windows path)
                retake(dst)
            return real_rename(src, dst, **kw)

        def link(src, dst, **kw):  # the restore (POSIX path)
            retake(dst)
            return real_link(src, dst, **kw)

        adapter_module.os.rename, adapter_module.os.link = rename, link
        try:
            outcome = cleanup("kaliv_job.mp4", dev, ino, None)
        finally:
            adapter_module.os.rename, adapter_module.os.link = real_rename, real_link
        check(outcome.startswith("kept:.kaliv-cleanup-"), f"reported under its quarantine name: {outcome}")
        contents = sorted(Path(out, n).read_bytes() for n in leftovers())
        check(contents == [b"first stranger", b"second stranger"], f"the restore never overwrites: {contents}")
        for name in leftovers():
            Path(out, name).unlink()

        # 4. still open (Windows sharing rules): cannot be captured, left in place
        if WINDOWS:
            busy = out / "kaliv_busy.mp4"
            busy.write_bytes(b"ours, still open")
            dev, ino = identity(busy)
            with open(busy, "rb"):
                outcome = cleanup("kaliv_busy.mp4", dev, ino, None)
            check(outcome == "PermissionError", f"an open file is not captured: {outcome}")
            check(leftovers() == ["kaliv_busy.mp4"], f"it stays under its own name: {leftovers()}")
            busy.unlink()
        else:
            print("skip (4) open-file sharing violation: Windows only")
    print(f"{'FAILED' if failures else 'OK'}: windows cleanup identity contract ({len(failures)} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
