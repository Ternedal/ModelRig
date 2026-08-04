"""Canonical contracts for a complete, pinned local Git runtime package."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

TRUSTED_GIT_RUNTIME_MANIFEST_SCHEMA = (
    "kaliv-development-trusted-git-runtime-manifest/v1"
)
TRUSTED_GIT_RUNTIME_STAGING_RECEIPT_SCHEMA = (
    "kaliv-development-trusted-git-runtime-staging-receipt/v1"
)
TRUSTED_GIT_RUNTIME_EVIDENCE_SCHEMA = (
    "kaliv-development-trusted-git-runtime-evidence/v1"
)

_RUNTIME_DOMAIN = b"kaliv-trusted-git-runtime/v1\0"
_TRANSACTION_DOMAIN = b"kaliv-trusted-git-runtime-transaction/v1\0"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILES = 50_000
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_RUNTIME_BYTES = 4 * 1024 * 1024 * 1024
# Invocation budgets remain caller/task-selected. This is only the hard schema
# ceiling and matches the live streaming primitive; output is never accumulated
# beyond bounded prefixes, and the complete process tree is killed on overflow.
_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
_ROLES = {"executable", "helper", "library", "data"}


class TrustedGitRuntimeError(ValueError):
    """The Git runtime package or one invocation failed closed."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict(value: Any, *, name: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise TrustedGitRuntimeError(f"{name} fields mismatch")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise TrustedGitRuntimeError(f"{name} is invalid")
    return value


