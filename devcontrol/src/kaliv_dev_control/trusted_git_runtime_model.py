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
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
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
    raw = Path(path)
    if not raw.is_absolute():
        raise TrustedGitRuntimeError(f"{name} must be absolute")
    resolved = Path(os.path.realpath(os.path.abspath(raw)))
    if not resolved.is_dir() or _has_linkish_component(resolved):
        raise TrustedGitRuntimeError(
            f"{name} must be an existing link-free directory"
        )
    return resolved


def _regular_unaliased_file(path: Path, *, name: str) -> os.stat_result:
    if not path.is_file() or _has_linkish_component(path):
        raise TrustedGitRuntimeError(f"{name} must be a regular link-free file")
    stat = path.stat()
    if stat.st_nlink != 1:
        raise TrustedGitRuntimeError(f"{name} must not be hard-linked")
    if stat.st_size <= 0 or stat.st_size > _MAX_FILE_BYTES:
        raise TrustedGitRuntimeError(f"{name} size is invalid")
    return stat


def _path_hash(path: Path) -> str:
    normalized = os.path.normcase(os.fspath(path)).encode("utf-8", "surrogatepass")
    return _sha256_bytes(b"kaliv-runtime-path/v1\0" + normalized)


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeFile:
    relative_path: str
    sha256: str
    size_bytes: int
    executable: bool
    role: str

    def __post_init__(self) -> None:
        _relative(self.relative_path, name="Git runtime file path")
        _hex64(self.sha256, name="Git runtime file hash")
        _integer(
            self.size_bytes,
            name="Git runtime file bytes",
            low=1,
            high=_MAX_FILE_BYTES,
        )
        _boolean(self.executable, name="Git runtime executable flag")
        if self.role not in _ROLES:
            raise TrustedGitRuntimeError("Git runtime file role is invalid")
        if self.role == "executable" and self.executable is not True:
            raise TrustedGitRuntimeError("Git runtime executable must be executable")

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeFile":
        data = _strict(
            value,
            name="Git runtime file",
            fields={"relative_path", "sha256", "size_bytes", "executable", "role"},
        )
        return cls(
            relative_path=data["relative_path"],
            sha256=data["sha256"],
            size_bytes=data["size_bytes"],
            executable=data["executable"],
            role=data["role"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "executable": self.executable,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeManifest:
    executable_relative_path: str
    exec_path_relative_path: str
    path_relative_directories: tuple[str, ...]
    files: tuple[TrustedGitRuntimeFile, ...]
    schema: str = TRUSTED_GIT_RUNTIME_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TRUSTED_GIT_RUNTIME_MANIFEST_SCHEMA:
            raise TrustedGitRuntimeError("unsupported Git runtime manifest schema")
        executable = _relative(
            self.executable_relative_path,
            name="Git runtime executable path",
        )
        exec_path = _relative(
            self.exec_path_relative_path,
            name="Git runtime exec path",
            allow_dot=True,
        )
        if (
            not isinstance(self.path_relative_directories, tuple)
            or not self.path_relative_directories
        ):
            raise TrustedGitRuntimeError("Git runtime PATH directories are invalid")
        path_directories = tuple(
            _relative(item, name="Git runtime PATH directory", allow_dot=True)
            for item in self.path_relative_directories
        )
        if len(set(path_directories)) != len(path_directories):
            raise TrustedGitRuntimeError("Git runtime PATH directories are duplicated")
        if (
            not isinstance(self.files, tuple)
            or not self.files
            or len(self.files) > _MAX_FILES
            or any(not isinstance(item, TrustedGitRuntimeFile) for item in self.files)
        ):
            raise TrustedGitRuntimeError("Git runtime file manifest is invalid")
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise TrustedGitRuntimeError(
                "Git runtime files must be unique and sorted"
            )
        by_path = {item.relative_path: item for item in self.files}
        entry = by_path.get(executable)
        if entry is None or entry.role != "executable" or not entry.executable:
            raise TrustedGitRuntimeError(
                "Git runtime executable is not exactly represented"
            )
        if sum(item.role == "executable" for item in self.files) != 1:
            raise TrustedGitRuntimeError("Git runtime must contain one executable")
        total = sum(item.size_bytes for item in self.files)
        if total > _MAX_RUNTIME_BYTES:
            raise TrustedGitRuntimeError("Git runtime exceeds its byte budget")
        prefixes = {exec_path, *path_directories}
        for prefix in prefixes:
            if prefix == ".":
                continue
            prefix_with_slash = prefix + "/"
            if not any(path.startswith(prefix_with_slash) for path in paths):
                raise TrustedGitRuntimeError(
                    "Git runtime directory does not contain a manifested file"
                )

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeManifest":
        data = _strict(
            value,
            name="Git runtime manifest",
            fields={
                "schema",
                "executable_relative_path",
                "exec_path_relative_path",
                "path_relative_directories",
                "files",
            },
        )
        path_directories = data["path_relative_directories"]
        files = data["files"]
        if not isinstance(path_directories, list) or not isinstance(files, list):
            raise TrustedGitRuntimeError("Git runtime manifest collections are invalid")
        return cls(
            schema=data["schema"],
            executable_relative_path=data["executable_relative_path"],
            exec_path_relative_path=data["exec_path_relative_path"],
            path_relative_directories=tuple(path_directories),
            files=tuple(TrustedGitRuntimeFile.from_mapping(item) for item in files),
        )

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "executable_relative_path": self.executable_relative_path,
            "exec_path_relative_path": self.exec_path_relative_path,
            "path_relative_directories": list(self.path_relative_directories),
            "files": [item.to_dict() for item in self.files],
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(
            _RUNTIME_DOMAIN + self.canonical_json().encode("utf-8")
        )


def capture_trusted_git_runtime_manifest(
    source_root: Path,
    *,
    executable_relative_path: str,
    exec_path_relative_path: str,
    path_relative_directories: tuple[str, ...],
) -> TrustedGitRuntimeManifest:
    """Hash every regular file below one reviewed Git runtime package root.

    Capture creates a reviewable manifest; it does not make the source trusted.
    Trust begins only when an operator pins and supplies the exact manifest to
    the create-once stager.
    """

    root = _existing_link_free_directory(source_root, name="Git runtime source root")
    executable = _relative(
        executable_relative_path,
        name="Git runtime executable path",
    )
    exec_path = _relative(
        exec_path_relative_path,
        name="Git runtime exec path",
        allow_dot=True,
    )
    path_dirs = tuple(
        _relative(item, name="Git runtime PATH directory", allow_dot=True)
        for item in path_relative_directories
    )
    entries: list[TrustedGitRuntimeFile] = []
    for candidate in sorted(root.rglob("*")):
        if candidate.is_dir():
            if _has_linkish_component(candidate):
                raise TrustedGitRuntimeError(
                    "Git runtime source contains a linked directory"
                )
            continue
        stat = _regular_unaliased_file(candidate, name="Git runtime source file")
        relative = candidate.relative_to(root).as_posix()
        payload = candidate.read_bytes()
        role = "data"
        if relative == executable:
            role = "executable"
        elif exec_path == "." or relative.startswith(exec_path + "/"):
            role = "helper"
        elif candidate.suffix.lower() in {".dll", ".so", ".dylib"}:
            role = "library"
        executable_flag = relative == executable or bool(stat.st_mode & 0o111)
        entries.append(
            TrustedGitRuntimeFile(
                relative_path=relative,
                sha256=_sha256_bytes(payload),
                size_bytes=len(payload),
                executable=executable_flag,
                role=role,
            )
        )
    return TrustedGitRuntimeManifest(
        executable_relative_path=executable,
        exec_path_relative_path=exec_path,
        path_relative_directories=path_dirs,
        files=tuple(entries),
    )


@dataclass(frozen=True, slots=True)
class TrustedGitRuntimeStagingReceipt:
    manifest: TrustedGitRuntimeManifest
    transaction_id: str
    source_root_path_sha256: str
    runtime_relative_path: str
    complete: bool
    schema: str = TRUSTED_GIT_RUNTIME_STAGING_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TRUSTED_GIT_RUNTIME_STAGING_RECEIPT_SCHEMA:
            raise TrustedGitRuntimeError("unsupported Git runtime receipt schema")
        if not isinstance(self.manifest, TrustedGitRuntimeManifest):
            raise TrustedGitRuntimeError("Git runtime receipt manifest is invalid")
        expected_id = _transaction_id(self.manifest.sha256)
        if self.transaction_id != expected_id:
            raise TrustedGitRuntimeError("Git runtime transaction id is invalid")
        _hex64(
            self.source_root_path_sha256,
            name="Git runtime source path hash",
        )
        if self.runtime_relative_path != "runtime":
            raise TrustedGitRuntimeError("Git runtime receipt path is invalid")
        if self.complete is not True:
            raise TrustedGitRuntimeError("Git runtime receipt is incomplete")

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeStagingReceipt":
        data = _strict(
            value,
            name="Git runtime staging receipt",
            fields={
                "schema",
                "manifest",
                "transaction_id",
                "source_root_path_sha256",
                "runtime_relative_path",
                "complete",
            },
        )
        return cls(
            schema=data["schema"],
            manifest=TrustedGitRuntimeManifest.from_mapping(data["manifest"]),
            transaction_id=data["transaction_id"],
            source_root_path_sha256=data["source_root_path_sha256"],
            runtime_relative_path=data["runtime_relative_path"],
            complete=data["complete"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest": self.manifest.to_dict(),
            "transaction_id": self.transaction_id,
            "source_root_path_sha256": self.source_root_path_sha256,
            "runtime_relative_path": self.runtime_relative_path,
            "complete": self.complete,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


def _transaction_id(manifest_sha256: str) -> str:
    digest = _sha256_bytes(
        _TRANSACTION_DOMAIN
        + _hex64(manifest_sha256, name="Git runtime manifest hash").encode("ascii")
    )
    return f"git-runtime-{digest[:32]}"


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
            raise TrustedGitRuntimeError("unsupported Git runtime evidence schema")
        _hex64(self.runtime_manifest_sha256, name="Git runtime manifest hash")
        _hex64(self.executable_sha256, name="Git executable hash")
        _integer(
            self.runtime_file_count,
            name="Git runtime file count",
            low=1,
            high=_MAX_FILES,
        )
        _integer(
            self.runtime_bytes,
            name="Git runtime bytes",
            low=1,
            high=_MAX_RUNTIME_BYTES,
        )
        if not isinstance(self.version, str) or not self.version or "\n" in self.version:
            raise TrustedGitRuntimeError("Git runtime version is invalid")
        _relative(
            self.exec_path_relative_path,
            name="Git runtime evidence exec path",
            allow_dot=True,
        )
        if not isinstance(self.path_relative_directories, tuple):
            raise TrustedGitRuntimeError("Git runtime evidence PATH is invalid")
        if not isinstance(self.library_relative_directories, tuple):
            raise TrustedGitRuntimeError("Git runtime evidence library path is invalid")
        for relative in self.library_relative_directories:
            _relative(
                relative,
                name="Git runtime evidence library directory",
                allow_dot=True,
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
            "library_relative_directories": list(
                self.library_relative_directories
            ),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "TrustedGitRuntimeEvidence":
        data = _strict(
            value,
            name="Git runtime evidence",
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
        paths = data["path_relative_directories"]
        libraries = data["library_relative_directories"]
        if not isinstance(paths, list) or not isinstance(libraries, list):
            raise TrustedGitRuntimeError("Git runtime evidence paths are invalid")
        return cls(
            schema=data["schema"],
            runtime_manifest_sha256=data["runtime_manifest_sha256"],
            runtime_file_count=data["runtime_file_count"],
            runtime_bytes=data["runtime_bytes"],
            executable_sha256=data["executable_sha256"],
            version=data["version"],
            exec_path_relative_path=data["exec_path_relative_path"],
            path_relative_directories=tuple(paths),
            library_relative_directories=tuple(libraries),
        )

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))
