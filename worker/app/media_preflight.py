"""Operator preflight for the C:/Z: media layout (ChatGPT 6689780350 P2/P3; R17).

Run before media is switched on, and after any change to the accounts, the work area or the disk.
It checks, on this machine and at this moment:

- the work area (``PrivateWorkArea``): canonical, private, local, stable file ids;
- the job database and its ``-wal``, ``-shm`` and ``-journal`` files: inside it and private;
- the publication volume (``MountedMediaVolume``): mounted, marked, not the system disk, and a
  different disk than the work area;
- free space on both against a minimum;
- that every named process (``pids``: the supervisor, worker, server, executor) runs as this
  account: on Windows the token's user SID, on POSIX the effective user id (as the code reads it);
- whether the executor switch is on (reported, not judged).

It prints evidence, never a prompt or a secret: paths, SIDs or user ids, sizes and reason codes.
It changes nothing. A pass is evidence for this machine now; it is **not** a physical
qualification of the rig (that is R17, run by Anders).
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Iterable, Mapping

from .media_generation_contract import ArtifactSinkUnavailable
from .media_volume import MediaVolumeConfigError, MountedMediaVolume, SystemProbe
from .media_work_area import MediaWorkAreaConfigError, PrivateWorkArea, WorkAreaProbe

SCHEMA = "kaliv-media-preflight/v1"
GIB = 1024 ** 3
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def current_account() -> str:
    """This process's account: the user SID on Windows, the effective user id on POSIX."""
    if os.name == "nt":
        from .credential_acl_windows import _Api
        return _Api().process_sid()
    return str(os.geteuid())


def process_account(pid: int) -> str | None:
    """The account another process runs as, or None if it cannot be read (gone, or not allowed)."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_sid(pid)
    try:
        with open(f"/proc/{pid}/status", encoding="ascii", errors="replace") as status:
            for line in status:
                if line.startswith("Uid:"):
                    return line.split()[2]  # the effective user id, as current_account()
    except OSError:
        return None
    return None


def _windows_process_sid(pid: int) -> str | None:
    import ctypes
    from .credential_acl_windows import (ERROR_INSUFFICIENT_BUFFER, TOKEN_QUERY, TOKEN_USER, CredentialAclUnavailable,
                                         _Api, _TOKEN_USER)
    api = _Api()
    api.k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    api.k32.OpenProcess.restype = ctypes.c_void_p
    process = api.k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not process:
        return None
    token = ctypes.c_void_p()
    try:
        if not api.adv.OpenProcessToken(ctypes.c_void_p(process), TOKEN_QUERY, ctypes.byref(token)):
            return None
        needed = ctypes.c_uint32()
        api.adv.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(needed))
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER or not needed.value:
            return None
        storage = ctypes.create_string_buffer(needed.value)
        if not api.adv.GetTokenInformation(token, TOKEN_USER, storage, needed.value, ctypes.byref(needed)):
            return None
        user = ctypes.cast(storage, ctypes.POINTER(_TOKEN_USER)).contents
        try:
            return api.sid_string(int(user.User.Sid or 0))
        except CredentialAclUnavailable:
            return None
    finally:
        if token.value:
            api.k32.CloseHandle(token)
        api.k32.CloseHandle(ctypes.c_void_p(process))


def preflight(*, work_root: str, job_db: str, volume_root: str, volume_id: str, pids: Iterable[int] = (),
              min_free_gib_work: float = 5.0, min_free_gib_volume: float = 20.0,
              env: Mapping[str, str] | None = None, work_probe: WorkAreaProbe | None = None,
              volume_probe: SystemProbe | None = None) -> dict:
    """Evidence for the C:/Z: layout on this machine now. ``ok`` is True only if every check passed."""
    env = os.environ if env is None else env
    checks: list[dict] = []

    def check(name: str, ok: bool, detail) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    account = current_account()
    work = volume = None
    try:
        work = PrivateWorkArea(work_root, probe=work_probe)
        check("work_area", True, {"root": str(work.root), "filesystem": work.filesystem})
    except MediaWorkAreaConfigError as exc:
        check("work_area", False, str(exc))
    if work is not None:
        try:
            work.require(os.path.dirname(job_db))
            check("job_db_folder_in_work_area", True, os.path.dirname(job_db))
        except ArtifactSinkUnavailable as exc:
            check("job_db_folder_in_work_area", False, str(exc))
        for path in (job_db, job_db + "-wal", job_db + "-shm", job_db + "-journal"):
            if not os.path.lexists(path):
                continue
            try:
                work.require(path)
                check(f"private:{os.path.basename(path)}", True, path)
            except ArtifactSinkUnavailable as exc:
                check(f"private:{os.path.basename(path)}", False, str(exc))
    try:
        volume = MountedMediaVolume(volume_root, volume_id, probe=volume_probe)
        check("publication_volume", True, {"root": str(volume.root), "filesystem": volume.filesystem})
    except (MediaVolumeConfigError, ArtifactSinkUnavailable) as exc:
        check("publication_volume", False, str(exc))
    if work is not None and volume is not None:
        volume_dev = (volume_probe or SystemProbe()).lstat(str(volume.root)).st_dev
        check("separate_disks", work.device != volume_dev, "the work area must not be on the publication volume")
    for label, path, minimum in (("work_area", work_root, min_free_gib_work),
                                 ("publication_volume", volume_root, min_free_gib_volume)):
        try:
            free = shutil.disk_usage(path).free
        except OSError as exc:
            check(f"free_space:{label}", False, type(exc).__name__)
            continue
        check(f"free_space:{label}", free >= minimum * GIB,
              {"free_gib": round(free / GIB, 1), "minimum_gib": minimum})
    for pid in pids:
        owner = process_account(pid)
        check(f"same_account:pid {pid}", owner is not None and owner == account,
              {"account": owner, "expected": account})
    return {"schema": SCHEMA, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "account": account,
            "executor_switch": "on" if env.get("KALIV_MEDIA_EXECUTOR") == "1" else "off",
            "ok": all(c["ok"] for c in checks), "checks": checks,
            "note": "evidence for this machine at this moment; not a physical rig qualification"}