def _integer(value: Any, *, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise TrustedGitRuntimeError(f"{name} is invalid")
    return value


def _boolean(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise TrustedGitRuntimeError(f"{name} is invalid")
    return value


def _relative(value: Any, *, name: str, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise TrustedGitRuntimeError(f"{name} is invalid")
    if value == ".":
        if allow_dot:
            return value
        raise TrustedGitRuntimeError(f"{name} is invalid")
    parsed = PurePosixPath(value)
    if (
        value.startswith("/")
        or str(parsed) != value
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise TrustedGitRuntimeError(f"{name} is invalid")
    return value


def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        is_junction = getattr(current, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _existing_link_free_directory(path: Path, *, name: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_dir():
        raise TrustedGitRuntimeError(f"{name} must be an existing absolute directory")
    if _has_linkish_component(candidate):
        raise TrustedGitRuntimeError(f"{name} must be link-free")
    resolved = candidate.resolve()
    if resolved != candidate:
        raise TrustedGitRuntimeError(f"{name} must already be canonical")
    return resolved


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeFile:
    relative_path: str
    sha256: str
    size_bytes: int
    role: str
    executable: bool

    def __post_init__(self) -> None:
        _relative(self.relative_path, name="runtime file path")
        _hex64(self.sha256, name="runtime file hash")
        _integer(
            self.size_bytes,
            name="runtime file bytes",
            low=0,
            high=_MAX_FILE_BYTES,
        )
        if self.role not in _ROLES:
            raise TrustedGitRuntimeError("runtime file role is invalid")
        _boolean(self.executable, name="runtime executable flag")
        if self.role in {"executable", "helper"} and not self.executable:
            raise TrustedGitRuntimeError(
                "runtime executable/helper file must be marked executable"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeFile":
        data = _strict(
            value,
            name="trusted Git runtime file",
            fields={"relative_path", "sha256", "size_bytes", "role", "executable"},
        )
        return cls(
            relative_path=data["relative_path"],
            sha256=data["sha256"],
            size_bytes=data["size_bytes"],
            role=data["role"],
            executable=data["executable"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "role": self.role,
            "executable": self.executable,
        }


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeManifest:
    executable_relative_path: str
    exec_path_relative_path: str
    path_relative_directories: tuple[str, ...]
    files: tuple[TrustedGitRuntimeFile, ...]
    total_bytes: int
    schema: str = TRUSTED_GIT_RUNTIME_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TRUSTED_GIT_RUNTIME_MANIFEST_SCHEMA:
            raise TrustedGitRuntimeError("unsupported trusted Git runtime schema")
        executable = _relative(
            self.executable_relative_path,
            name="Git executable path",
        )
        exec_path = _relative(
            self.exec_path_relative_path,
            name="Git exec path",
            allow_dot=True,
        )
        if not isinstance(self.path_relative_directories, tuple):
            raise TrustedGitRuntimeError("runtime PATH directories must be immutable")
        path_directories = tuple(
            _relative(item, name="runtime PATH directory", allow_dot=True)
            for item in self.path_relative_directories
        )
        if not path_directories or len(set(path_directories)) != len(path_directories):
            raise TrustedGitRuntimeError("runtime PATH directories are invalid")
        if not isinstance(self.files, tuple) or not self.files:
            raise TrustedGitRuntimeError("runtime file set is invalid")
        _integer(len(self.files), name="runtime file count", low=1, high=_MAX_FILES)
        paths = [item.relative_path for item in self.files]
        if paths != sorted(paths) or len(set(paths)) != len(paths):
            raise TrustedGitRuntimeError("runtime files must be unique and sorted")
        if executable not in paths:
            raise TrustedGitRuntimeError("runtime executable is not in the manifest")
        roles = {item.relative_path: item.role for item in self.files}
        if roles[executable] != "executable":
            raise TrustedGitRuntimeError("runtime executable role is invalid")
        for directory in (exec_path, *path_directories):
            if directory != "." and not any(
                item == directory or item.startswith(f"{directory}/") for item in paths
            ):
                raise TrustedGitRuntimeError(
                    "runtime directory contains no manifest file"
                )
        computed_total = sum(item.size_bytes for item in self.files)
        _integer(
            self.total_bytes,
            name="runtime total bytes",
            low=0,
            high=_MAX_RUNTIME_BYTES,
        )
        if self.total_bytes != computed_total:
            raise TrustedGitRuntimeError("runtime total byte count is inconsistent")

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeManifest":
        data = _strict(
            value,
            name="trusted Git runtime manifest",
            fields={
                "schema",
                "executable_relative_path",
                "exec_path_relative_path",
                "path_relative_directories",
                "files",
                "total_bytes",
            },
        )
        if not isinstance(data["path_relative_directories"], list):
            raise TrustedGitRuntimeError("runtime PATH directories are invalid")
        if not isinstance(data["files"], list):
            raise TrustedGitRuntimeError("runtime files are invalid")
        return cls(
            schema=data["schema"],
            executable_relative_path=data["executable_relative_path"],
            exec_path_relative_path=data["exec_path_relative_path"],
            path_relative_directories=tuple(data["path_relative_directories"]),
            files=tuple(
                TrustedGitRuntimeFile.from_mapping(item) for item in data["files"]
            ),
            total_bytes=data["total_bytes"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "executable_relative_path": self.executable_relative_path,
            "exec_path_relative_path": self.exec_path_relative_path,
            "path_relative_directories": list(self.path_relative_directories),
            "files": [item.to_dict() for item in self.files],
            "total_bytes": self.total_bytes,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(
            _RUNTIME_DOMAIN + self.canonical_json().encode("utf-8")
        )


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeStagingReceipt:
    manifest: TrustedGitRuntimeManifest
    transaction_id: str
    runtime_relative_path: str
    manifest_relative_path: str
    schema: str = TRUSTED_GIT_RUNTIME_STAGING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TRUSTED_GIT_RUNTIME_STAGING_RECEIPT_SCHEMA:
            raise TrustedGitRuntimeError("unsupported trusted Git staging schema")
        if not isinstance(self.manifest, TrustedGitRuntimeManifest):
            raise TrustedGitRuntimeError("trusted Git staging manifest is invalid")
        if (
            not isinstance(self.transaction_id, str)
            or not re.fullmatch(r"git-runtime-[0-9a-f]{32}", self.transaction_id)
        ):
            raise TrustedGitRuntimeError("trusted Git transaction id is invalid")
        _relative(self.runtime_relative_path, name="runtime relative path")
        _relative(self.manifest_relative_path, name="manifest relative path")

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeStagingReceipt":
        data = _strict(
            value,
            name="trusted Git staging receipt",
            fields={
                "schema",
                "manifest",
                "transaction_id",
                "runtime_relative_path",
                "manifest_relative_path",
            },
        )
        return cls(
            schema=data["schema"],
            manifest=TrustedGitRuntimeManifest.from_mapping(data["manifest"]),
            transaction_id=data["transaction_id"],
            runtime_relative_path=data["runtime_relative_path"],
            manifest_relative_path=data["manifest_relative_path"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest": self.manifest.to_dict(),
            "transaction_id": self.transaction_id,
            "runtime_relative_path": self.runtime_relative_path,
            "manifest_relative_path": self.manifest_relative_path,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(
            _TRANSACTION_DOMAIN + self.canonical_json().encode("utf-8")
        )


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeEvidence:
    runtime_manifest_sha256: str
    runtime_file_count: int
    runtime_bytes: int
    executable_sha256: str
    version: str
    exec_path_relative_path: str
    path_relative_directories: tuple[str, ...]
    library_relative_directories: tuple[str, ...]
    schema: str = TRUSTED_GIT_RUNTIME_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TRUSTED_GIT_RUNTIME_EVIDENCE_SCHEMA:
            raise TrustedGitRuntimeError("unsupported trusted Git evidence schema")
        _hex64(self.runtime_manifest_sha256, name="runtime manifest hash")
        _integer(
            self.runtime_file_count,
            name="runtime evidence file count",
            low=1,
            high=_MAX_FILES,
        )
        _integer(
            self.runtime_bytes,
            name="runtime evidence bytes",
            low=0,
            high=_MAX_RUNTIME_BYTES,
        )
        _hex64(self.executable_sha256, name="runtime executable hash")
        if (
            not isinstance(self.version, str)
            or not self.version
            or "\n" in self.version
            or "\r" in self.version
            or "\x00" in self.version
            or len(self.version.encode("utf-8")) > 512
        ):
            raise TrustedGitRuntimeError("runtime Git version is invalid")
        _relative(
            self.exec_path_relative_path,
            name="runtime evidence exec path",
            allow_dot=True,
        )
        for values, name in (
            (self.path_relative_directories, "runtime evidence PATH directories"),
            (self.library_relative_directories, "runtime evidence library directories"),
        ):
            if not isinstance(values, tuple):
                raise TrustedGitRuntimeError(f"{name} must be immutable")
            normalized = tuple(
                _relative(item, name=name, allow_dot=True) for item in values
            )
            if len(set(normalized)) != len(normalized):
                raise TrustedGitRuntimeError(f"{name} contain duplicates")

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeEvidence":
        data = _strict(
            value,
            name="trusted Git runtime evidence",
            fields={
                "schema",
                "runtime_manifest_sha256",
                "runtime_file_count",
                "runtime_bytes",
                "executable_sha256",
                "version",
                "exec_path_relative_path",
                "path_relative_directories",
                "library_relative_directories",
            },
        )
        if not isinstance(data["path_relative_directories"], list) or not isinstance(
            data["library_relative_directories"], list
        ):
            raise TrustedGitRuntimeError("runtime evidence directories are invalid")
        return cls(
            schema=data["schema"],
            runtime_manifest_sha256=data["runtime_manifest_sha256"],
            runtime_file_count=data["runtime_file_count"],
            runtime_bytes=data["runtime_bytes"],
            executable_sha256=data["executable_sha256"],
            version=data["version"],
            exec_path_relative_path=data["exec_path_relative_path"],
            path_relative_directories=tuple(data["path_relative_directories"]),
            library_relative_directories=tuple(data["library_relative_directories"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "runtime_file_count": self.runtime_file_count,
            "runtime_bytes": self.runtime_bytes,
            "executable_sha256": self.executable_sha256,
            "version": self.version,
            "exec_path_relative_path": self.exec_path_relative_path,
            "path_relative_directories": list(self.path_relative_directories),
            "library_relative_directories": list(self.library_relative_directories),
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))
