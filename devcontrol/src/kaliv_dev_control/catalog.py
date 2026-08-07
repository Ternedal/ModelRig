from __future__ import annotations

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover
    _fcntl = None

import hashlib
import json
import os
import re
import stat
import struct
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
_FIXED_ENV = MappingProxyType({
    "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
    "LC_CTYPE": "C", "TZ": "UTC",
})
_ALLOWED_ENV = {"CI": "1", "MODELRIG_DEVCONTROL": "1", **_FIXED_ENV}
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


def _require_static_elf(fd: int, size: int, tool_id: str) -> None:
    """Reject all externally backed runtimes, not only the sandbox helper."""
    try:
        header = os.pread(fd, 64, 0)
        if len(header) < 52 or header[:4] != b"\x7fELF" or header[6] != 1:
            raise CatalogError(f"executable runtime must be a static ELF object: {tool_id}")
        elf_class, data_encoding = header[4], header[5]
        prefix = "<" if data_encoding == 1 else ">" if data_encoding == 2 else None
        if prefix is None:
            raise CatalogError(f"executable runtime must be a static ELF object: {tool_id}")
        if elf_class == 2:
            offset = struct.unpack_from(prefix + "Q", header, 32)[0]
            entry_size = struct.unpack_from(prefix + "H", header, 54)[0]
            count = struct.unpack_from(prefix + "H", header, 56)[0]
            minimum = 56
        elif elf_class == 1:
            offset = struct.unpack_from(prefix + "I", header, 28)[0]
            entry_size = struct.unpack_from(prefix + "H", header, 42)[0]
            count = struct.unpack_from(prefix + "H", header, 44)[0]
            minimum = 32
        else:
            raise CatalogError(f"executable runtime must be a static ELF object: {tool_id}")
        table_size = entry_size * count
        if not 1 <= count <= 1024 or entry_size < minimum or offset > size or table_size > size - offset:
            raise CatalogError(f"executable runtime has an invalid ELF program table: {tool_id}")
        saw_load = False
        for index in range(count):
            record = os.pread(fd, 4, offset + index * entry_size)
            if len(record) != 4:
                raise CatalogError(f"executable runtime has an incomplete ELF program table: {tool_id}")
            kind = struct.unpack(prefix + "I", record)[0]
            saw_load = saw_load or kind == 1
            if kind in {2, 3}:
                raise CatalogError(f"executable runtime must not depend on a dynamic runtime: {tool_id}")
        if not saw_load:
            raise CatalogError(f"executable runtime lacks a loadable ELF segment: {tool_id}")
    except CatalogError:
        raise
    except (OSError, struct.error, OverflowError) as exc:
        raise CatalogError(f"executable runtime static ELF validation failed: {tool_id}") from exc


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
        if self.tool_id == "python":
            raise CatalogError("Python commands require complete self-contained runtime attestation")
        if self.tool_id == "go":
            raise CatalogError("Go commands require complete helper toolchain attestation")
        if self.tool_id == "sandbox":
            raise CatalogError("sandbox helper cannot be used as a catalog command tool")
        if not isinstance(self.args, tuple) or len(self.args) > 128 or any(
            not isinstance(item, str) or not item or "\0" in item or len(item.encode("utf-8")) > 4096
            for item in self.args
        ):
            raise CatalogError("catalog arguments must be bounded canonical strings")
        if not isinstance(self.cwd, str) or not self.cwd or "\0" in self.cwd:
            raise CatalogError("catalog cwd must be repository-relative")
        if self.cwd != ".":
            parts = self.cwd.split("/")
            if self.cwd.startswith("/") or "\\" in self.cwd or any(part in {"", ".", ".."} for part in parts) or PurePosixPath(self.cwd).as_posix() != self.cwd:
                raise CatalogError("catalog cwd must be canonical and repository-relative")
        if isinstance(self.max_timeout_seconds, bool) or not isinstance(self.max_timeout_seconds, int) or not 1 <= self.max_timeout_seconds <= 86_400:
            raise CatalogError("catalog timeout is outside bounds")
        if not isinstance(self.required_boundary, IsolationBoundary) or not isinstance(self.network_mode, NetworkMode):
            raise CatalogError("catalog isolation policy is invalid")
        if not isinstance(self.env, Mapping):
            raise CatalogError("catalog environment must be an object")
        clean: dict[str, str] = {}
        for key, value in self.env.items():
            if not isinstance(key, str) or not key or key.strip() != key or "=" in key or not isinstance(value, str) or "\0" in key + value or len(key.encode()) > 128 or len(value.encode()) > 4096:
                raise CatalogError("catalog environment is invalid")
            if key not in _ALLOWED_ENV or value != _ALLOWED_ENV[key]:
                raise CatalogError("catalog environment is outside the reviewed isolation positive list")
            clean[key] = value
        for key, value in _FIXED_ENV.items():
            clean.setdefault(key, value)
        object.__setattr__(self, "env", MappingProxyType(clean))

    def copy(self) -> "ProjectCommandSpec":
        return ProjectCommandSpec(self.command_id, self.tool_id, tuple(self.args), self.cwd, self.max_timeout_seconds, dict(self.env), self.required_boundary, self.network_mode)

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
        return ModelRigCommandCatalog(tuple(self._specs[key] for key in sorted(self._specs)))

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
        return {"schema": CATALOG_SCHEMA, "repository": "Ternedal/ModelRig", "commands": [self._specs[key].to_dict() for key in sorted(self._specs)]}

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
        if not isinstance(self.executable, str) or not self.executable or self.executable.strip() != self.executable or "\0" in self.executable or len(self.executable.encode()) > 4096 or not _absolute(self.executable):
            raise CatalogError("tool executable must be a canonical absolute path")
        if not isinstance(self.executable_sha256, str) or _HEX64.fullmatch(self.executable_sha256) is None:
            raise CatalogError("tool executable hash must be lowercase SHA-256")

    def copy(self) -> "ToolBinding":
        return ToolBinding(self.tool_id, self.executable, self.executable_sha256)

    def to_dict(self) -> dict[str, str]:
        return {"tool_id": self.tool_id, "executable": self.executable, "executable_sha256": self.executable_sha256}


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
        return Toolchain(tuple(self._bindings[key] for key in sorted(self._bindings)))

    def resolve(self, tool_id: str) -> ToolBinding:
        if not isinstance(tool_id, str) or _ID.fullmatch(tool_id) is None:
            raise CatalogError("invalid tool binding id")
        try:
            return self._bindings[tool_id]
        except KeyError as exc:
            raise CatalogError(f"required tool is not bound: {tool_id}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"schema": TOOLCHAIN_SCHEMA, "bindings": [self._bindings[key].to_dict() for key in sorted(self._bindings)]}

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
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None or self.repository != "Ternedal/ModelRig":
            raise CatalogError("isolation attestation identity is invalid")
        if not isinstance(self.base_sha, str) or _HEX40.fullmatch(self.base_sha) is None:
            raise CatalogError("attestation base SHA is invalid")
        for name in ("task_sha256", "catalog_sha256", "toolchain_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                raise CatalogError(f"{name} is invalid")
        if not isinstance(self.boundary, IsolationBoundary) or not isinstance(self.network_mode, NetworkMode):
            raise CatalogError("isolation policy is invalid")
        if not isinstance(self.evidence_sha256, tuple) or not 1 <= len(self.evidence_sha256) <= 32 or len(set(self.evidence_sha256)) != len(self.evidence_sha256) or any(not isinstance(item, str) or _HEX64.fullmatch(item) is None for item in self.evidence_sha256):
            raise CatalogError("isolation evidence must be 1..32 unique SHA-256 hashes")

    @classmethod
    def from_mapping(cls, value: Any) -> "IsolationAttestation":
        fields = {"schema", "task_id", "task_sha256", "repository", "base_sha", "catalog_sha256", "toolchain_sha256", "boundary", "network_mode", "evidence_sha256"}
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


class RejectUnverifiedIsolation:
    def verify(self, attestation: IsolationAttestation) -> None:
        del attestation
        raise CatalogError("OS isolation has not been independently verified")


class TaskBoundCommandRegistry(CommandRegistry):
    def __init__(self, templates: Sequence[CommandTemplate], task: DevelopmentTask, executable_verifier: object | None, bootstrap_executable: str | None) -> None:
        materialized = tuple(templates)
        super().__init__(materialized)
        if materialized and (not isinstance(bootstrap_executable, str) or not bootstrap_executable or "\0" in bootstrap_executable or not _absolute(bootstrap_executable)):
            raise CommandPolicyError("task-bound registry bootstrap executable is invalid")
        if not materialized and bootstrap_executable is not None:
            raise CommandPolicyError("empty task-bound registry cannot retain bootstrap authority")
        object.__setattr__(self, "_bound_task_identity", self._identity(task))
        object.__setattr__(self, "_catalog_executable_verifier", executable_verifier)
        object.__setattr__(self, "_bootstrap_executable", bootstrap_executable)
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
        return snapshot.task_id, _task_sha(snapshot), snapshot.repository, snapshot.base_sha

    def execution_task(self, task: DevelopmentTask) -> DevelopmentTask:
        snapshot = super().execution_task(task)
        if self._identity(snapshot) != self._bound_task_identity:
            raise CommandPolicyError("command registry is not bound to this exact task")
        return snapshot

    def sandbox_bootstrap_executable(self, task: DevelopmentTask) -> str:
        if self._identity(task) != self._bound_task_identity:
            raise CommandPolicyError("command registry is not bound to this exact task")
        if self._bootstrap_executable is None:
            raise CommandPolicyError("empty command registry has no launch authority")
        return self._bootstrap_executable

    def sandbox_bootstrap_mode(self, task: DevelopmentTask) -> str:
        if self._identity(task) != self._bound_task_identity:
            raise CommandPolicyError("command registry is not bound to this exact task")
        if self._bootstrap_executable is None:
            raise CommandPolicyError("empty command registry has no launch authority")
        return "static"

    def resolve(self, task: DevelopmentTask, command_id: str) -> CommandTemplate:
        if self._identity(task) != self._bound_task_identity:
            raise CommandPolicyError("command registry is not bound to this exact task")
        return super().resolve(task, command_id)


class LocalExecutableHashVerifier:
    """Pin and seal self-contained static ELF objects only."""
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
        if not hasattr(os, "memfd_create") or not hasattr(os, "pread"):
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
            source = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        except OSError as exc:
            raise CatalogError(f"tool executable cannot be opened safely: {binding.tool_id}") from exc
        pinned: int | None = None
        try:
            before = os.fstat(source)
            if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o111 == 0:
                raise CatalogError(f"tool executable is not a regular executable file: {binding.tool_id}")
            if not 0 < before.st_size <= _MAX_EXECUTABLE_BYTES:
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
            after, observed = os.fstat(source), path.stat(follow_symlinks=False)
            identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            if identity(before) != identity(after) or total != before.st_size:
                raise CatalogError(f"tool executable changed during verification: {binding.tool_id}")
            if not stat.S_ISREG(observed.st_mode) or (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
                raise CatalogError(f"tool executable path changed during verification: {binding.tool_id}")
            if digest.hexdigest() != binding.executable_sha256:
                raise CatalogError(f"tool executable hash mismatch: {binding.tool_id}")
            _require_static_elf(pinned, total, binding.tool_id)
            os.fchmod(pinned, 0o500)
            seals = _fcntl.F_SEAL_SEAL | _fcntl.F_SEAL_SHRINK | _fcntl.F_SEAL_GROW | _fcntl.F_SEAL_WRITE
            _fcntl.fcntl(pinned, _fcntl.F_ADD_SEALS, seals)
            invocation = f"/proc/{os.getpid()}/fd/{pinned}"
            if Path(invocation).stat().st_size != total or os.fstat(pinned).st_size != total:
                raise CatalogError(f"pinned executable size could not be verified: {binding.tool_id}")
            _RETIRED_DESCRIPTORS.add(pinned)
            self._pins[binding.tool_id] = binding, pinned, invocation
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
    __slots__ = ("catalog", "isolation_verifier")

    def __init__(self, catalog: ModelRigCommandCatalog, *, isolation_verifier: IsolationVerifier | None = None, executable_verifier: LocalExecutableHashVerifier | None = None) -> None:
        if not isinstance(catalog, ModelRigCommandCatalog):
            raise CatalogError("materializer requires a ModelRig command catalog")
        if executable_verifier is not None and type(executable_verifier) is not LocalExecutableHashVerifier:
            raise CatalogError("materializer requires the fixed static-runtime executable verifier")
        self.catalog = catalog
        self.isolation_verifier = isolation_verifier or RejectUnverifiedIsolation()

    def materialize(self, task: DevelopmentTask, toolchain: Toolchain, attestation: IsolationAttestation) -> CommandRegistry:
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
        specs = tuple(catalog.resolve(item) for item in task_snapshot.allowed_command_ids)
        snapshot = toolchain.snapshot()
        verifier_type = LocalExecutableHashVerifier
        verifier_init = LocalExecutableHashVerifier.__init__
        verify_impl = LocalExecutableHashVerifier.verify
        expected = {
            "task_id": task_snapshot.task_id, "task_sha256": _task_sha(task_snapshot),
            "repository": task_snapshot.repository, "base_sha": task_snapshot.base_sha,
            "catalog_sha256": catalog.sha256, "toolchain_sha256": snapshot.sha256,
            "boundary": IsolationBoundary.OS_ISOLATED, "network_mode": NetworkMode.DENY,
        }
        try:
            proof = IsolationAttestation.from_mapping(attestation.to_dict())
        except (CatalogError, AttributeError, TypeError, ValueError) as exc:
            raise CatalogError("materializer isolation attestation is invalid") from exc
        authority = lambda item: {
            "task_id": item.task_id, "task_sha256": item.task_sha256,
            "repository": item.repository, "base_sha": item.base_sha,
            "catalog_sha256": item.catalog_sha256, "toolchain_sha256": item.toolchain_sha256,
            "boundary": item.boundary, "network_mode": item.network_mode,
        }
        if authority(proof) != expected:
            raise CatalogError("isolation attestation is not bound to this exact authority")
        verifier_proof = IsolationAttestation.from_mapping(proof.to_dict())
        canonical = verifier_proof.canonical_json()
        self.isolation_verifier.verify(verifier_proof)
        try:
            checked = IsolationAttestation.from_mapping(verifier_proof.to_dict())
        except (CatalogError, AttributeError, TypeError, ValueError) as exc:
            raise CatalogError("isolation verifier mutated the attestation") from exc
        if checked.canonical_json() != canonical or authority(checked) != expected:
            raise CatalogError("isolation verifier mutated the attestation")
        if not specs:
            return TaskBoundCommandRegistry((), task_snapshot, None, None)
        verifier = object.__new__(verifier_type)
        verifier_init(verifier)
        verify_executable = verify_impl.__get__(verifier, verifier_type)
        bootstrap = verify_executable(snapshot.resolve("sandbox"))
        if not isinstance(bootstrap, str) or not _absolute(bootstrap):
            raise CatalogError("executable verifier did not return a pinned sandbox helper")
        templates: list[CommandTemplate] = []
        for spec in specs:
            if spec.required_boundary is not IsolationBoundary.OS_ISOLATED or spec.network_mode is not NetworkMode.DENY:
                raise CatalogError("catalog command weakened isolation")
            invocation = verify_executable(snapshot.resolve(spec.tool_id))
            if not isinstance(invocation, str) or not _absolute(invocation):
                raise CatalogError("executable verifier did not return a pinned static object")
            templates.append(CommandTemplate(spec.command_id, (invocation, *spec.args), spec.cwd, spec.max_timeout_seconds, spec.env))
        return TaskBoundCommandRegistry(templates, task_snapshot, verifier, bootstrap)


def modelrig_command_catalog() -> ModelRigCommandCatalog:
    """DC-L03 exposes no default command IDs or execution authority."""
    return ModelRigCommandCatalog(())
