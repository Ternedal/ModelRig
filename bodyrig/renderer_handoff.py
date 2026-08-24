"""Digest-bound bridge from M2.7 current profiles to file-path renderers.

The BodyRig core keeps `.mrbody` archives whole and renderer-neutral. Some
renderers, including the Unity/UniVRM proof, require a filesystem path to one
VRM file. This module stages only the already-validated `avatar.vrm` bytes from
the current M2.7 runtime binding into a content-addressed sibling directory.

No arbitrary archive entry is extracted. No renderer is activated. No Unity,
VRM expression, humanoid bone or Animator vocabulary crosses back into core.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import RLock
import tempfile
from typing import Callable

from .mrbody import ENTRY_LIMITS, validate_vrm1_bytes
from .profile_selection import MRBodyCurrentProfileStore
from .profile_store import MRBodyProfileStore


RENDERER_PROFILE_FORMAT = "bodyrig.renderer_profile"
RENDERER_PROFILE_VERSION = "0.1"

_BODYID_RE = re.compile(r"^bodyid-[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RendererHandoffError(RuntimeError):
    """Renderer asset staging failed closed before a new visible asset commit."""


@dataclass(frozen=True, slots=True)
class RendererProfileDescriptor:
    """Portable metadata binding one staged avatar to exact validated package bytes."""

    body_id: str
    package_sha256: str
    avatar_sha256: str
    avatar_filename: str

    def to_mapping(self) -> dict[str, object]:
        if _BODYID_RE.fullmatch(self.body_id) is None:
            raise RendererHandoffError("renderer descriptor body_id is invalid")
        if _SHA256_RE.fullmatch(self.package_sha256) is None:
            raise RendererHandoffError("renderer descriptor package digest is invalid")
        if _SHA256_RE.fullmatch(self.avatar_sha256) is None:
            raise RendererHandoffError("renderer descriptor avatar digest is invalid")
        expected_name = (
            f"{self.body_id}.{self.package_sha256}.avatar.vrm"
        )
        if self.avatar_filename != expected_name:
            raise RendererHandoffError(
                "renderer descriptor avatar filename is not content-addressed"
            )
        return {
            "avatar_filename": self.avatar_filename,
            "avatar_sha256": self.avatar_sha256,
            "body_id": self.body_id,
            "format": RENDERER_PROFILE_FORMAT,
            "package_sha256": self.package_sha256,
            "version": RENDERER_PROFILE_VERSION,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_mapping(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


@dataclass(frozen=True, slots=True)
class RendererProfileHandoff:
    """One validated descriptor plus the local path required by a renderer."""

    descriptor: RendererProfileDescriptor
    vrm_path: Path


FailureInjector = Callable[[str, Path], None]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_regular(path: Path, *, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise RendererHandoffError(f"{label} is missing") from exc
    except OSError as exc:
        raise RendererHandoffError(f"cannot inspect {label}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RendererHandoffError(f"{label} must be a non-symlink regular file")


def _bounded_vrm_read(path: Path) -> bytes:
    _safe_regular(path, label="renderer avatar")
    try:
        with path.open("rb") as handle:
            data = handle.read(ENTRY_LIMITS["avatar.vrm"] + 1)
    except OSError as exc:
        raise RendererHandoffError("cannot read renderer avatar") from exc
    if len(data) > ENTRY_LIMITS["avatar.vrm"]:
        raise RendererHandoffError("renderer avatar exceeds mrbody V1 safety cap")
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


class MRBodyRendererHandoff:
    """Prepare the freshly validated current M2.7 avatar for a path-based renderer."""

    def __init__(
        self,
        store: MRBodyProfileStore,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        if not store.root.name:
            raise RendererHandoffError(
                "profile-store root must have a final path component"
            )
        self._store = store
        self._current = MRBodyCurrentProfileStore(store)
        self._failure_injector = failure_injector
        self._lock = RLock()
        self._staging_root = store.root.with_name(
            f".{store.root.name}.renderer-assets"
        )

    @property
    def staging_root(self) -> Path:
        return self._staging_root

    def _inject(self, stage: str, path: Path) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage, path)

    def _ensure_staging_root(self) -> None:
        parent = self._staging_root.parent
        try:
            parent_info = parent.lstat()
        except OSError as exc:
            raise RendererHandoffError(
                "cannot inspect renderer staging parent directory"
            ) from exc
        if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
            raise RendererHandoffError(
                "renderer staging parent must be a non-symlink directory"
            )
        try:
            self._staging_root.mkdir(mode=0o700, exist_ok=True)
            info = self._staging_root.lstat()
        except OSError as exc:
            raise RendererHandoffError(
                "cannot create or inspect renderer staging directory"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise RendererHandoffError(
                "renderer staging root must be a non-symlink directory"
            )

    def prepare_current(self) -> RendererProfileHandoff:
        """Stage exactly the selected avatar bytes after fresh M2.7 validation.

        The call to `bind_current_runtime()` happens before renderer staging is
        created or mutated. A stale/tampered current selection therefore fails
        before this layer writes anything. The final filename is derived only
        from canonical body id plus the selected package digest.
        """

        try:
            binding = self._current.bind_current_runtime()
        except Exception as exc:
            raise RendererHandoffError(str(exc)) from exc

        avatar_digest = _digest(binding.avatar_vrm)
        filename = (
            f"{binding.body_id}.{binding.package_sha256}.avatar.vrm"
        )
        descriptor = RendererProfileDescriptor(
            body_id=binding.body_id,
            package_sha256=binding.package_sha256,
            avatar_sha256=avatar_digest,
            avatar_filename=filename,
        )
        # Validate descriptor before filesystem mutation.
        descriptor.to_mapping()
        destination = self._staging_root / filename

        with self._lock:
            self._ensure_staging_root()

            if destination.exists() or destination.is_symlink():
                existing = _bounded_vrm_read(destination)
                if existing != binding.avatar_vrm or _digest(existing) != avatar_digest:
                    raise RendererHandoffError(
                        "content-addressed renderer avatar already exists with different bytes"
                    )
                try:
                    validate_vrm1_bytes(existing)
                except Exception as exc:
                    raise RendererHandoffError(
                        "existing renderer avatar failed structural VRM validation"
                    ) from exc
                return RendererProfileHandoff(
                    descriptor=descriptor,
                    vrm_path=destination,
                )

            descriptor_fd: int | None = None
            temp_path: Path | None = None
            try:
                descriptor_fd, temp_name = tempfile.mkstemp(
                    prefix=f".{filename}.",
                    suffix=".tmp",
                    dir=str(self._staging_root),
                )
                temp_path = Path(temp_name)
                with os.fdopen(descriptor_fd, "wb") as handle:
                    descriptor_fd = None
                    handle.write(binding.avatar_vrm)
                    handle.flush()
                    os.fsync(handle.fileno())

                self._inject("after_avatar_fsync", temp_path)

                staged = _bounded_vrm_read(temp_path)
                if staged != binding.avatar_vrm or _digest(staged) != avatar_digest:
                    raise RendererHandoffError(
                        "staged renderer avatar differs from validated current profile"
                    )
                try:
                    validate_vrm1_bytes(staged)
                except Exception as exc:
                    raise RendererHandoffError(
                        "staged renderer avatar failed structural VRM validation"
                    ) from exc

                self._inject("after_avatar_revalidation", temp_path)

                try:
                    os.replace(temp_path, destination)
                except OSError as exc:
                    raise RendererHandoffError(
                        "atomic renderer avatar replacement failed"
                    ) from exc
                temp_path = None

                # `os.replace` is the only visible commit point. Do not add a
                # fallible post-commit check that could report failure after the
                # avatar has become visible to a renderer.
                _fsync_directory_best_effort(self._staging_root)
                return RendererProfileHandoff(
                    descriptor=descriptor,
                    vrm_path=destination,
                )
            finally:
                if descriptor_fd is not None:
                    try:
                        os.close(descriptor_fd)
                    except OSError:
                        pass
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
