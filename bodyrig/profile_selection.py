"""Digest-bound current `.mrbody` selection and renderer-neutral runtime payload binding.

M2.7 keeps the M2.6 archive store archive-only. Selection state lives in one
fixed sibling JSON file beside the store directory. The marker binds both the
canonical body id and the exact installed archive SHA-256, so replacing a
package under the same body id cannot silently change the selected runtime body.

Runtime binding reads only already-validated, checksummed data into memory. It
never extracts archive members to disk, executes package content, interprets
VRMA semantics, activates a renderer, or claims physical/visual acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from threading import RLock
import tempfile
from typing import Callable
import zipfile

from .mrbody import OPTIONAL_MOTION_PATHS
from .profile_store import (
    MRBodyProfileNotFoundError,
    MRBodyProfileStore,
    MRBodyStoredProfile,
)


CURRENT_PROFILE_FORMAT = "bodyrig.current_profile"
CURRENT_PROFILE_VERSION = 1
MAX_CURRENT_MARKER_BYTES = 4096

_BODYID_RE = re.compile(r"^bodyid-[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MRBodyCurrentProfileError(RuntimeError):
    """Current-profile selection or runtime binding failed closed."""


class MRBodyCurrentProfileNotSelectedError(MRBodyCurrentProfileError):
    """No current profile marker exists."""


class MRBodyCurrentProfileStaleError(MRBodyCurrentProfileError):
    """Selected body id still exists but no longer matches the pinned package digest."""


@dataclass(frozen=True, slots=True)
class MRBodyCurrentMarker:
    """Canonical persisted selection authority."""

    body_id: str
    package_sha256: str


@dataclass(frozen=True, slots=True)
class MRBodyCurrentProfile:
    """One marker resolved against a freshly validated installed archive."""

    marker: MRBodyCurrentMarker
    stored: MRBodyStoredProfile


@dataclass(frozen=True, slots=True)
class MRBodyRuntimeBinding:
    """Immutable, validated data-only payload handoff for a later renderer adapter."""

    body_id: str
    name: str
    package_sha256: str
    avatar_vrm: bytes
    bodyprint_json: bytes
    thumbnail_png: bytes
    motions: tuple[tuple[str, bytes], ...]


FailureInjector = Callable[[str, Path], None]


def _canonical_marker_bytes(marker: MRBodyCurrentMarker) -> bytes:
    value = {
        "body_id": marker.body_id,
        "format": CURRENT_PROFILE_FORMAT,
        "package_sha256": marker.package_sha256,
        "version": CURRENT_PROFILE_VERSION,
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _parse_marker_bytes(data: bytes) -> MRBodyCurrentMarker:
    if not data or len(data) > MAX_CURRENT_MARKER_BYTES:
        raise MRBodyCurrentProfileError("current-profile marker size is invalid")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MRBodyCurrentProfileError("current-profile marker must be UTF-8 JSON") from exc

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise MRBodyCurrentProfileError(
                    f"current-profile marker contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                MRBodyCurrentProfileError(
                    f"current-profile marker contains non-finite JSON constant {token}"
                )
            ),
        )
    except MRBodyCurrentProfileError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise MRBodyCurrentProfileError("current-profile marker is malformed JSON") from exc

    expected = {"format", "version", "body_id", "package_sha256"}
    if not isinstance(value, dict) or set(value) != expected:
        raise MRBodyCurrentProfileError(
            "current-profile marker contains missing or unsupported fields"
        )
    if value.get("format") != CURRENT_PROFILE_FORMAT:
        raise MRBodyCurrentProfileError("current-profile marker format is unsupported")
    if type(value.get("version")) is not int or value["version"] != CURRENT_PROFILE_VERSION:
        raise MRBodyCurrentProfileError("current-profile marker version is unsupported")
    body_id = value.get("body_id")
    digest = value.get("package_sha256")
    if not isinstance(body_id, str) or _BODYID_RE.fullmatch(body_id) is None:
        raise MRBodyCurrentProfileError("current-profile body_id is invalid")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise MRBodyCurrentProfileError("current-profile package_sha256 is invalid")

    marker = MRBodyCurrentMarker(body_id=body_id, package_sha256=digest)
    if data != _canonical_marker_bytes(marker):
        raise MRBodyCurrentProfileError("current-profile marker is not canonical JSON")
    return marker


def _safe_regular_marker(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise MRBodyCurrentProfileNotSelectedError("no current BodyRig profile is selected") from exc
    except OSError as exc:
        raise MRBodyCurrentProfileError("cannot inspect current-profile marker") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MRBodyCurrentProfileError(
            "current-profile marker must be a non-symlink regular file"
        )


def _bounded_marker_read(path: Path) -> bytes:
    _safe_regular_marker(path)
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_CURRENT_MARKER_BYTES + 1)
    except OSError as exc:
        raise MRBodyCurrentProfileError("cannot read current-profile marker") from exc
    if len(data) > MAX_CURRENT_MARKER_BYTES:
        raise MRBodyCurrentProfileError("current-profile marker exceeds safety cap")
    return data


def _fsync_directory_best_effort(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


class MRBodyCurrentProfileStore:
    """Atomic selection state over an M2.6 archive-only profile store."""

    def __init__(
        self,
        store: MRBodyProfileStore,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        if not store.root.name:
            raise MRBodyCurrentProfileError(
                "profile-store root must have a final path component for sibling state"
            )
        self._store = store
        self._failure_injector = failure_injector
        self._lock = RLock()
        self._marker_path = store.root.with_name(
            f".{store.root.name}.current-profile.json"
        )

    @property
    def marker_path(self) -> Path:
        return self._marker_path

    def _inject(self, stage: str, path: Path) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage, path)

    def _validate_state_parent(self) -> None:
        parent = self._marker_path.parent
        try:
            info = parent.lstat()
        except OSError as exc:
            raise MRBodyCurrentProfileError(
                "cannot inspect current-profile state directory"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise MRBodyCurrentProfileError(
                "current-profile state parent must be a non-symlink directory"
            )

    def select(self, body_id: str) -> MRBodyCurrentMarker:
        """Pin current selection to the exact freshly validated installed package."""

        try:
            stored = self._store.load(body_id)
        except Exception as exc:
            raise MRBodyCurrentProfileError(str(exc)) from exc

        marker = MRBodyCurrentMarker(
            body_id=stored.receipt.body_id,
            package_sha256=stored.receipt.package_sha256,
        )
        desired = _canonical_marker_bytes(marker)

        with self._lock:
            self._validate_state_parent()
            if self._marker_path.exists() or self._marker_path.is_symlink():
                _safe_regular_marker(self._marker_path)

            descriptor: int | None = None
            temp_path: Path | None = None
            try:
                descriptor, temp_name = tempfile.mkstemp(
                    prefix=f".{self._marker_path.name}.",
                    suffix=".tmp",
                    dir=str(self._marker_path.parent),
                )
                temp_path = Path(temp_name)
                with os.fdopen(descriptor, "wb") as handle:
                    descriptor = None
                    handle.write(desired)
                    handle.flush()
                    os.fsync(handle.fileno())

                self._inject("after_marker_fsync", temp_path)

                staged = _bounded_marker_read(temp_path)
                staged_marker = _parse_marker_bytes(staged)
                if staged_marker != marker or staged != desired:
                    raise MRBodyCurrentProfileError(
                        "staged current-profile marker changed before commit"
                    )

                self._inject("after_marker_revalidation", temp_path)

                try:
                    os.replace(temp_path, self._marker_path)
                except OSError as exc:
                    raise MRBodyCurrentProfileError(
                        "atomic current-profile marker replacement failed"
                    ) from exc
                temp_path = None
                _fsync_directory_best_effort(self._marker_path.parent)
                return marker
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

    def load_current(self) -> MRBodyCurrentProfile:
        """Resolve current marker only if it still pins the exact installed bytes."""

        with self._lock:
            marker = _parse_marker_bytes(_bounded_marker_read(self._marker_path))
            try:
                stored = self._store.load(marker.body_id)
            except MRBodyProfileNotFoundError as exc:
                raise MRBodyCurrentProfileStaleError(
                    "selected BodyRig profile is no longer installed"
                ) from exc
            except Exception as exc:
                raise MRBodyCurrentProfileError(str(exc)) from exc
            if stored.receipt.body_id != marker.body_id:
                raise MRBodyCurrentProfileError(
                    "selected BodyRig profile resolved to a different body id"
                )
            if stored.receipt.package_sha256 != marker.package_sha256:
                raise MRBodyCurrentProfileStaleError(
                    "selected BodyRig package changed; explicit re-selection is required"
                )
            return MRBodyCurrentProfile(marker=marker, stored=stored)

    def bind_current_runtime(self) -> MRBodyRuntimeBinding:
        """Read validated data-only renderer handoff payloads into immutable memory."""

        current = self.load_current()
        stored = current.stored
        present = {path for path, _ in stored.inspection.payload_sizes}
        try:
            with zipfile.ZipFile(BytesIO(stored.archive_bytes), "r") as archive:
                avatar = archive.read("avatar.vrm")
                bodyprint = archive.read("bodyprint.json")
                thumbnail = archive.read("thumbnail.png")
                motions = tuple(
                    (path, archive.read(path))
                    for path in OPTIONAL_MOTION_PATHS
                    if path in present
                )
        except (KeyError, OSError, zipfile.BadZipFile) as exc:
            # M2.6/M2.5 validation already succeeded. Any disagreement during
            # in-memory handoff is nevertheless a hard runtime-binding failure.
            raise MRBodyCurrentProfileError(
                "validated mrbody payloads could not be bound in memory"
            ) from exc

        return MRBodyRuntimeBinding(
            body_id=current.marker.body_id,
            name=stored.inspection.name,
            package_sha256=current.marker.package_sha256,
            avatar_vrm=avatar,
            bodyprint_json=bodyprint,
            thumbnail_png=thumbnail,
            motions=motions,
        )
