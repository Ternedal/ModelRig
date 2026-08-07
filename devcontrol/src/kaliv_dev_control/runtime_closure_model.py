"""Canonical signed runtime-closure data model."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

from ._runtime_closure_common import (
    RUNTIME_CLOSURE_SCHEMA,
    RUNTIME_CLOSURE_SIGNATURE_ALGORITHM,
    RuntimeClosureError,
    SIGNED_RUNTIME_CLOSURE_SCHEMA,
    _AUTHORITY_ID,
    _HEX40,
    _HEX64,
    _IDENTIFIER,
    _MAX_CLOSURE_BYTES,
    _MAX_CLOSURE_FILES,
    _MAX_FILE_BYTES,
    _TASK_ID,
    _closure_canonical,
    _closure_relative_path,
    _closure_sha256,
    _closure_working_directory,
)


@dataclass(frozen=True, slots=True)
class RuntimeClosureFile:
    relative_path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            _closure_relative_path(self.relative_path, name="runtime closure file path"),
        )
        if not isinstance(self.sha256, str) or _HEX64.fullmatch(self.sha256) is None:
            raise RuntimeClosureError("runtime closure file hash is invalid")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or not 1 <= self.size_bytes <= _MAX_FILE_BYTES
        ):
            raise RuntimeClosureError("runtime closure file size is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "RuntimeClosureFile":
        if not isinstance(value, Mapping) or set(value) != {
            "relative_path",
            "sha256",
            "size_bytes",
        }:
            raise RuntimeClosureError("runtime closure file fields mismatch")
        return cls(
            relative_path=value["relative_path"],
            sha256=value["sha256"],
            size_bytes=value["size_bytes"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class RuntimeClosureManifest:
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    command_id: str
    tool_id: str
    catalog_sha256: str
    toolchain_sha256: str
    lease_sha256: str
    workspace_root_sha256: str
    trusted_runtime_root_sha256: str
    entrypoint_relative_path: str
    working_directory: str
    files: tuple[RuntimeClosureFile, ...]
    total_bytes: int
    schema: str = RUNTIME_CLOSURE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RUNTIME_CLOSURE_SCHEMA:
            raise RuntimeClosureError("unsupported runtime closure schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise RuntimeClosureError("runtime closure task id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise RuntimeClosureError("runtime closure repository is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
            ("lease_sha256", self.lease_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
            (
                "trusted_runtime_root_sha256",
                self.trusted_runtime_root_sha256,
                _HEX64,
            ),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise RuntimeClosureError(f"runtime closure {name} is invalid")
        for name, value in (
            ("command_id", self.command_id),
            ("tool_id", self.tool_id),
        ):
            if not isinstance(value, str) or _AUTHORITY_ID.fullmatch(value) is None:
                raise RuntimeClosureError(f"runtime closure {name} is invalid")
        object.__setattr__(
            self,
            "entrypoint_relative_path",
            _closure_relative_path(self.entrypoint_relative_path, name="entrypoint"),
        )
        object.__setattr__(
            self,
            "working_directory",
            _closure_working_directory(self.working_directory),
        )
        if (
            not isinstance(self.files, tuple)
            or not self.files
            or len(self.files) > _MAX_CLOSURE_FILES
            or any(not isinstance(item, RuntimeClosureFile) for item in self.files)
        ):
            raise RuntimeClosureError("runtime closure file set is invalid")
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise RuntimeClosureError(
                "runtime closure files must be unique and sorted"
            )
        if len({path.casefold() for path in paths}) != len(paths):
            raise RuntimeClosureError(
                "runtime closure files collide on a case-insensitive filesystem"
            )
        path_set = set(paths)
        for path in paths:
            parts = PurePosixPath(path).parts
            if any(
                PurePosixPath(*parts[:index]).as_posix() in path_set
                for index in range(1, len(parts))
            ):
                raise RuntimeClosureError(
                    "runtime closure file conflicts with a parent file"
                )
        if self.entrypoint_relative_path not in paths:
            raise RuntimeClosureError("runtime closure entrypoint is not manifested")
        expected_total = sum(item.size_bytes for item in self.files)
        if (
            isinstance(self.total_bytes, bool)
            or not isinstance(self.total_bytes, int)
            or self.total_bytes != expected_total
            or not 1 <= self.total_bytes <= _MAX_CLOSURE_BYTES
        ):
            raise RuntimeClosureError("runtime closure total size is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "RuntimeClosureManifest":
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "repository",
            "base_sha",
            "command_id",
            "tool_id",
            "catalog_sha256",
            "toolchain_sha256",
            "lease_sha256",
            "workspace_root_sha256",
            "trusted_runtime_root_sha256",
            "entrypoint_relative_path",
            "working_directory",
            "files",
            "total_bytes",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise RuntimeClosureError("runtime closure manifest fields mismatch")
        files = value["files"]
        if not isinstance(files, list):
            raise RuntimeClosureError("runtime closure files must be an array")
        return cls(
            schema=value["schema"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            repository=value["repository"],
            base_sha=value["base_sha"],
            command_id=value["command_id"],
            tool_id=value["tool_id"],
            catalog_sha256=value["catalog_sha256"],
            toolchain_sha256=value["toolchain_sha256"],
            lease_sha256=value["lease_sha256"],
            workspace_root_sha256=value["workspace_root_sha256"],
            trusted_runtime_root_sha256=value["trusted_runtime_root_sha256"],
            entrypoint_relative_path=value["entrypoint_relative_path"],
            working_directory=value["working_directory"],
            files=tuple(RuntimeClosureFile.from_mapping(item) for item in files),
            total_bytes=value["total_bytes"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "command_id": self.command_id,
            "tool_id": self.tool_id,
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "lease_sha256": self.lease_sha256,
            "workspace_root_sha256": self.workspace_root_sha256,
            "trusted_runtime_root_sha256": self.trusted_runtime_root_sha256,
            "entrypoint_relative_path": self.entrypoint_relative_path,
            "working_directory": self.working_directory,
            "files": [item.to_dict() for item in self.files],
            "total_bytes": self.total_bytes,
        }

    def canonical_json(self) -> str:
        return _closure_canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _closure_sha256(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class SignedRuntimeClosureManifest:
    manifest: RuntimeClosureManifest
    key_id: str
    signature_algorithm: str
    signature_sha256: str
    schema: str = SIGNED_RUNTIME_CLOSURE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SIGNED_RUNTIME_CLOSURE_SCHEMA:
            raise RuntimeClosureError("unsupported signed runtime closure schema")
        if not isinstance(self.manifest, RuntimeClosureManifest):
            raise RuntimeClosureError("signed runtime closure payload is invalid")
        if not isinstance(self.key_id, str) or _IDENTIFIER.fullmatch(self.key_id) is None:
            raise RuntimeClosureError("runtime closure key id is invalid")
        if self.signature_algorithm != RUNTIME_CLOSURE_SIGNATURE_ALGORITHM:
            raise RuntimeClosureError("runtime closure signature algorithm is invalid")
        if (
            not isinstance(self.signature_sha256, str)
            or _HEX64.fullmatch(self.signature_sha256) is None
        ):
            raise RuntimeClosureError("runtime closure signature is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "SignedRuntimeClosureManifest":
        fields = {
            "schema",
            "manifest",
            "key_id",
            "signature_algorithm",
            "signature_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise RuntimeClosureError("signed runtime closure fields mismatch")
        return cls(
            schema=value["schema"],
            manifest=RuntimeClosureManifest.from_mapping(value["manifest"]),
            key_id=value["key_id"],
            signature_algorithm=value["signature_algorithm"],
            signature_sha256=value["signature_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest": self.manifest.to_dict(),
            "key_id": self.key_id,
            "signature_algorithm": self.signature_algorithm,
            "signature_sha256": self.signature_sha256,
        }

    def canonical_json(self) -> str:
        return _closure_canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _closure_sha256(self.canonical_json().encode("utf-8"))


class HmacRuntimeClosureSigner:
    def __init__(self, key_id: str, secret: bytes) -> None:
        if not isinstance(key_id, str) or _IDENTIFIER.fullmatch(key_id) is None:
            raise RuntimeClosureError("runtime closure signing key id is invalid")
        if not isinstance(secret, bytes) or not 32 <= len(secret) <= 4096:
            raise RuntimeClosureError("runtime closure secret must be 32..4096 bytes")
        self.key_id = key_id
        self._secret = secret

    def sign(self, manifest: RuntimeClosureManifest) -> SignedRuntimeClosureManifest:
        if not isinstance(manifest, RuntimeClosureManifest):
            raise RuntimeClosureError("only a runtime closure manifest can be signed")
        signature = hmac.new(
            self._secret,
            manifest.canonical_json().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SignedRuntimeClosureManifest(
            manifest=manifest,
            key_id=self.key_id,
            signature_algorithm=RUNTIME_CLOSURE_SIGNATURE_ALGORITHM,
            signature_sha256=signature,
        )
