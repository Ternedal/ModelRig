"""Atomic filesystem storage for validated `.mrbody` V1 packages.

M2.6 deliberately stores the complete data-only archive rather than extracting
it. The final `<bodyid>.mrbody` path is derived only from validated identity
metadata. A same-directory temporary sibling is fully written, fsynced and
revalidated before `os.replace()` becomes the single visible commit point.

Renderer activation, current-profile selection and visual/Unity acceptance are
separate gates and are intentionally absent here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from threading import RLock
import tempfile
from typing import Callable

from .mrbody import MAX_ARCHIVE_BYTES, MRBodyInspection, validate_mrbody


_BODYID_RE = re.compile(r"^bodyid-[0-9a-f]{24}$")


class MRBodyProfileStoreError(RuntimeError):
    """Filesystem profile-store operation failed without a package commit."""


class MRBodyProfileNotFoundError(MRBodyProfileStoreError):
    """Requested canonical body profile is not installed."""


class MRBodyStoredProfileError(MRBodyProfileStoreError):
    """Installed profile path is not a safe regular-file package."""


@dataclass(frozen=True, slots=True)
class MRBodyProfileReceipt:
    """Immutable receipt for one validated stored archive."""

    body_id: str
    name: str
    package_sha256: str
    size_bytes: int
    filename: str


@dataclass(frozen=True, slots=True)
class MRBodyStoredProfile:
    """Validated stored bytes plus their M2.5 inspection and receipt."""

    archive_bytes: bytes
    inspection: MRBodyInspection
    receipt: MRBodyProfileReceipt


FailureInjector = Callable[[str, Path], None]


def _canonical_body_id(value: object) -> str:
    if not isinstance(value, str) or _BODYID_RE.fullmatch(value) is None:
        raise MRBodyProfileStoreError("body_id must be a canonical bodyid-<24 lowercase hex>")
    return value


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _receipt(data: bytes, inspection: MRBodyInspection) -> MRBodyProfileReceipt:
    body_id = _canonical_body_id(inspection.body_id)
    return MRBodyProfileReceipt(
        body_id=body_id,
        name=inspection.name,
        package_sha256=_digest(data),
        size_bytes=len(data),
        filename=f"{body_id}.mrbody",
    )


def _bounded_read(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_ARCHIVE_BYTES + 1)
    except OSError as exc:
        raise MRBodyProfileStoreError(f"cannot read mrbody package: {path.name}") from exc
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise MRBodyProfileStoreError("mrbody package exceeds implementation archive safety cap")
    return payload


def _safe_regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise MRBodyProfileNotFoundError(f"profile is not installed: {path.name}") from exc
    except OSError as exc:
        raise MRBodyProfileStoreError(f"cannot inspect stored profile: {path.name}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MRBodyStoredProfileError("stored profile path must be a non-symlink regular file")


def _fsync_directory_best_effort(path: Path) -> None:
    """Strengthen post-commit durability where directory fsync is supported.

    `os.replace` is already the commit point. A post-commit directory-fsync
    limitation must never turn a committed installation into an apparent
    failure, particularly on Windows where opening a directory for fsync is not
    a portable operation.
    """

    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


class MRBodyProfileStore:
    """Validate-first `.mrbody` store with one atomic file replacement commit."""

    def __init__(
        self,
        root: Path | str,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self._root = Path(root)
        self._failure_injector = failure_injector
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def _profile_path(self, body_id: str) -> Path:
        identifier = _canonical_body_id(body_id)
        return self._root / f"{identifier}.mrbody"

    def _ensure_root(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            info = self._root.lstat()
        except OSError as exc:
            raise MRBodyProfileStoreError("cannot create or inspect profile-store directory") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise MRBodyProfileStoreError("profile-store root must be a non-symlink directory")

    def _inject(self, stage: str, temp_path: Path) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage, temp_path)

    def install(
        self,
        archive_bytes: bytes,
        *,
        expected_identity_id: str | None = None,
    ) -> MRBodyProfileReceipt:
        """Validate, stage, revalidate and atomically install one package.

        Invalid package bytes are rejected before the store directory or final
        profile path is touched. Any exception before `os.replace` removes the
        temporary sibling and leaves a previously valid final package unchanged.
        """

        inspection = validate_mrbody(
            archive_bytes,
            expected_identity_id=expected_identity_id,
        )
        body_id = _canonical_body_id(inspection.body_id)
        destination = self._profile_path(body_id)
        expected_digest = _digest(archive_bytes)

        with self._lock:
            self._ensure_root()
            descriptor: int | None = None
            temp_path: Path | None = None
            try:
                descriptor, temp_name = tempfile.mkstemp(
                    prefix=f".{body_id}.",
                    suffix=".tmp",
                    dir=str(self._root),
                )
                temp_path = Path(temp_name)
                with os.fdopen(descriptor, "wb") as handle:
                    descriptor = None
                    handle.write(archive_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())

                self._inject("after_stage_fsync", temp_path)

                staged_bytes = _bounded_read(temp_path)
                if len(staged_bytes) != len(archive_bytes) or _digest(staged_bytes) != expected_digest:
                    raise MRBodyProfileStoreError("staged mrbody bytes differ from validated input")
                staged_inspection = validate_mrbody(
                    staged_bytes,
                    expected_identity_id=body_id,
                )
                if staged_inspection.body_id != body_id:
                    raise MRBodyProfileStoreError("staged mrbody identity changed before commit")

                self._inject("after_stage_revalidation", temp_path)

                try:
                    os.replace(temp_path, destination)
                except OSError as exc:
                    raise MRBodyProfileStoreError("atomic mrbody profile replacement failed") from exc
                temp_path = None

                # The replacement above is the only commit point. Do not perform
                # any fallible post-commit validation that could report failure
                # after the previous valid package has already been replaced.
                _fsync_directory_best_effort(self._root)
                return _receipt(staged_bytes, staged_inspection)
            finally:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def install_file(
        self,
        package_path: Path | str,
        *,
        expected_identity_id: str | None = None,
    ) -> MRBodyProfileReceipt:
        """Bounded-read an archive file, then use the exact `install` boundary."""

        path = Path(package_path)
        _safe_regular_file(path)
        return self.install(
            _bounded_read(path),
            expected_identity_id=expected_identity_id,
        )

    def load(self, body_id: str) -> MRBodyStoredProfile:
        """Return one installed package only after fresh M2.5 validation."""

        identifier = _canonical_body_id(body_id)
        path = self._profile_path(identifier)
        with self._lock:
            _safe_regular_file(path)
            archive_bytes = _bounded_read(path)
            inspection = validate_mrbody(
                archive_bytes,
                expected_identity_id=identifier,
            )
            return MRBodyStoredProfile(
                archive_bytes=archive_bytes,
                inspection=inspection,
                receipt=_receipt(archive_bytes, inspection),
            )
