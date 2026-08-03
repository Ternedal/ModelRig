"""Deterministic exact-file staging for verified runtime closures."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import _tier_a_execution_core as _core
from ._runtime_closure_common import (
    RUNTIME_CLOSURE_STAGING_SCHEMA,
    RuntimeClosureError,
    _AUTHORITY_ID,
    _HEX40,
    _HEX64,
    _MAX_CLOSURE_BYTES,
    _MAX_CLOSURE_FILES,
    _TASK_ID,
    _closure_canonical,
    _closure_canonical_directory,
    _closure_file_hash_and_size,
    _closure_has_linkish_component,
    _closure_inside,
    _closure_is_linkish,
    _closure_publish_exact_file,
    _closure_relative_path,
    _closure_secure_directory_chain,
    _closure_sha256,
    _closure_task_sha,
    _closure_working_directory,
)
from .commands import CommandRegistry, CommandTemplate
from .contract import DevelopmentTask
from .runtime_closure_model import (
    RuntimeClosureFile,
    SignedRuntimeClosureManifest,
)
from .runtime_closure_verify import RuntimeClosureVerifier

LeasedCommandRegistry = _core.LeasedCommandRegistry


@dataclass(frozen=True, slots=True)
class RuntimeClosureStagingReceipt:
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
    manifest_sha256: str
    signed_manifest_sha256: str
    staged_root_relative_path: str
    staged_entrypoint_relative_path: str
    working_directory: str
    files: tuple[RuntimeClosureFile, ...]
    total_bytes: int
    schema: str = RUNTIME_CLOSURE_STAGING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RUNTIME_CLOSURE_STAGING_SCHEMA:
            raise RuntimeClosureError("unsupported runtime closure receipt schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise RuntimeClosureError("runtime closure receipt task id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise RuntimeClosureError("runtime closure receipt repository is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
            ("lease_sha256", self.lease_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
            ("manifest_sha256", self.manifest_sha256, _HEX64),
            ("signed_manifest_sha256", self.signed_manifest_sha256, _HEX64),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise RuntimeClosureError(f"runtime closure receipt {name} is invalid")
        for name, value in (("command_id", self.command_id), ("tool_id", self.tool_id)):
            if not isinstance(value, str) or _AUTHORITY_ID.fullmatch(value) is None:
                raise RuntimeClosureError(f"runtime closure receipt {name} is invalid")
        expected_root = PurePosixPath(
            ".kaliv", "runtime-closures", self.tool_id, self.manifest_sha256
        ).as_posix()
        if self.staged_root_relative_path != expected_root:
            raise RuntimeClosureError("runtime closure staged root is not canonical")
        entrypoint = _closure_relative_path(
            self.staged_entrypoint_relative_path, name="staged entrypoint"
        )
        if not entrypoint.startswith(expected_root + "/"):
            raise RuntimeClosureError("staged entrypoint escaped its closure root")
        object.__setattr__(self, "staged_entrypoint_relative_path", entrypoint)
        object.__setattr__(
            self, "working_directory", _closure_working_directory(self.working_directory)
        )
        if (
            not isinstance(self.files, tuple)
            or not self.files
            or any(not isinstance(item, RuntimeClosureFile) for item in self.files)
        ):
            raise RuntimeClosureError("runtime closure receipt file set is invalid")
        if self.total_bytes != sum(item.size_bytes for item in self.files):
            raise RuntimeClosureError("runtime closure receipt size is inconsistent")

    @classmethod
    def from_mapping(cls, value: Any) -> "RuntimeClosureStagingReceipt":
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
            "manifest_sha256",
            "signed_manifest_sha256",
            "staged_root_relative_path",
            "staged_entrypoint_relative_path",
            "working_directory",
            "files",
            "total_bytes",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise RuntimeClosureError("runtime closure receipt fields mismatch")
        files = value["files"]
        if not isinstance(files, list):
            raise RuntimeClosureError("runtime closure receipt files must be an array")
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
            manifest_sha256=value["manifest_sha256"],
            signed_manifest_sha256=value["signed_manifest_sha256"],
            staged_root_relative_path=value["staged_root_relative_path"],
            staged_entrypoint_relative_path=value["staged_entrypoint_relative_path"],
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
            "manifest_sha256": self.manifest_sha256,
            "signed_manifest_sha256": self.signed_manifest_sha256,
            "staged_root_relative_path": self.staged_root_relative_path,
            "staged_entrypoint_relative_path": self.staged_entrypoint_relative_path,
            "working_directory": self.working_directory,
            "files": [item.to_dict() for item in self.files],
            "total_bytes": self.total_bytes,
        }

    def canonical_json(self) -> str:
        return _closure_canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _closure_sha256(self.canonical_json().encode("utf-8"))


class TrustedRuntimeClosureStager:
    def __init__(
        self,
        trusted_runtime_root: Path,
        workspace_root: Path,
        *,
        max_files: int = _MAX_CLOSURE_FILES,
        max_total_bytes: int = _MAX_CLOSURE_BYTES,
    ) -> None:
        self.trusted_runtime_root = _closure_canonical_directory(
            trusted_runtime_root, name="trusted runtime root"
        )
        self.workspace_root = _closure_canonical_directory(
            workspace_root, name="workspace root"
        )
        if _closure_inside(self.trusted_runtime_root, self.workspace_root) or _closure_inside(
            self.workspace_root, self.trusted_runtime_root
        ):
            raise RuntimeClosureError(
                "trusted runtime root and workspace must be separate trees"
            )
        if (
            isinstance(max_files, bool)
            or not isinstance(max_files, int)
            or not 1 <= max_files <= _MAX_CLOSURE_FILES
        ):
            raise RuntimeClosureError("closure staging file budget is invalid")
        if (
            isinstance(max_total_bytes, bool)
            or not isinstance(max_total_bytes, int)
            or not 1 <= max_total_bytes <= _MAX_CLOSURE_BYTES
        ):
            raise RuntimeClosureError("closure staging byte budget is invalid")
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes

    def _receipt(
        self,
        signed: SignedRuntimeClosureManifest,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ) -> RuntimeClosureStagingReceipt:
        manifest = signed.manifest
        root_relative = PurePosixPath(
            ".kaliv", "runtime-closures", manifest.tool_id, manifest.sha256
        )
        return RuntimeClosureStagingReceipt(
            task_id=task.task_id,
            task_sha256=_closure_task_sha(task),
            repository=task.repository,
            base_sha=task.base_sha,
            command_id=command_id,
            tool_id=manifest.tool_id,
            catalog_sha256=registry.catalog.sha256,
            toolchain_sha256=registry.toolchain.sha256,
            lease_sha256=registry.lease.sha256,
            workspace_root_sha256=registry.lease.workspace_root_sha256,
            manifest_sha256=manifest.sha256,
            signed_manifest_sha256=signed.sha256,
            staged_root_relative_path=root_relative.as_posix(),
            staged_entrypoint_relative_path=(
                root_relative / PurePosixPath(manifest.entrypoint_relative_path)
            ).as_posix(),
            working_directory=manifest.working_directory,
            files=manifest.files,
            total_bytes=manifest.total_bytes,
        )

    def stage(
        self,
        signed: SignedRuntimeClosureManifest,
        verifier: RuntimeClosureVerifier,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ) -> RuntimeClosureStagingReceipt:
        if not isinstance(verifier, RuntimeClosureVerifier):
            raise RuntimeClosureError("closure stager requires its verifier")
        _, verified = verifier.verify(
            signed,
            registry,
            task,
            command_id,
            trusted_runtime_root=self.trusted_runtime_root,
        )
        if len(verified) > self.max_files or signed.manifest.total_bytes > self.max_total_bytes:
            raise RuntimeClosureError("runtime closure exceeds staging budgets")
        receipt = self._receipt(signed, registry, task, command_id)
        staged_root = _closure_secure_directory_chain(
            self.workspace_root, PurePosixPath(receipt.staged_root_relative_path)
        )
        for entry, source in verified:
            relative = PurePosixPath(entry.relative_path)
            parent = _closure_secure_directory_chain(
                staged_root, PurePosixPath(*relative.parts[:-1])
            )
            _closure_publish_exact_file(
                source,
                parent / relative.name,
                expected_sha256=entry.sha256,
                expected_size=entry.size_bytes,
                maximum=self.max_total_bytes,
            )
        self.verify(receipt, signed, verifier, registry, task, command_id)
        return receipt

    def verify(
        self,
        receipt: RuntimeClosureStagingReceipt,
        signed: SignedRuntimeClosureManifest,
        verifier: RuntimeClosureVerifier,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ) -> Path:
        if not isinstance(receipt, RuntimeClosureStagingReceipt):
            raise RuntimeClosureError("closure verification requires a receipt")
        verifier.verify(
            signed,
            registry,
            task,
            command_id,
            trusted_runtime_root=self.trusted_runtime_root,
        )
        if receipt != self._receipt(signed, registry, task, command_id):
            raise RuntimeClosureError("closure receipt is not bound to the authority")
        staged_root = self.workspace_root.joinpath(
            *PurePosixPath(receipt.staged_root_relative_path).parts
        )
        if (
            _closure_has_linkish_component(staged_root)
            or not staged_root.is_dir()
            or not _closure_inside(staged_root.resolve(), self.workspace_root)
        ):
            raise RuntimeClosureError("staged closure root is missing or unsafe")
        observed: set[str] = set()
        for path in staged_root.rglob("*"):
            if _closure_is_linkish(path):
                raise RuntimeClosureError("staged runtime closure contains a link")
            if path.is_dir():
                continue
            if not path.is_file() or path.stat().st_nlink != 1:
                raise RuntimeClosureError(
                    "staged closure contains a non-file or hardlink"
                )
            observed.add(path.relative_to(staged_root).as_posix())
        expected_paths = {item.relative_path for item in receipt.files}
        if observed != expected_paths:
            raise RuntimeClosureError(
                "staged runtime closure contains missing or unmanifested files"
            )
        for entry in receipt.files:
            destination = staged_root.joinpath(
                *PurePosixPath(entry.relative_path).parts
            )
            digest, size = _closure_file_hash_and_size(
                destination, maximum=self.max_total_bytes
            )
            if digest != entry.sha256 or size != entry.size_bytes:
                raise RuntimeClosureError(
                    f"staged runtime closure changed: {entry.relative_path}"
                )
        entrypoint = self.workspace_root.joinpath(
            *PurePosixPath(receipt.staged_entrypoint_relative_path).parts
        )
        if (
            not entrypoint.is_file()
            or entrypoint.stat().st_nlink != 1
            or _closure_has_linkish_component(entrypoint)
        ):
            raise RuntimeClosureError("staged runtime closure entrypoint is unsafe")
        return entrypoint.resolve()

    def bind_for_launch(
        self,
        receipt: RuntimeClosureStagingReceipt,
        signed: SignedRuntimeClosureManifest,
        verifier: RuntimeClosureVerifier,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
    ) -> LeasedCommandRegistry:
        entrypoint = self.verify(
            receipt, signed, verifier, registry, task, command_id
        )
        original = registry.resolve(task, command_id)
        template = CommandTemplate(
            command_id=original.command_id,
            argv=(os.fspath(entrypoint), *original.argv[1:]),
            cwd=original.cwd,
            max_timeout_seconds=original.max_timeout_seconds,
            env=original.env,
        )
        return LeasedCommandRegistry(
            CommandRegistry((template,)),
            registry.lease,
            task=task,
            catalog=registry.catalog,
            toolchain=registry.toolchain,
            attestation=registry.attestation,
        )
