"""Verification of signed runtime closures against exact leased authority."""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from . import _tier_a_execution_core as _core
from ._runtime_closure_common import (
    RuntimeClosureError,
    _MAX_CLOSURE_BYTES,
    _MAX_CLOSURE_FILES,
    _IDENTIFIER,
    _closure_canonical_directory,
    _closure_canonical_source,
    _closure_file_hash_and_size,
    _closure_task_sha,
    trusted_runtime_root_sha256,
)
from .contract import DevelopmentTask
from .runtime_closure_model import (
    RuntimeClosureFile,
    SignedRuntimeClosureManifest,
)

LeasedCommandRegistry = _core.LeasedCommandRegistry


class RuntimeClosureVerifier:
    def __init__(
        self,
        keyring: Mapping[str, bytes],
        *,
        max_files: int = _MAX_CLOSURE_FILES,
        max_total_bytes: int = _MAX_CLOSURE_BYTES,
    ) -> None:
        if (
            isinstance(max_files, bool)
            or not isinstance(max_files, int)
            or not 1 <= max_files <= _MAX_CLOSURE_FILES
        ):
            raise RuntimeClosureError("runtime closure file budget is invalid")
        if (
            isinstance(max_total_bytes, bool)
            or not isinstance(max_total_bytes, int)
            or not 1 <= max_total_bytes <= _MAX_CLOSURE_BYTES
        ):
            raise RuntimeClosureError("runtime closure byte budget is invalid")
        clean: dict[str, bytes] = {}
        for key_id, secret in keyring.items():
            if not isinstance(key_id, str) or _IDENTIFIER.fullmatch(key_id) is None:
                raise RuntimeClosureError("runtime closure key id is invalid")
            if not isinstance(secret, bytes) or not 32 <= len(secret) <= 4096:
                raise RuntimeClosureError("runtime closure key is invalid")
            clean[key_id] = secret
        if not clean:
            raise RuntimeClosureError("runtime closure keyring is empty")
        self.keyring = MappingProxyType(clean)
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes

    def verify(
        self,
        signed: SignedRuntimeClosureManifest,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str,
        *,
        trusted_runtime_root: Path,
    ) -> tuple[Path, tuple[tuple[RuntimeClosureFile, Path], ...]]:
        if not isinstance(signed, SignedRuntimeClosureManifest):
            raise RuntimeClosureError("runtime closure must be signed")
        if not isinstance(registry, LeasedCommandRegistry):
            raise RuntimeClosureError("runtime closure requires a leased registry")
        try:
            secret = self.keyring[signed.key_id]
        except KeyError as exc:
            raise RuntimeClosureError("runtime closure signing key is not trusted") from exc
        expected_signature = hmac.new(
            secret,
            signed.manifest.canonical_json().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, signed.signature_sha256):
            raise RuntimeClosureError("runtime closure signature is invalid")

        root = _closure_canonical_directory(trusted_runtime_root, name="trusted runtime root")
        manifest = signed.manifest
        template = registry.resolve(task, command_id)
        registry.lease.verify_attestation(registry.attestation)
        specification = registry.catalog.resolve(command_id)
        binding = registry.toolchain.resolve(specification.tool_id)
        expected = {
            "task_id": task.task_id,
            "task_sha256": _closure_task_sha(task),
            "repository": task.repository,
            "base_sha": task.base_sha,
            "command_id": command_id,
            "tool_id": specification.tool_id,
            "catalog_sha256": registry.catalog.sha256,
            "toolchain_sha256": registry.toolchain.sha256,
            "lease_sha256": registry.lease.sha256,
            "workspace_root_sha256": registry.lease.workspace_root_sha256,
            "trusted_runtime_root_sha256": trusted_runtime_root_sha256(root),
            "working_directory": template.cwd,
        }
        actual = {
            "task_id": manifest.task_id,
            "task_sha256": manifest.task_sha256,
            "repository": manifest.repository,
            "base_sha": manifest.base_sha,
            "command_id": manifest.command_id,
            "tool_id": manifest.tool_id,
            "catalog_sha256": manifest.catalog_sha256,
            "toolchain_sha256": manifest.toolchain_sha256,
            "lease_sha256": manifest.lease_sha256,
            "workspace_root_sha256": manifest.workspace_root_sha256,
            "trusted_runtime_root_sha256": manifest.trusted_runtime_root_sha256,
            "working_directory": manifest.working_directory,
        }
        if actual != expected:
            raise RuntimeClosureError(
                "runtime closure is not bound to the exact command authority"
            )
        if len(manifest.files) > self.max_files or manifest.total_bytes > self.max_total_bytes:
            raise RuntimeClosureError("runtime closure exceeds verifier budgets")
        source_entrypoint = _closure_canonical_source(Path(binding.executable), root)
        if source_entrypoint.relative_to(root).as_posix() != manifest.entrypoint_relative_path:
            raise RuntimeClosureError(
                "runtime closure entrypoint does not match the tool binding"
            )
        verified: list[tuple[RuntimeClosureFile, Path]] = []
        for entry in manifest.files:
            source = _closure_canonical_source(
                root.joinpath(*PurePosixPath(entry.relative_path).parts), root
            )
            digest, size = _closure_file_hash_and_size(
                source, maximum=self.max_total_bytes
            )
            if digest != entry.sha256 or size != entry.size_bytes:
                raise RuntimeClosureError(
                    f"runtime closure file changed: {entry.relative_path}"
                )
            verified.append((entry, source))
        entrypoint = next(
            item
            for item in manifest.files
            if item.relative_path == manifest.entrypoint_relative_path
        )
        if entrypoint.sha256 != binding.executable_sha256:
            raise RuntimeClosureError(
                "runtime closure entrypoint hash does not match the tool binding"
            )
        return root, tuple(verified)
