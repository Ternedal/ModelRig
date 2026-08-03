"""Versioned ModelRig command catalog and isolation-bound materialization.

The catalog names tools rather than executable paths. A separately trusted
host binding supplies absolute executables and their hashes. Project commands
are never executable until an OS-isolation attestation is independently
verified and bound to the exact task, catalog and toolchain.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from .commands import CommandRegistry, CommandTemplate
from .contract import DevelopmentTask

CATALOG_SCHEMA = "kaliv-modelrig-command-catalog/v1"
TOOLCHAIN_SCHEMA = "kaliv-development-toolchain/v1"
ATTESTATION_SCHEMA = "kaliv-development-isolation-attestation/v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOOL_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")


class CatalogError(ValueError):
    """Catalog, toolchain or isolation authority is invalid or incomplete."""


class IsolationBoundary(StrEnum):
    OS_ISOLATED = "os_isolated"


class NetworkMode(StrEnum):
    DENY = "deny"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _task_sha(task: DevelopmentTask) -> str:
    return _sha256(task.canonical_json().encode("utf-8"))


def _canonical(data: Mapping[str, Any]) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _is_absolute_executable(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


@dataclass(frozen=True, slots=True)
class ProjectCommandSpec:
    command_id: str
    tool_id: str
    args: tuple[str, ...]
    cwd: str
    max_timeout_seconds: int
    env: Mapping[str, str] = field(default_factory=dict)
    required_boundary: IsolationBoundary = IsolationBoundary.OS_ISOLATED
    network_mode: NetworkMode = NetworkMode.DENY

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, str) or _TOOL_ID.fullmatch(self.command_id) is None:
            raise CatalogError("invalid catalog command id")
        if not isinstance(self.tool_id, str) or _TOOL_ID.fullmatch(self.tool_id) is None:
            raise CatalogError("invalid catalog tool id")
        if not isinstance(self.args, tuple) or any(
            not isinstance(item, str) or not item or "\x00" in item for item in self.args
        ):
            raise CatalogError("catalog arguments must be canonical strings")
        if self.cwd != ".":
            path = PurePosixPath(self.cwd)
            if (
                self.cwd.startswith("/")
                or "\\" in self.cwd
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise CatalogError("catalog cwd must be repository-relative")
        if (
            isinstance(self.max_timeout_seconds, bool)
            or not isinstance(self.max_timeout_seconds, int)
            or not 1 <= self.max_timeout_seconds <= 86_400
        ):
            raise CatalogError("catalog timeout is outside bounds")
        clean_env: dict[str, str] = {}
        for key, value in self.env.items():
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or "\x00" in key + value
            ):
                raise CatalogError("catalog environment is invalid")
            clean_env[key] = value
        object.__setattr__(self, "env", MappingProxyType(clean_env))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "tool_id": self.tool_id,
            "args": list(self.args),
            "cwd": self.cwd,
            "max_timeout_seconds": self.max_timeout_seconds,
            "env": dict(sorted(self.env.items())),
            "required_boundary": self.required_boundary.value,
            "network_mode": self.network_mode.value,
        }


class ModelRigCommandCatalog:
    """Immutable, versioned command authority for the ModelRig repository."""

    def __init__(self, specs: Sequence[ProjectCommandSpec]) -> None:
        values: dict[str, ProjectCommandSpec] = {}
        for spec in specs:
            if spec.command_id in values:
                raise CatalogError(f"duplicate catalog command: {spec.command_id}")
            values[spec.command_id] = spec
        self._specs = MappingProxyType(values)

    @property
    def command_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def resolve(self, command_id: str) -> ProjectCommandSpec:
        try:
            return self._specs[command_id]
        except KeyError as exc:
            raise CatalogError(f"command is not in the ModelRig catalog: {command_id}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CATALOG_SCHEMA,
            "repository": "Ternedal/ModelRig",
            "commands": [self._specs[key].to_dict() for key in sorted(self._specs)],
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_id: str
    executable: str
    executable_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or _TOOL_ID.fullmatch(self.tool_id) is None:
            raise CatalogError("invalid tool binding id")
        if (
            not isinstance(self.executable, str)
            or not self.executable
            or "\x00" in self.executable
            or not _is_absolute_executable(self.executable)
        ):
            raise CatalogError("tool executable must be an absolute path")
        if (
            not isinstance(self.executable_sha256, str)
            or _HEX64.fullmatch(self.executable_sha256) is None
        ):
            raise CatalogError("tool executable hash must be lowercase SHA-256")

    def to_dict(self) -> dict[str, str]:
        return {
            "tool_id": self.tool_id,
            "executable": self.executable,
            "executable_sha256": self.executable_sha256,
        }


class Toolchain:
    """Immutable operator-controlled mapping from tool ids to exact binaries."""

    def __init__(self, bindings: Sequence[ToolBinding]) -> None:
        values: dict[str, ToolBinding] = {}
        for binding in bindings:
            if binding.tool_id in values:
                raise CatalogError(f"duplicate tool binding: {binding.tool_id}")
            values[binding.tool_id] = binding
        self._bindings = MappingProxyType(values)

    def resolve(self, tool_id: str) -> ToolBinding:
        try:
            return self._bindings[tool_id]
        except KeyError as exc:
            raise CatalogError(f"required tool is not bound: {tool_id}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TOOLCHAIN_SCHEMA,
            "bindings": [self._bindings[key].to_dict() for key in sorted(self._bindings)],
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class IsolationAttestation:
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    catalog_sha256: str
    toolchain_sha256: str
    boundary: IsolationBoundary
    network_mode: NetworkMode
    evidence_sha256: tuple[str, ...]
    schema: str = ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ATTESTATION_SCHEMA:
            raise CatalogError("unsupported isolation attestation schema")
        if (
            not isinstance(self.task_id, str)
            or _TASK_ID.fullmatch(self.task_id) is None
            or self.repository != "Ternedal/ModelRig"
        ):
            raise CatalogError("isolation attestation identity is invalid")
        if not isinstance(self.boundary, IsolationBoundary) or not isinstance(
            self.network_mode, NetworkMode
        ):
            raise CatalogError("isolation boundary or network mode is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise CatalogError(f"{name} is invalid")
        if not isinstance(self.base_sha, str) or re.fullmatch(r"[0-9a-f]{40}", self.base_sha) is None:
            raise CatalogError("attestation base SHA is invalid")
        if (
            not isinstance(self.evidence_sha256, tuple)
            or not self.evidence_sha256
            or len(self.evidence_sha256) > 32
        ):
            raise CatalogError("isolation evidence must be an immutable tuple of 1..32 hashes")
        if any(_HEX64.fullmatch(item) is None for item in self.evidence_sha256):
            raise CatalogError("isolation evidence hash is invalid")
        if len(set(self.evidence_sha256)) != len(self.evidence_sha256):
            raise CatalogError("isolation evidence hashes must be unique")

    @classmethod
    def from_mapping(cls, value: Any) -> "IsolationAttestation":
        if not isinstance(value, Mapping):
            raise CatalogError("isolation attestation must be an object")
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "repository",
            "base_sha",
            "catalog_sha256",
            "toolchain_sha256",
            "boundary",
            "network_mode",
            "evidence_sha256",
        }
        if set(value) != fields:
            raise CatalogError("isolation attestation fields mismatch")
        evidence = value["evidence_sha256"]
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise CatalogError("isolation evidence must be a string array")
        try:
            boundary = IsolationBoundary(value["boundary"])
            network_mode = NetworkMode(value["network_mode"])
        except (TypeError, ValueError) as exc:
            raise CatalogError("unsupported isolation boundary or network mode") from exc
        return cls(
            schema=value["schema"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            repository=value["repository"],
            base_sha=value["base_sha"],
            catalog_sha256=value["catalog_sha256"],
            toolchain_sha256=value["toolchain_sha256"],
            boundary=boundary,
            network_mode=network_mode,
            evidence_sha256=tuple(evidence),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "boundary": self.boundary.value,
            "network_mode": self.network_mode.value,
            "evidence_sha256": list(self.evidence_sha256),
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class IsolationVerifier(Protocol):
    def verify(self, attestation: IsolationAttestation) -> None: ...


class ExecutableVerifier(Protocol):
    def verify(self, binding: ToolBinding) -> None: ...


class RejectUnverifiedIsolation:
    """Fail-closed default until a physical isolation verifier is injected."""

    def verify(self, attestation: IsolationAttestation) -> None:
        raise CatalogError("OS isolation has not been independently verified")


class LocalExecutableHashVerifier:
    """Verify a trusted absolute executable path without following a symlink."""

    def verify(self, binding: ToolBinding) -> None:
        path = Path(binding.executable)
        if path.is_symlink() or not path.is_file():
            raise CatalogError(f"tool executable is not a regular file: {binding.tool_id}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != binding.executable_sha256:
            raise CatalogError(f"tool executable hash mismatch: {binding.tool_id}")


class CatalogMaterializer:
    """Turn catalog ids into executable templates only after all gates pass."""

    def __init__(
        self,
        catalog: ModelRigCommandCatalog,
        *,
        isolation_verifier: IsolationVerifier | None = None,
        executable_verifier: ExecutableVerifier | None = None,
    ) -> None:
        self.catalog = catalog
        self.isolation_verifier = isolation_verifier or RejectUnverifiedIsolation()
        self.executable_verifier = executable_verifier or LocalExecutableHashVerifier()

    def materialize(
        self,
        task: DevelopmentTask,
        toolchain: Toolchain,
        attestation: IsolationAttestation,
    ) -> CommandRegistry:
        if task.repository != "Ternedal/ModelRig":
            raise CatalogError("ModelRig catalog cannot authorize another repository")

        selected = tuple(self.catalog.resolve(item) for item in task.allowed_command_ids)
        expected = {
            "task_id": task.task_id,
            "task_sha256": _task_sha(task),
            "repository": task.repository,
            "base_sha": task.base_sha,
            "catalog_sha256": self.catalog.sha256,
            "toolchain_sha256": toolchain.sha256,
            "boundary": IsolationBoundary.OS_ISOLATED,
            "network_mode": NetworkMode.DENY,
        }
        actual = {
            "task_id": attestation.task_id,
            "task_sha256": attestation.task_sha256,
            "repository": attestation.repository,
            "base_sha": attestation.base_sha,
            "catalog_sha256": attestation.catalog_sha256,
            "toolchain_sha256": attestation.toolchain_sha256,
            "boundary": attestation.boundary,
            "network_mode": attestation.network_mode,
        }
        if actual != expected:
            raise CatalogError("isolation attestation is not bound to this exact authority")

        self.isolation_verifier.verify(attestation)

        templates: list[CommandTemplate] = []
        verified_tools: set[str] = set()
        for spec in selected:
            if spec.required_boundary is not IsolationBoundary.OS_ISOLATED:
                raise CatalogError("catalog boundary weakened unexpectedly")
            if spec.network_mode is not NetworkMode.DENY:
                raise CatalogError("catalog command unexpectedly permits network")
            binding = toolchain.resolve(spec.tool_id)
            if binding.tool_id not in verified_tools:
                self.executable_verifier.verify(binding)
                verified_tools.add(binding.tool_id)
            templates.append(
                CommandTemplate(
                    command_id=spec.command_id,
                    argv=(binding.executable, *spec.args),
                    cwd=spec.cwd,
                    max_timeout_seconds=spec.max_timeout_seconds,
                    env=spec.env,
                )
            )
        return CommandRegistry(templates)


def modelrig_command_catalog() -> ModelRigCommandCatalog:
    """Return the reviewed v1 ModelRig command catalog.

    Every entry executes repository-controlled code and therefore requires a
    separately proven OS boundary with network denied.
    """

    common = {"CI": "1", "MODELRIG_DEVCONTROL": "1"}
    return ModelRigCommandCatalog(
        (
            ProjectCommandSpec(
                "modelrig.version.check",
                "python",
                ("scripts/version_tool.py", "check"),
                ".",
                120,
                common,
            ),
            ProjectCommandSpec(
                "modelrig.devcontrol.tests",
                "python",
                ("-m", "unittest", "discover", "-s", "devcontrol/tests", "-v"),
                ".",
                900,
                common,
            ),
            ProjectCommandSpec(
                "modelrig.workflow.test-coverage",
                "python",
                ("tests/workflow_test_coverage.py",),
                ".",
                3_600,
                common,
            ),
            ProjectCommandSpec(
                "modelrig.backend.vet",
                "go",
                ("vet", "./..."),
                "backend",
                900,
                {**common, "GOTOOLCHAIN": "local"},
            ),
            ProjectCommandSpec(
                "modelrig.backend.tests",
                "go",
                ("test", "./..."),
                "backend",
                3_600,
                {**common, "GOTOOLCHAIN": "local"},
            ),
        )
    )
