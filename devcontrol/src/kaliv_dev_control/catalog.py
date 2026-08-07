from __future__ import annotations

try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from .commands import CommandPolicyError, CommandRegistry, CommandTemplate
from .contract import ContractError, DevelopmentTask

CATALOG_SCHEMA = "kaliv-modelrig-command-catalog/v1"
TOOLCHAIN_SCHEMA = "kaliv-development-toolchain/v1"
ATTESTATION_SCHEMA = "kaliv-development-isolation-attestation/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_FIXED_PATH = "/usr/bin:/bin"
_ALLOWED_ENV = {
    "CI": "1",
    "MODELRIG_DEVCONTROL": "1",
    "GOTOOLCHAIN": "local",
    "PATH": _FIXED_PATH,
}
_MAX_EXECUTABLE_BYTES = 256_000_000
_MAX_PINNED_EXECUTABLES = 128
_RETIRED_DESCRIPTORS: set[int] = set()


class CatalogError(ValueError):
    pass


class IsolationBoundary(StrEnum):
    OS_ISOLATED = "os_isolated"


class NetworkMode(StrEnum):
    DENY = "deny"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _task_sha(task: DevelopmentTask) -> str:
    return _sha256(task.canonical_json().encode("utf-8"))


def _absolute(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _linked(path: Path) -> bool:
    junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(junction and junction())


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
        if not isinstance(self.command_id, str) or _ID.fullmatch(self.command_id) is None:
            raise CatalogError("invalid catalog command id")
        if not isinstance(self.tool_id, str) or _ID.fullmatch(self.tool_id) is None:
            raise CatalogError("invalid catalog tool id")
        if not isinstance(self.args, tuple) or len(self.args) > 128 or any(
            not isinstance(arg, str) or not arg or "\0" in arg or len(arg.encode()) > 4096
            for arg in self.args
        ):
            raise CatalogError("catalog arguments must be bounded canonical strings")
        if not isinstance(self.cwd, str) or not self.cwd or "\0" in self.cwd:
            raise CatalogError("catalog cwd must be repository-relative")
        if self.cwd != ".":
            parts = self.cwd.split("/")
            if self.cwd.startswith("/") or "\\" in self.cwd or any(
                part in {"", ".", ".."} for part in parts
            ) or PurePosixPath(self.cwd).as_posix() != self.cwd:
                raise CatalogError("catalog cwd must be canonical and repository-relative")
        if isinstance(self.max_timeout_seconds, bool) or not isinstance(
            self.max_timeout_seconds, int
        ) or not 1 <= self.max_timeout_seconds <= 86_400:
            raise CatalogError("catalog timeout is outside bounds")
        if not isinstance(self.required_boundary, IsolationBoundary) or not isinstance(
            self.network_mode, NetworkMode
        ):
            raise CatalogError("catalog isolation policy is invalid")
        if not isinstance(self.env, Mapping):
            raise CatalogError("catalog environment must be an object")
        clean: dict[str, str] = {}
        for key, value in self.env.items():
            if (
                not isinstance(key, str) or not key or key.strip() != key or "=" in key
                or not isinstance(value, str) or "\0" in key + value
                or len(key.encode()) > 128 or len(value.encode()) > 4096
            ):
                raise CatalogError("catalog environment is invalid")
            if key not in _ALLOWED_ENV or value != _ALLOWED_ENV[key]:
                raise CatalogError("catalog environment is outside the reviewed isolation positive list")
            clean[key] = value
        if clean.get("PATH") != _FIXED_PATH:
            raise CatalogError("catalog environment must include the reviewed isolation PATH")
        object.__setattr__(self, "env", MappingProxyType(clean))

    def copy(self) -> "ProjectCommandSpec":
        return ProjectCommandSpec(
            command_id=self.command_id,
            tool_id=self.tool_id,
            args=tuple(self.args),
            cwd=self.cwd,
            max_timeout_seconds=self.max_timeout_seconds,
            env=dict(self.env),
            required_boundary=self.required_boundary,
            network_mode=self.network_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id, "tool_id": self.tool_id,
            "args": list(self.args), "cwd": self.cwd,
            "max_timeout_seconds": self.max_timeout_seconds,
            "env": dict(sorted(self.env.items())),
            "required_boundary": self.required_boundary.value,
            "network_mode": self.network_mode.value,
        }


class ModelRigCommandCatalog:
    def __init__(self, specs: Sequence[ProjectCommandSpec]) -> None:
        if isinstance(specs, (str, bytes)) or not isinstance(specs, Sequence):
            raise CatalogError("catalog specs must be a sequence")
        values: dict[str, ProjectCommandSpec] = {}
        for supplied in specs:
            if not isinstance(supplied, ProjectCommandSpec):
                raise CatalogError("catalog contains an invalid command spec")
            spec = supplied.copy()
            if spec.command_id in values:
                raise CatalogError(f"duplicate catalog command: {spec.command_id}")
            values[spec.command_id] = spec
        self._specs = MappingProxyType(values)

    def snapshot(self) -> "ModelRigCommandCatalog":
        current = self._specs
        return ModelRigCommandCatalog(tuple(current[key] for key in sorted(current)))

    @property
    def command_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def resolve(self, command_id: str) -> ProjectCommandSpec:
        if not isinstance(command_id, str) or _ID.fullmatch(command_id) is None:
            raise CatalogError("invalid catalog command id")
        try:
            return self._specs[command_id]
        except KeyError as exc:
            raise CatalogError(f"command is not in the ModelRig catalog: {command_id}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CATALOG_SCHEMA, "repository": "Ternedal/ModelRig",
            "commands": [self._specs[key].to_dict() for key in sorted(self._specs)],
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode())


@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_id: str
    executable: str
    executable_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or _ID.fullmatch(self.tool_id) is None:
            raise CatalogError("invalid tool binding id")
        if (
            not isinstance(self.executable, str) or not self.executable
            or self.executable.strip() != self.executable or "\0" in self.executable
            or len(self.executable.encode()) > 4096 or not _absolute(self.executable)
        ):
            raise CatalogError("tool executable must be a canonical absolute path")
        if not isinstance(self.executable_sha256, str) or _HEX64.fullmatch(
            self.executable_sha256
        ) is None:
            raise CatalogError("tool executable hash must be lowercase SHA-256")

    def copy(self) -> "ToolBinding":
        return ToolBinding(self.tool_id, self.executable, self.executable_sha256)

    def to_dict(self) -> dict[str, str]:
        return {
            "tool_id": self.tool_id, "executable": self.executable,
            "executable_sha256": self.executable_sha256,
        }


class Toolchain:
    def __init__(self, bindings: Sequence[ToolBinding]) -> None:
        if isinstance(bindings, (str, bytes)) or not isinstance(bindings, Sequence):
            raise CatalogError("toolchain bindings must be a sequence")
        values: dict[str, ToolBinding] = {}
        for supplied in bindings:
            if not isinstance(supplied, ToolBinding):
                raise CatalogError("toolchain contains an invalid binding")
            binding = supplied.copy()
            if binding.tool_id in values:
                raise CatalogError(f"duplicate tool binding: {binding.tool_id}")
            values[binding.tool_id] = binding
        self._bindings = MappingProxyType(values)

    def snapshot(self) -> "Toolchain":
        current = self._bindings
        return Toolchain(tuple(current[key] for key in sorted(current)))

    def resolve(self, tool_id: str) -> ToolBinding:
        if not isinstance(tool_id, str) or _ID.fullmatch(tool_id) is None:
            raise CatalogError("invalid tool binding id")
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
        return _sha256(self.canonical_json().encode())


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
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(
            self.task_id
        ) is None or self.repository != "Ternedal/ModelRig":
            raise CatalogError("isolation attestation identity is invalid")
        if not isinstance(self.base_sha, str) or _HEX40.fullmatch(self.base_sha) is None:
            raise CatalogError("attestation base SHA is invalid")
        for name in ("task_sha256", "catalog_sha256", "toolchain_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                raise CatalogError(f"{name} is invalid")
        if not isinstance(self.boundary, IsolationBoundary) or not isinstance(
            self.network_mode, NetworkMode
        ):
            raise CatalogError("isolation policy is invalid")
        if (
            not isinstance(self.evidence_sha256, tuple)
            or not 1 <= len(self.evidence_sha256) <= 32
            or len(set(self.evidence_sha256)) != len(self.evidence_sha256)
            or any(not isinstance(item, str) or _HEX64.fullmatch(item) is None for item in self.evidence_sha256)
        ):
            raise CatalogError("isolation evidence must be 1..32 unique SHA-256 hashes")

    @classmethod
    def from_mapping(cls, value: Any) -> "IsolationAttestation":
        fields = {
            "schema", "task_id", "task_sha256", "repository", "base_sha",
            "catalog_sha256", "toolchain_sha256", "boundary", "network_mode",
            "evidence_sha256",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise CatalogError("isolation attestation fields mismatch")
        evidence = value["evidence_sha256"]
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise CatalogError("isolation evidence must be a string array")
        try:
            return cls(
                **{key: value[key] for key in fields - {"boundary", "network_mode", "evidence_sha256"}},
                boundary=IsolationBoundary(value["boundary"]),
                network_mode=NetworkMode(value["network_mode"]),
                evidence_sha256=tuple(evidence),
            )
        except (TypeError, ValueError) as exc:
            raise CatalogError("isolation attestation fields are invalid") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "task_id": self.task_id,
            "task_sha256": self.task_sha256, "repository": self.repository,
            "base_sha": self.base_sha, "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "boundary": self.boundary.value, "network_mode": self.network_mode.value,
            "evidence_sha256": list(self.evidence_sha256),
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class IsolationVerifier(Protocol):
    def verify(self, attestation: IsolationAttestation) -> None: ...


class ExecutableVerifier(Protocol):
    def verify(self, binding: ToolBinding) -> str: ...


class RejectUnverifiedIsolation:
    def verify(self, attestation: IsolationAttestation) -> None:
        del attestation
        raise CatalogError("OS isolation has not been independently verified")


class TaskBoundCommandRegistry(CommandRegistry):
    def __init__(
        self,
        templates: Sequence[CommandTemplate],
        task: DevelopmentTask,
        executable_verifier: ExecutableVerifier,
    ) -> None:
        super().__init__(templates)
        object.__setattr__(self, "_bound_task_identity", self._identity(task))
        object.__setattr__(self, "_catalog_executable_verifier", executable_verifier)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise CommandPolicyError("task-bound command registry is immutable")
        object.__setattr__(self, name, value)

    @staticmethod
    def _identity(task: DevelopmentTask) -> tuple[str, str, str, str]:
        if not isinstance(task, DevelopmentTask):
            raise CommandPolicyError("registry resolution requires a development task")
        try:
            snapshot = DevelopmentTask.from_mapping(task.to_dict())
        except (ContractError, AttributeError, TypeError, ValueError) as exc:
            raise CommandPolicyError("registry resolution task is invalid") from exc
        return (
            snapshot.task_id,
            _task_sha(snapshot),
            snapshot.repository,
            snapshot.base_sha,
        )

    def resolve(self, task: DevelopmentTask, command_id: str) -> CommandTemplate:
        if self._identity(task) != self._bound_task_identity:
            raise CommandPolicyError("command registry is not bound to this exact task")
        return super().resolve(task, command_id)


class LocalExecutableHashVerifier:
    def __init__(self) -> None:
        self._pins: dict[str, tuple[ToolBinding, int, str]] = {}
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self._pins.clear()

    def __del__(self) -> None:
        self.close()

    def verify(self, binding: ToolBinding) -> str:
        if self._closed:
            raise CatalogError("executable verifier is closed")
        if binding.tool_id in self._pins:
            previous, _, invocation = self._pins[binding.tool_id]
            if previous != binding:
                raise CatalogError(f"tool id was rebound after verification: {binding.tool_id}")
            return invocation
        if os.name == "nt" or not sys.platform.startswith("linux") or _fcntl is None:
            raise CatalogError("pinned executable verification requires Linux")
        if not hasattr(os, "memfd_create"):
            raise CatalogError("sealed executable objects are unavailable")
        if len(_RETIRED_DESCRIPTORS) >= _MAX_PINNED_EXECUTABLES:
            raise CatalogError("process executable pin limit was reached")
        path = Path(binding.executable)
        try:
            if _linked(path) or path.resolve(strict=True) != path:
                raise CatalogError(f"tool executable path is linked or non-canonical: {binding.tool_id}")
        except OSError as exc:
            raise CatalogError(f"tool executable cannot be resolved: {binding.tool_id}") from exc
        try:
            source = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
        except OSError as exc:
            raise CatalogError(f"tool executable cannot be opened safely: {binding.tool_id}") from exc
        pinned: int | None = None
        try:
            before = os.fstat(source)
            if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o111 == 0:
                raise CatalogError(f"tool executable is not a regular executable file: {binding.tool_id}")
            if not 0 <= before.st_size <= _MAX_EXECUTABLE_BYTES:
                raise CatalogError(f"tool executable exceeds the verification bound: {binding.tool_id}")
            flags = getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0)
            pinned = os.memfd_create(f"kaliv-{binding.tool_id}", flags=flags)
            digest, total = hashlib.sha256(), 0
            while chunk := os.read(source, 1_048_576):
                total += len(chunk)
                if total > _MAX_EXECUTABLE_BYTES:
                    raise CatalogError(f"tool executable exceeds the verification bound: {binding.tool_id}")
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(pinned, view)
                    if written <= 0:
                        raise CatalogError(f"tool executable could not be pinned: {binding.tool_id}")
                    view = view[written:]
            after = os.fstat(source)
            identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            observed = path.stat(follow_symlinks=False)
            if identity(before) != identity(after) or total != before.st_size:
                raise CatalogError(f"tool executable changed during verification: {binding.tool_id}")
            if not stat.S_ISREG(observed.st_mode) or (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
                raise CatalogError(f"tool executable path changed during verification: {binding.tool_id}")
            if digest.hexdigest() != binding.executable_sha256:
                raise CatalogError(f"tool executable hash mismatch: {binding.tool_id}")
            os.fchmod(pinned, 0o500)
            seals = _fcntl.F_SEAL_SEAL | _fcntl.F_SEAL_SHRINK | _fcntl.F_SEAL_GROW | _fcntl.F_SEAL_WRITE
            _fcntl.fcntl(pinned, _fcntl.F_ADD_SEALS, seals)
            invocation = f"/proc/{os.getpid()}/fd/{pinned}"
            if Path(invocation).stat().st_size != total or os.fstat(pinned).st_size != total:
                raise CatalogError(f"pinned executable size could not be verified: {binding.tool_id}")
            _RETIRED_DESCRIPTORS.add(pinned)
            self._pins[binding.tool_id] = (binding, pinned, invocation)
            pinned = None
            return invocation
        except CatalogError:
            raise
        except OSError as exc:
            raise CatalogError(f"tool executable could not be verified: {binding.tool_id}") from exc
        finally:
            os.close(source)
            if pinned is not None:
                os.close(pinned)


class CatalogMaterializer:
    def __init__(
        self, catalog: ModelRigCommandCatalog, *,
        isolation_verifier: IsolationVerifier | None = None,
        executable_verifier: ExecutableVerifier | None = None,
    ) -> None:
        if not isinstance(catalog, ModelRigCommandCatalog):
            raise CatalogError("materializer requires a ModelRig command catalog")
        self.catalog = catalog
        self.isolation_verifier = isolation_verifier or RejectUnverifiedIsolation()
        self.executable_verifier = executable_verifier or LocalExecutableHashVerifier()

    def materialize(
        self, task: DevelopmentTask, toolchain: Toolchain,
        attestation: IsolationAttestation,
    ) -> CommandRegistry:
        if not isinstance(task, DevelopmentTask):
            raise CatalogError("materializer requires a development task")
        if not isinstance(toolchain, Toolchain) or not isinstance(attestation, IsolationAttestation):
            raise CatalogError("materializer authority inputs are invalid")
        try:
            task_snapshot = DevelopmentTask.from_mapping(task.to_dict())
        except (ContractError, AttributeError, TypeError, ValueError) as exc:
            raise CatalogError("materializer task contract is invalid") from exc
        if task_snapshot.repository != "Ternedal/ModelRig":
            raise CatalogError("ModelRig catalog cannot authorize another repository")
        catalog = self.catalog.snapshot()
        isolation_verifier = self.isolation_verifier
        executable_verifier = self.executable_verifier
        specs = tuple(catalog.resolve(item) for item in task_snapshot.allowed_command_ids)
        snapshot = toolchain.snapshot()
        expected = {
            "task_id": task_snapshot.task_id, "task_sha256": _task_sha(task_snapshot),
            "repository": task_snapshot.repository, "base_sha": task_snapshot.base_sha,
            "catalog_sha256": catalog.sha256,
            "toolchain_sha256": snapshot.sha256,
            "boundary": IsolationBoundary.OS_ISOLATED,
            "network_mode": NetworkMode.DENY,
        }
        try:
            attestation_snapshot = IsolationAttestation.from_mapping(
                attestation.to_dict()
            )
        except (CatalogError, AttributeError, TypeError, ValueError) as exc:
            raise CatalogError("materializer isolation attestation is invalid") from exc

        def authority(proof: IsolationAttestation) -> dict[str, Any]:
            return {
                "task_id": proof.task_id, "task_sha256": proof.task_sha256,
                "repository": proof.repository, "base_sha": proof.base_sha,
                "catalog_sha256": proof.catalog_sha256,
                "toolchain_sha256": proof.toolchain_sha256,
                "boundary": proof.boundary, "network_mode": proof.network_mode,
            }

        if authority(attestation_snapshot) != expected:
            raise CatalogError("isolation attestation is not bound to this exact authority")
        verifier_attestation = IsolationAttestation.from_mapping(
            attestation_snapshot.to_dict()
        )
        verified_canonical = verifier_attestation.canonical_json()
        isolation_verifier.verify(verifier_attestation)
        try:
            verified_snapshot = IsolationAttestation.from_mapping(
                verifier_attestation.to_dict()
            )
        except (CatalogError, AttributeError, TypeError, ValueError) as exc:
            raise CatalogError("isolation verifier mutated the attestation") from exc
        if (
            verified_snapshot.canonical_json() != verified_canonical
            or authority(verified_snapshot) != expected
        ):
            raise CatalogError("isolation verifier mutated the attestation")
        templates, invocations = [], {}
        for spec in specs:
            if spec.required_boundary is not IsolationBoundary.OS_ISOLATED or spec.network_mode is not NetworkMode.DENY:
                raise CatalogError("catalog command weakened isolation")
            binding = snapshot.resolve(spec.tool_id)
            invocation = invocations.get(binding.tool_id)
            if invocation is None:
                invocation = executable_verifier.verify(binding)
                if not isinstance(invocation, str) or not invocation or not _absolute(invocation):
                    raise CatalogError("executable verifier did not return a pinned absolute object")
                invocations[binding.tool_id] = invocation
            templates.append(CommandTemplate(
                command_id=spec.command_id, argv=(invocation, *spec.args), cwd=spec.cwd,
                max_timeout_seconds=spec.max_timeout_seconds, env=spec.env,
            ))
        return TaskBoundCommandRegistry(
            templates, task_snapshot, executable_verifier
        )


def modelrig_command_catalog() -> ModelRigCommandCatalog:
    common = {
        "CI": "1",
        "MODELRIG_DEVCONTROL": "1",
        "PATH": _FIXED_PATH,
    }
    return ModelRigCommandCatalog((
        ProjectCommandSpec("modelrig.version.check", "python", ("scripts/version_tool.py", "check"), ".", 120, common),
        ProjectCommandSpec("modelrig.devcontrol.tests", "python", ("-m", "unittest", "discover", "-s", "../tests", "-p", "test_*.py", "-v"), "devcontrol/src", 900, common),
        ProjectCommandSpec("modelrig.workflow.test-coverage", "python", ("tests/workflow_test_coverage.py",), ".", 3600, common),
        ProjectCommandSpec("modelrig.backend.vet", "go", ("vet", "./..."), "backend", 900, {**common, "GOTOOLCHAIN": "local"}),
        ProjectCommandSpec("modelrig.backend.tests", "go", ("test", "./..."), "backend", 3600, {**common, "GOTOOLCHAIN": "local"}),
    ))
