"""Trusted, deterministic runtime staging for dormant Tier-A commands.

This module does not execute a process and grants no repository or GitHub write
authority. It copies one operator-bound executable into a deterministic
workspace location only after the exact task, leased command registry, catalog,
toolchain and signed workspace authority agree.

The public Tier-A runtime consumes the immutable receipt by rebinding exactly one
leased command template to the verified staged path. Staging still cannot launch
a process by itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .catalog import CatalogError
from .commands import CommandRegistry, CommandTemplate
from .contract import DevelopmentTask
from .tier_a_execution import (
    LeasedCommandRegistry,
    workspace_root_authority_sha256,
)

RUNTIME_STAGING_SCHEMA = "kaliv-development-runtime-staging-receipt/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_AUTHORITY_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFAULT_MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024


class RuntimeStagingError(CatalogError):
    """A trusted runtime could not be staged without weakening authority."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _task_sha(task: DevelopmentTask) -> str:
    return _sha256(task.canonical_json().encode("utf-8"))


def _is_linkish(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if _is_linkish(current):
            return True
        if current.parent == current:
            return False
        current = current.parent


def _canonical_directory(path: Path, *, name: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise RuntimeStagingError(f"{name} must be absolute")
    if _has_linkish_component(raw):
        raise RuntimeStagingError(f"{name} must not contain links or junctions")
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise RuntimeStagingError(f"{name} must be an existing directory")
    return resolved


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_source(path: Path, trusted_root: Path) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise RuntimeStagingError("trusted runtime source must be absolute")
    if _has_linkish_component(raw):
        raise RuntimeStagingError(
            "trusted runtime source must not contain links or junctions"
        )
    resolved = raw.resolve()
    if not _inside(resolved, trusted_root):
        raise RuntimeStagingError(
            "trusted runtime source is outside the operator-controlled root"
        )
    if not resolved.is_file() or _is_linkish(resolved):
        raise RuntimeStagingError("trusted runtime source must be a regular file")
    return resolved


def _file_hash_and_size(path: Path, *, maximum: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if maximum is not None and size > maximum:
                raise RuntimeStagingError("trusted runtime exceeds the staging budget")
            digest.update(chunk)
    if size == 0:
        raise RuntimeStagingError("trusted runtime source must not be empty")
    return digest.hexdigest(), size


def _path_identity(path: Path) -> str:
    canonical = os.path.normcase(os.fspath(path.resolve()))
    return _sha256(
        b"kaliv-runtime-source-path/v1\0"
        + canonical.encode("utf-8", "surrogatepass")
    )


def _secure_directory_chain(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise RuntimeStagingError("runtime staging directory is invalid")
        current = current / part
        try:
            current.mkdir()
        except FileExistsError:
            pass
        if _is_linkish(current) or not current.is_dir():
            raise RuntimeStagingError(
                "runtime staging directory changed to a link or non-directory"
            )
    return current


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class RuntimeStagingReceipt:
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
    source_path_sha256: str
    executable_sha256: str
    staged_relative_path: str
    size_bytes: int
    schema: str = RUNTIME_STAGING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RUNTIME_STAGING_SCHEMA:
            raise RuntimeStagingError("unsupported runtime staging receipt schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise RuntimeStagingError("runtime staging task id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise RuntimeStagingError("runtime staging repository is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
            ("lease_sha256", self.lease_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
            ("source_path_sha256", self.source_path_sha256, _HEX64),
            ("executable_sha256", self.executable_sha256, _HEX64),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise RuntimeStagingError(f"runtime staging {name} is invalid")
        for name, value in (
            ("command_id", self.command_id),
            ("tool_id", self.tool_id),
        ):
            if not isinstance(value, str) or _AUTHORITY_ID.fullmatch(value) is None:
                raise RuntimeStagingError(f"runtime staging {name} is invalid")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or not 1 <= self.size_bytes <= _DEFAULT_MAX_EXECUTABLE_BYTES
        ):
            raise RuntimeStagingError("runtime staging size is invalid")
        if not isinstance(self.staged_relative_path, str):
            raise RuntimeStagingError("runtime staging path is invalid")
        relative = PurePosixPath(self.staged_relative_path)
        expected_prefix = (
            ".kaliv",
            "runtime",
            self.tool_id,
            self.executable_sha256,
        )
        if (
            self.staged_relative_path.startswith("/")
            or "\\" in self.staged_relative_path
            or len(relative.parts) != 5
            or tuple(relative.parts[:4]) != expected_prefix
            or any(part in {"", ".", ".."} for part in relative.parts)
            or _BASENAME.fullmatch(relative.name) is None
        ):
            raise RuntimeStagingError("runtime staging path is not canonical")

    @classmethod
    def from_mapping(cls, value: Any) -> "RuntimeStagingReceipt":
        if not isinstance(value, Mapping):
            raise RuntimeStagingError("runtime staging receipt must be an object")
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
            "source_path_sha256",
            "executable_sha256",
            "staged_relative_path",
            "size_bytes",
        }
        if set(value) != fields:
            raise RuntimeStagingError("runtime staging receipt fields mismatch")
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
            source_path_sha256=value["source_path_sha256"],
            executable_sha256=value["executable_sha256"],
            staged_relative_path=value["staged_relative_path"],
            size_bytes=value["size_bytes"],
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
            "source_path_sha256": self.source_path_sha256,
            "executable_sha256": self.executable_sha256,
            "staged_relative_path": self.staged_relative_path,
            "size_bytes": self.size_bytes,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))


class TrustedRuntimeStager:
    """Stage one exact operator-bound executable without executing it."""

    def __init__(
        self,
        trusted_runtime_root: Path,
        workspace_root: Path,
        *,
        max_executable_bytes: int = _DEFAULT_MAX_EXECUTABLE_BYTES,
    ) -> None:
        if (
            isinstance(max_executable_bytes, bool)
            or not isinstance(max_executable_bytes, int)
            or not 1 <= max_executable_bytes <= _DEFAULT_MAX_EXECUTABLE_BYTES
        ):
            raise RuntimeStagingError("runtime staging budget is invalid")
        trusted = _canonical_directory(
            trusted_runtime_root, name="trusted runtime root"
        )
        workspace = _canonical_directory(workspace_root, name="workspace root")
        if _inside(trusted, workspace) or _inside(workspace, trusted):
            raise RuntimeStagingError(
                "trusted runtime root and workspace must be separate trees"
            )
        self.trusted_runtime_root = trusted
        self.workspace_root = workspace
        self.max_executable_bytes = max_executable_bytes

    def _authority(
        self,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ):
        if not isinstance(registry, LeasedCommandRegistry):
            raise RuntimeStagingError(
                "runtime staging requires a leased command registry"
            )
        template = registry.resolve(task, command_id)
        registry.lease.verify_attestation(registry.attestation)
        task_sha256 = _task_sha(task)
        if (
            registry.lease.task_sha256 != task_sha256
            or registry.lease.base_sha != task.base_sha
            or registry.lease.catalog_sha256 != registry.catalog.sha256
            or registry.lease.toolchain_sha256 != registry.toolchain.sha256
        ):
            raise RuntimeStagingError(
                "runtime staging authority does not match the exact task"
            )
        actual_workspace = workspace_root_authority_sha256(self.workspace_root)
        if actual_workspace != registry.lease.workspace_root_sha256:
            raise RuntimeStagingError(
                "runtime staging workspace does not match the signed report"
            )
        specification = registry.catalog.resolve(command_id)
        binding = registry.toolchain.resolve(specification.tool_id)
        if template.argv[0] != binding.executable:
            raise RuntimeStagingError(
                "materialized command executable does not match the tool binding"
            )
        return specification, binding, task_sha256

    def _receipt(
        self,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
        *,
        tool_id: str,
        source: Path,
        executable_sha256: str,
        staged_relative_path: str,
        size_bytes: int,
        task_sha256: str,
    ) -> RuntimeStagingReceipt:
        return RuntimeStagingReceipt(
            task_id=task.task_id,
            task_sha256=task_sha256,
            repository=task.repository,
            base_sha=task.base_sha,
            command_id=command_id,
            tool_id=tool_id,
            catalog_sha256=registry.catalog.sha256,
            toolchain_sha256=registry.toolchain.sha256,
            lease_sha256=registry.lease.sha256,
            workspace_root_sha256=registry.lease.workspace_root_sha256,
            source_path_sha256=_path_identity(source),
            executable_sha256=executable_sha256,
            staged_relative_path=staged_relative_path,
            size_bytes=size_bytes,
        )

    def stage(
        self,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ) -> RuntimeStagingReceipt:
        """Copy one exact trusted executable into its deterministic workspace slot."""

        specification, binding, task_sha256 = self._authority(
            registry, task, command_id
        )
        source = _canonical_source(
            Path(binding.executable), self.trusted_runtime_root
        )
        executable_sha256, size_bytes = _file_hash_and_size(
            source, maximum=self.max_executable_bytes
        )
        if executable_sha256 != binding.executable_sha256:
            raise RuntimeStagingError("trusted runtime source hash mismatch")
        if _BASENAME.fullmatch(source.name) is None:
            raise RuntimeStagingError("trusted runtime source basename is invalid")

        relative = PurePosixPath(
            ".kaliv",
            "runtime",
            specification.tool_id,
            executable_sha256,
            source.name,
        )
        parent = _secure_directory_chain(
            self.workspace_root, PurePosixPath(*relative.parts[:-1])
        )
        destination = parent / relative.name
        if _is_linkish(destination):
            raise RuntimeStagingError("staged runtime destination is a link")

        if destination.exists():
            if not destination.is_file():
                raise RuntimeStagingError(
                    "staged runtime destination is not a regular file"
                )
            existing_hash, existing_size = _file_hash_and_size(
                destination, maximum=self.max_executable_bytes
            )
            if existing_hash != executable_sha256 or existing_size != size_bytes:
                raise RuntimeStagingError(
                    "staged runtime destination already exists with different bytes"
                )
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".kaliv-stage-", suffix=".tmp", dir=parent
            )
            temporary = Path(temporary_name)
            try:
                digest = hashlib.sha256()
                copied = 0
                with source.open("rb") as source_handle, os.fdopen(
                    descriptor, "wb", closefd=True
                ) as destination_handle:
                    while chunk := source_handle.read(1024 * 1024):
                        copied += len(chunk)
                        if copied > self.max_executable_bytes:
                            raise RuntimeStagingError(
                                "trusted runtime exceeds the staging budget"
                            )
                        destination_handle.write(chunk)
                        digest.update(chunk)
                    destination_handle.flush()
                    os.fsync(destination_handle.fileno())
                descriptor = -1
                if copied != size_bytes or digest.hexdigest() != executable_sha256:
                    raise RuntimeStagingError(
                        "trusted runtime changed while it was being staged"
                    )
                try:
                    os.chmod(temporary, 0o555)
                except OSError as exc:
                    raise RuntimeStagingError(
                        "staged runtime permissions could not be fixed"
                    ) from exc
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    existing_hash, existing_size = _file_hash_and_size(
                        destination, maximum=self.max_executable_bytes
                    )
                    if (
                        existing_hash != executable_sha256
                        or existing_size != size_bytes
                    ):
                        raise RuntimeStagingError(
                            "concurrent runtime staging produced different bytes"
                        )
                _fsync_directory(parent)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

        receipt = self._receipt(
            registry,
            task,
            command_id,
            tool_id=specification.tool_id,
            source=source,
            executable_sha256=executable_sha256,
            staged_relative_path=relative.as_posix(),
            size_bytes=size_bytes,
            task_sha256=task_sha256,
        )
        self.verify(receipt, registry, task, command_id)
        return receipt

    def verify(
        self,
        receipt: RuntimeStagingReceipt,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ) -> Path:
        """Rebind a persisted receipt and rehash source and staged executable."""

        if not isinstance(receipt, RuntimeStagingReceipt):
            raise RuntimeStagingError("runtime staging verification requires a receipt")
        specification, binding, task_sha256 = self._authority(
            registry, task, command_id
        )
        source = _canonical_source(
            Path(binding.executable), self.trusted_runtime_root
        )
        source_sha256, source_size = _file_hash_and_size(
            source, maximum=self.max_executable_bytes
        )
        if source_sha256 != binding.executable_sha256:
            raise RuntimeStagingError("trusted runtime source hash mismatch")
        expected = self._receipt(
            registry,
            task,
            command_id,
            tool_id=specification.tool_id,
            source=source,
            executable_sha256=source_sha256,
            staged_relative_path=receipt.staged_relative_path,
            size_bytes=source_size,
            task_sha256=task_sha256,
        )
        if receipt != expected:
            raise RuntimeStagingError(
                "runtime staging receipt is not bound to the exact authority"
            )
        relative = PurePosixPath(receipt.staged_relative_path)
        destination = self.workspace_root.joinpath(*relative.parts)
        if (
            _has_linkish_component(destination)
            or not destination.is_file()
            or not _inside(destination.resolve(), self.workspace_root)
        ):
            raise RuntimeStagingError("staged runtime path is missing or unsafe")
        digest, size = _file_hash_and_size(
            destination, maximum=self.max_executable_bytes
        )
        if digest != receipt.executable_sha256 or size != receipt.size_bytes:
            raise RuntimeStagingError("staged runtime bytes no longer match the receipt")
        return destination.resolve()

    def bind_for_launch(
        self,
        receipt: RuntimeStagingReceipt,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ) -> LeasedCommandRegistry:
        """Rebind exactly one leased template to its verified staged executable."""

        destination = self.verify(receipt, registry, task, command_id)
        original = registry.resolve(task, command_id)
        staged_template = CommandTemplate(
            command_id=original.command_id,
            argv=(os.fspath(destination), *original.argv[1:]),
            cwd=original.cwd,
            max_timeout_seconds=original.max_timeout_seconds,
            env=original.env,
        )
        return LeasedCommandRegistry(
            CommandRegistry((staged_template,)),
            registry.lease,
            task=task,
            catalog=registry.catalog,
            toolchain=registry.toolchain,
            attestation=registry.attestation,
        )
