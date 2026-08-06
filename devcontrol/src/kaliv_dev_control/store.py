"""Crash-durable, locked compare-and-swap campaign persistence."""
from __future__ import annotations

import ctypes
import json
import os
import re
import secrets
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from .campaign import DevelopmentCampaign
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    replace_file_durable,
    sync_directory,
    unlink_durable,
)

_CAMPAIGN_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_LOCK_SCHEMA = "kaliv-development-campaign-lock/v1"
_LOCK_MAX = 4096
_RECORD_MAX = 8_000_000


class CampaignStoreError(RuntimeError):
    """Campaign persistence failed or detected stale/tampered state."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _windows_identity(pid: int) -> str | None:
    """Bind a Windows PID to its kernel process creation timestamp."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    get_process_times = kernel32.GetProcessTimes
    get_process_times.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    get_process_times.restype = ctypes.c_int

    handle = open_process(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        code = ctypes.get_last_error()
        if code in {87, 1168}:  # invalid parameter / not found
            return ""
        return None
    try:
        created = FileTime()
        exited = FileTime()
        kernel = FileTime()
        user = FileTime()
        if not get_process_times(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        ticks = (int(created.high) << 32) | int(created.low)
        return f"windows:{ticks}"
    finally:
        close_handle(handle)


def _identity(pid: int) -> str | None:
    """Return stable live-process identity, empty for dead, None if unverifiable."""
    if os.name == "nt":
        return _windows_identity(pid)
    proc = Path("/proc")
    if os.name == "posix" and proc.is_dir():
        try:
            text = (proc / str(pid) / "stat").read_text(encoding="ascii")
            boot = (proc / "sys/kernel/random/boot_id").read_text(
                encoding="ascii"
            ).strip()
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeError):
            return None
        close = text.rfind(")")
        fields = text[close + 2 :].split() if close >= 0 else []
        if len(fields) < 20 or not fields[19].isdigit() or not boot:
            return None
        return f"linux:{boot}:{fields[19]}"
    return None


class CampaignStore:
    """Persist one canonical JSON object per campaign under a controlled root."""

    def __init__(self, root: Path) -> None:
        configured = Path(root)
        self.configured_root = (
            configured if configured.is_absolute() else configured.absolute()
        )
        self.root = self.configured_root.resolve(strict=False)

    @staticmethod
    def _linkish(path: Path) -> bool:
        if path.is_symlink():
            return True
        junction = getattr(path, "is_junction", None)
        return bool(junction is not None and junction())

    def _prepare_root(self) -> None:
        missing: list[Path] = []
        cursor = self.configured_root
        while not cursor.exists():
            if cursor.parent == cursor:
                raise CampaignStoreError("campaign store has no existing ancestor")
            missing.append(cursor)
            cursor = cursor.parent
        probe = cursor
        while True:
            if self._linkish(probe):
                raise CampaignStoreError("campaign store path must be link-free")
            if probe.parent == probe:
                break
            probe = probe.parent
        if not cursor.is_dir():
            raise CampaignStoreError("campaign store ancestor is not a directory")
        try:
            for directory in reversed(missing):
                directory.mkdir(mode=0o700)
                sync_directory(directory.parent.resolve())
        except (OSError, DurablePublicationError) as exc:
            raise CampaignStoreError(
                "campaign store root was not durably created"
            ) from exc
        self.root = self.configured_root.resolve()
        if self._linkish(self.root) or not self.root.is_dir():
            raise CampaignStoreError("campaign store root is irregular")

    def path(self, campaign_id: str) -> Path:
        if (
            not isinstance(campaign_id, str)
            or _CAMPAIGN_ID.fullmatch(campaign_id) is None
        ):
            raise CampaignStoreError("campaign id cannot be used as a filename")
        return self.root / f"{campaign_id}.json"

    def _lock_path(self, campaign_id: str) -> Path:
        return self.root / f".{campaign_id}.lock"

    @staticmethod
    def _read_bounded(path: Path, maximum: int) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise CampaignStoreError(
                "store record cannot be opened safely"
            ) from exc
        try:
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                raise CampaignStoreError(
                    "store record is not a single regular file"
                )
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > maximum:
                raise CampaignStoreError("store record exceeds bound")
            return data
        except OSError as exc:
            raise CampaignStoreError("store record cannot be read") from exc
        finally:
            os.close(descriptor)

    @staticmethod
    def _parse_lock(raw: bytes) -> dict[str, Any]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("campaign lock is malformed") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "pid",
            "identity",
            "nonce",
        }:
            raise CampaignStoreError("campaign lock fields mismatch")
        if value["schema"] != _LOCK_SCHEMA:
            raise CampaignStoreError("campaign lock schema is unsupported")
        if (
            isinstance(value["pid"], bool)
            or not isinstance(value["pid"], int)
            or value["pid"] <= 0
            or not isinstance(value["identity"], str)
            or not value["identity"]
            or not isinstance(value["nonce"], str)
            or len(value["nonce"]) != 64
            or any(ch not in "0123456789abcdef" for ch in value["nonce"])
        ):
            raise CampaignStoreError("campaign lock identity is invalid")
        return value

    def _reclaim_stale_lock(self, lock: Path) -> bool:
        if self._linkish(lock):
            raise CampaignStoreError("campaign lock must not be a link")
        try:
            before = lock.stat(follow_symlinks=False)
        except FileNotFoundError:
            return True
        raw = self._read_bounded(lock, _LOCK_MAX)
        record = self._parse_lock(raw)
        current = _identity(record["pid"])
        if current is None:
            raise CampaignStoreError("campaign lock owner cannot be verified")
        if current and current == record["identity"]:
            return False
        try:
            after = lock.stat(follow_symlinks=False)
        except FileNotFoundError:
            return True
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_size,
        ):
            raise CampaignStoreError("campaign lock changed during recovery")
        if self._read_bounded(lock, _LOCK_MAX) != raw:
            raise CampaignStoreError(
                "campaign lock contents changed during recovery"
            )
        try:
            unlink_durable(lock)
        except DurablePublicationError as exc:
            raise CampaignStoreError(
                "stale campaign lock was not durably removed"
            ) from exc
        return True

    @contextmanager
    def _exclusive_lock(self, campaign_id: str) -> Iterator[None]:
        lock = self._lock_path(campaign_id)
        pid = os.getpid()
        identity = _identity(pid)
        if not identity:
            raise CampaignStoreError(
                "current process identity cannot be established"
            )
        record = _canonical(
            {
                "schema": _LOCK_SCHEMA,
                "pid": pid,
                "identity": identity,
                "nonce": secrets.token_hex(32),
            }
        )
        acquired: os.stat_result | None = None
        for _ in range(3):
            try:
                create_once_file(lock, record)
                acquired = lock.stat(follow_symlinks=False)
                break
            except FileExistsError as exc:
                if not self._reclaim_stale_lock(lock):
                    raise CampaignStoreError(
                        "campaign is locked by another live operation"
                    ) from exc
            except (OSError, DurablePublicationError) as exc:
                raise CampaignStoreError(
                    "campaign lock could not be acquired durably"
                ) from exc
        if acquired is None:
            raise CampaignStoreError("campaign lock recovery did not converge")
        try:
            # create_once_file already persists the directory entry; this
            # explicit sync keeps the lock boundary independently auditable.
            sync_directory(self.root)
            yield
        except DurablePublicationError as exc:
            raise CampaignStoreError("campaign lock durability failed") from exc
        finally:
            if self._linkish(lock):
                raise CampaignStoreError("campaign lock ownership changed")
            try:
                observed = lock.stat(follow_symlinks=False)
            except FileNotFoundError as exc:
                raise CampaignStoreError("campaign lock disappeared") from exc
            if (observed.st_dev, observed.st_ino) != (
                acquired.st_dev,
                acquired.st_ino,
            ):
                raise CampaignStoreError("campaign lock ownership changed")
            if self._read_bounded(lock, _LOCK_MAX) != record:
                raise CampaignStoreError("campaign lock ownership changed")
            try:
                unlink_durable(lock)
            except DurablePublicationError as exc:
                raise CampaignStoreError(
                    "campaign lock was not durably released"
                ) from exc

    def _read(self, path: Path) -> DevelopmentCampaign:
        if self._linkish(path) or not path.is_file():
            raise CampaignStoreError("campaign record is missing or irregular")
        raw = self._read_bounded(path, _RECORD_MAX)
        if b"\x00" in raw:
            raise CampaignStoreError("campaign record is outside bounds")
        try:
            return DevelopmentCampaign.from_mapping(
                json.loads(raw.decode("utf-8"))
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise CampaignStoreError("campaign record does not verify") from exc

    def create(self, campaign: DevelopmentCampaign) -> Path:
        campaign.verify()
        self._prepare_root()
        path = self.path(campaign.campaign_id)
        payload = (campaign.canonical_json() + "\n").encode("utf-8")
        with self._exclusive_lock(campaign.campaign_id):
            if path.exists() or self._linkish(path):
                raise CampaignStoreError("campaign already exists")
            try:
                create_once_file(path, payload)
            except (FileExistsError, DurablePublicationError) as exc:
                raise CampaignStoreError(
                    "campaign could not be created durably"
                ) from exc
        return path

    def load(self, campaign_id: str) -> DevelopmentCampaign:
        self._prepare_root()
        return self._read(self.path(campaign_id))

    def save(
        self,
        campaign: DevelopmentCampaign,
        *,
        expected_previous_event_sha256: str,
    ) -> Path:
        campaign.verify()
        self._prepare_root()
        path = self.path(campaign.campaign_id)
        payload = (campaign.canonical_json() + "\n").encode("utf-8")
        with self._exclusive_lock(campaign.campaign_id):
            current = self._read(path)
            current_head = current.events[-1].event_sha256
            if current_head != expected_previous_event_sha256:
                raise CampaignStoreError(
                    "campaign compare-and-swap precondition failed"
                )
            if (
                campaign.campaign_id != current.campaign_id
                or campaign.task_id != current.task_id
                or campaign.task_sha256 != current.task_sha256
                or campaign.base_sha != current.base_sha
                or len(campaign.events) != len(current.events) + 1
                or campaign.events[:-1] != current.events
                or campaign.events[-1].previous_event_sha256 != current_head
            ):
                raise CampaignStoreError(
                    "campaign update is not one valid append"
                )
            temporary: Path | None = None
            try:
                descriptor, name = tempfile.mkstemp(
                    dir=self.root,
                    prefix=f".{campaign.campaign_id}.",
                    suffix=".pending",
                )
                temporary = Path(name)
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                replace_file_durable(temporary, path)
                temporary = None
            except (OSError, DurablePublicationError) as exc:
                raise CampaignStoreError(
                    "campaign update could not be committed durably"
                ) from exc
            finally:
                if temporary is not None and temporary.exists():
                    try:
                        unlink_durable(temporary)
                    except DurablePublicationError as exc:
                        raise CampaignStoreError(
                            "campaign temporary file was not durably removed"
                        ) from exc
        return path
