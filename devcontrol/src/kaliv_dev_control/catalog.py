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
from .commands import CommandRegistry, CommandTemplate
from .contract import DevelopmentTask
CATALOG_SCHEMA = 'kaliv-modelrig-command-catalog/v1'
TOOLCHAIN_SCHEMA = 'kaliv-development-toolchain/v1'
ATTESTATION_SCHEMA = 'kaliv-development-isolation-attestation/v1'
_HEX40 = re.compile('^[0-9a-f]{40}$')
_HEX64 = re.compile('^[0-9a-f]{64}$')
_TOOL_ID = re.compile('^[a-z][a-z0-9_.-]{1,63}$')
_TASK_ID = re.compile('^[A-Z][A-Z0-9_-]{2,63}$')
_FORBIDDEN_ENV_NAMES = {'HOME', 'XDG_CONFIG_HOME', 'TMPDIR', 'PWD', 'PYTHONHOME', 'PYTHONPATH', 'LD_PRELOAD', 'LD_AUDIT'}
_MAX_EXECUTABLE_BYTES = 256000000

class CatalogError(ValueError):
    pass

class IsolationBoundary(StrEnum):
    OS_ISOLATED = 'os_isolated'

class NetworkMode(StrEnum):
    DENY = 'deny'

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _task_sha(task: DevelopmentTask) -> str:
    return _sha256(task.canonical_json().encode('utf-8'))

def _canonical(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def _is_absolute_executable(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()

def _linkish(path: Path) -> bool:
    if path.is_symlink():
        return True
    junction = getattr(path, 'is_junction', None)
    return bool(junction is not None and junction())

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
            raise CatalogError('invalid catalog command id')
        if not isinstance(self.tool_id, str) or _TOOL_ID.fullmatch(self.tool_id) is None:
            raise CatalogError('invalid catalog tool id')
        if not isinstance(self.args, tuple) or any((not isinstance(item, str) or not item or '\x00' in item or (len(item.encode('utf-8')) > 4096) for item in self.args)):
            raise CatalogError('catalog arguments must be bounded canonical strings')
        if len(self.args) > 128:
            raise CatalogError('catalog contains too many command arguments')
        if not isinstance(self.cwd, str) or not self.cwd or '\x00' in self.cwd:
            raise CatalogError('catalog cwd must be repository-relative')
        if self.cwd != '.':
            raw_parts = self.cwd.split('/')
            path = PurePosixPath(self.cwd)
            if self.cwd.startswith('/') or '\\' in self.cwd or any((part in {'', '.', '..'} for part in raw_parts)) or (path.as_posix() != self.cwd):
                raise CatalogError('catalog cwd must be canonical and repository-relative')
        if isinstance(self.max_timeout_seconds, bool) or not isinstance(self.max_timeout_seconds, int) or (not 1 <= self.max_timeout_seconds <= 86400):
            raise CatalogError('catalog timeout is outside bounds')
        if not isinstance(self.required_boundary, IsolationBoundary):
            raise CatalogError('catalog isolation boundary is invalid')
        if not isinstance(self.network_mode, NetworkMode):
            raise CatalogError('catalog network mode is invalid')
        if not isinstance(self.env, Mapping):
            raise CatalogError('catalog environment must be an object')
        clean_env: dict[str, str] = {}
        for key, value in self.env.items():
            if not isinstance(key, str) or not key or key.strip() != key or ('=' in key) or (not isinstance(value, str)) or ('\x00' in key + value) or (len(key.encode('utf-8')) > 128) or (len(value.encode('utf-8')) > 4096):
                raise CatalogError('catalog environment is invalid')
            if key.startswith('GIT_') or key.startswith('DYLD_') or key in _FORBIDDEN_ENV_NAMES:
                raise CatalogError('catalog environment cannot weaken process isolation')
            clean_env[key] = value
        object.__setattr__(self, 'env', MappingProxyType(clean_env))

    def to_dict(self) -> dict[str, Any]:
        return {'command_id': self.command_id, 'tool_id': self.tool_id, 'args': list(self.args), 'cwd': self.cwd, 'max_timeout_seconds': self.max_timeout_seconds, 'env': dict(sorted(self.env.items())), 'required_boundary': self.required_boundary.value, 'network_mode': self.network_mode.value}

class ModelRigCommandCatalog:

    def __init__(self, specs: Sequence[ProjectCommandSpec]) -> None:
        if isinstance(specs, (str, bytes)) or not isinstance(specs, Sequence):
            raise CatalogError('catalog specs must be a sequence')
        values: dict[str, ProjectCommandSpec] = {}
        for spec in specs:
            if not isinstance(spec, ProjectCommandSpec):
                raise CatalogError('catalog contains an invalid command spec')
            if spec.command_id in values:
                raise CatalogError(f'duplicate catalog command: {spec.command_id}')
            values[spec.command_id] = spec
        self._specs = MappingProxyType(values)

    @property
    def command_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def resolve(self, command_id: str) -> ProjectCommandSpec:
        if not isinstance(command_id, str) or _TOOL_ID.fullmatch(command_id) is None:
            raise CatalogError('invalid catalog command id')
        try:
            return self._specs[command_id]
        except KeyError as exc:
            raise CatalogError(f'command is not in the ModelRig catalog: {command_id}') from exc

    def to_dict(self) -> dict[str, Any]:
        return {'schema': CATALOG_SCHEMA, 'repository': 'Ternedal/ModelRig', 'commands': [self._specs[key].to_dict() for key in sorted(self._specs)]}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode('utf-8'))

@dataclass(frozen=True, slots=True)
class ToolBinding:
    tool_id: str
    executable: str
    executable_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.tool_id, str) or _TOOL_ID.fullmatch(self.tool_id) is None:
            raise CatalogError('invalid tool binding id')
        if not isinstance(self.executable, str) or not self.executable or self.executable.strip() != self.executable or ('\x00' in self.executable) or (len(self.executable.encode('utf-8')) > 4096) or (not _is_absolute_executable(self.executable)):
            raise CatalogError('tool executable must be a canonical absolute path')
        if not isinstance(self.executable_sha256, str) or _HEX64.fullmatch(self.executable_sha256) is None:
            raise CatalogError('tool executable hash must be lowercase SHA-256')

    def to_dict(self) -> dict[str, str]:
        return {'tool_id': self.tool_id, 'executable': self.executable, 'executable_sha256': self.executable_sha256}

class Toolchain:

    def __init__(self, bindings: Sequence[ToolBinding]) -> None:
        if isinstance(bindings, (str, bytes)) or not isinstance(bindings, Sequence):
            raise CatalogError('toolchain bindings must be a sequence')
        values: dict[str, ToolBinding] = {}
        for binding in bindings:
            if not isinstance(binding, ToolBinding):
                raise CatalogError('toolchain contains an invalid binding')
            if binding.tool_id in values:
                raise CatalogError(f'duplicate tool binding: {binding.tool_id}')
            values[binding.tool_id] = binding
        self._bindings = MappingProxyType(values)

    def resolve(self, tool_id: str) -> ToolBinding:
        if not isinstance(tool_id, str) or _TOOL_ID.fullmatch(tool_id) is None:
            raise CatalogError('invalid tool binding id')
        try:
            return self._bindings[tool_id]
        except KeyError as exc:
            raise CatalogError(f'required tool is not bound: {tool_id}') from exc

    def to_dict(self) -> dict[str, Any]:
        return {'schema': TOOLCHAIN_SCHEMA, 'bindings': [self._bindings[key].to_dict() for key in sorted(self._bindings)]}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode('utf-8'))

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
            raise CatalogError('unsupported isolation attestation schema')
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None or self.repository != 'Ternedal/ModelRig':
            raise CatalogError('isolation attestation identity is invalid')
        if not isinstance(self.boundary, IsolationBoundary) or not isinstance(self.network_mode, NetworkMode):
            raise CatalogError('isolation boundary or network mode is invalid')
        for name, value, pattern in (('task_sha256', self.task_sha256, _HEX64), ('catalog_sha256', self.catalog_sha256, _HEX64), ('toolchain_sha256', self.toolchain_sha256, _HEX64)):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise CatalogError(f'{name} is invalid')
        if not isinstance(self.base_sha, str) or _HEX40.fullmatch(self.base_sha) is None:
            raise CatalogError('attestation base SHA is invalid')
        if not isinstance(self.evidence_sha256, tuple) or not self.evidence_sha256 or len(self.evidence_sha256) > 32 or any((not isinstance(item, str) or _HEX64.fullmatch(item) is None for item in self.evidence_sha256)):
            raise CatalogError('isolation evidence must be an immutable tuple of 1..32 hashes')
        if len(set(self.evidence_sha256)) != len(self.evidence_sha256):
            raise CatalogError('isolation evidence hashes must be unique')

    @classmethod
    def from_mapping(cls, value: Any) -> 'IsolationAttestation':
        if not isinstance(value, Mapping):
            raise CatalogError('isolation attestation must be an object')
        fields = {'schema', 'task_id', 'task_sha256', 'repository', 'base_sha', 'catalog_sha256', 'toolchain_sha256', 'boundary', 'network_mode', 'evidence_sha256'}
        if set(value) != fields:
            raise CatalogError('isolation attestation fields mismatch')
        evidence = value['evidence_sha256']
        if not isinstance(evidence, list) or any((not isinstance(item, str) for item in evidence)):
            raise CatalogError('isolation evidence must be a string array')
        try:
            boundary = IsolationBoundary(value['boundary'])
            network_mode = NetworkMode(value['network_mode'])
        except (TypeError, ValueError) as exc:
            raise CatalogError('unsupported isolation boundary or network mode') from exc
        try:
            return cls(schema=value['schema'], task_id=value['task_id'], task_sha256=value['task_sha256'], repository=value['repository'], base_sha=value['base_sha'], catalog_sha256=value['catalog_sha256'], toolchain_sha256=value['toolchain_sha256'], boundary=boundary, network_mode=network_mode, evidence_sha256=tuple(evidence))
        except TypeError as exc:
            raise CatalogError('isolation attestation fields are invalid') from exc

    def to_dict(self) -> dict[str, Any]:
        return {'schema': self.schema, 'task_id': self.task_id, 'task_sha256': self.task_sha256, 'repository': self.repository, 'base_sha': self.base_sha, 'catalog_sha256': self.catalog_sha256, 'toolchain_sha256': self.toolchain_sha256, 'boundary': self.boundary.value, 'network_mode': self.network_mode.value, 'evidence_sha256': list(self.evidence_sha256)}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

class IsolationVerifier(Protocol):

    def verify(self, attestation: IsolationAttestation) -> None:
        ...

class ExecutableVerifier(Protocol):

    def verify(self, binding: ToolBinding) -> str:
        ...

class RejectUnverifiedIsolation:

    def verify(self, attestation: IsolationAttestation) -> None:
        del attestation
        raise CatalogError('OS isolation has not been independently verified')

class LocalExecutableHashVerifier:

    def __init__(self) -> None:
        self._pins: dict[str, tuple[ToolBinding, int, str]] = {}

    def close(self) -> None:
        for _, descriptor, _ in tuple(self._pins.values()):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self._pins.clear()

    def __del__(self) -> None:
        self.close()

    def verify(self, binding: ToolBinding) -> str:
        existing = self._pins.get(binding.tool_id)
        if existing is not None:
            previous, _, invocation = existing
            if previous != binding:
                raise CatalogError(f'tool id was rebound after verification: {binding.tool_id}')
            return invocation
        if os.name == 'nt' or not sys.platform.startswith('linux') or _fcntl is None:
            raise CatalogError('pinned executable verification requires Linux')
        if not hasattr(os, 'memfd_create'):
            raise CatalogError('sealed executable objects are unavailable')
        path = Path(binding.executable)
        try:
            if _linkish(path) or path.resolve(strict=True) != path:
                raise CatalogError(f'tool executable path is linked or non-canonical: {binding.tool_id}')
        except OSError as exc:
            raise CatalogError(f'tool executable cannot be resolved: {binding.tool_id}') from exc
        flags = os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
        try:
            source = os.open(path, flags)
        except OSError as exc:
            raise CatalogError(f'tool executable cannot be opened safely: {binding.tool_id}') from exc
        pinned: int | None = None
        try:
            before = os.fstat(source)
            if not stat.S_ISREG(before.st_mode):
                raise CatalogError(f'tool executable is not a regular file: {binding.tool_id}')
            if before.st_size < 0 or before.st_size > _MAX_EXECUTABLE_BYTES:
                raise CatalogError(f'tool executable exceeds the verification bound: {binding.tool_id}')
            if before.st_mode & 0o111 == 0:
                raise CatalogError(f'tool executable is not marked executable: {binding.tool_id}')
            memfd_flags = getattr(os, 'MFD_CLOEXEC', 0) | getattr(os, 'MFD_ALLOW_SEALING', 0)
            pinned = os.memfd_create(f'kaliv-{binding.tool_id}', flags=memfd_flags)
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(source, 1048576)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_EXECUTABLE_BYTES:
                    raise CatalogError(f'tool executable exceeds the verification bound: {binding.tool_id}')
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(pinned, view)
                    if written <= 0:
                        raise CatalogError(f'tool executable could not be pinned: {binding.tool_id}')
                    view = view[written:]
            after = os.fstat(source)
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            if identity_after != identity_before or total != before.st_size:
                raise CatalogError(f'tool executable changed during verification: {binding.tool_id}')
            observed_path = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(observed_path.st_mode) or (observed_path.st_dev, observed_path.st_ino) != (before.st_dev, before.st_ino):
                raise CatalogError(f'tool executable path changed during verification: {binding.tool_id}')
            if digest.hexdigest() != binding.executable_sha256:
                raise CatalogError(f'tool executable hash mismatch: {binding.tool_id}')
            os.fchmod(pinned, 0o500)
            seals = _fcntl.F_SEAL_SEAL | _fcntl.F_SEAL_SHRINK | _fcntl.F_SEAL_GROW | _fcntl.F_SEAL_WRITE
            _fcntl.fcntl(pinned, _fcntl.F_ADD_SEALS, seals)
            invocation = f'/proc/{os.getpid()}/fd/{pinned}'
            pinned_stat = Path(invocation).stat()
            sealed_stat = os.fstat(pinned)
            if pinned_stat.st_size != total or sealed_stat.st_size != total:
                raise CatalogError(f'pinned executable size could not be verified: {binding.tool_id}')
            self._pins[binding.tool_id] = (binding, pinned, invocation)
            pinned = None
            return invocation
        except CatalogError:
            raise
        except OSError as exc:
            raise CatalogError(f'tool executable could not be verified: {binding.tool_id}') from exc
        finally:
            os.close(source)
            if pinned is not None:
                os.close(pinned)

class CatalogMaterializer:

    def __init__(self, catalog: ModelRigCommandCatalog, *, isolation_verifier: IsolationVerifier | None=None, executable_verifier: ExecutableVerifier | None=None) -> None:
        if not isinstance(catalog, ModelRigCommandCatalog):
            raise CatalogError('materializer requires a ModelRig command catalog')
        self.catalog = catalog
        self.isolation_verifier = isolation_verifier or RejectUnverifiedIsolation()
        self.executable_verifier = executable_verifier or LocalExecutableHashVerifier()

    def materialize(self, task: DevelopmentTask, toolchain: Toolchain, attestation: IsolationAttestation) -> CommandRegistry:
        if not isinstance(task, DevelopmentTask):
            raise CatalogError('materializer requires a development task')
        if not isinstance(toolchain, Toolchain) or not isinstance(attestation, IsolationAttestation):
            raise CatalogError('materializer authority inputs are invalid')
        if task.repository != 'Ternedal/ModelRig':
            raise CatalogError('ModelRig catalog cannot authorize another repository')
        selected = tuple((self.catalog.resolve(item) for item in task.allowed_command_ids))
        expected = {'task_id': task.task_id, 'task_sha256': _task_sha(task), 'repository': task.repository, 'base_sha': task.base_sha, 'catalog_sha256': self.catalog.sha256, 'toolchain_sha256': toolchain.sha256, 'boundary': IsolationBoundary.OS_ISOLATED, 'network_mode': NetworkMode.DENY}
        actual = {'task_id': attestation.task_id, 'task_sha256': attestation.task_sha256, 'repository': attestation.repository, 'base_sha': attestation.base_sha, 'catalog_sha256': attestation.catalog_sha256, 'toolchain_sha256': attestation.toolchain_sha256, 'boundary': attestation.boundary, 'network_mode': attestation.network_mode}
        if actual != expected:
            raise CatalogError('isolation attestation is not bound to this exact authority')
        self.isolation_verifier.verify(attestation)
        templates: list[CommandTemplate] = []
        invocation_paths: dict[str, str] = {}
        for spec in selected:
            if spec.required_boundary is not IsolationBoundary.OS_ISOLATED:
                raise CatalogError('catalog boundary weakened unexpectedly')
            if spec.network_mode is not NetworkMode.DENY:
                raise CatalogError('catalog command unexpectedly permits network')
            binding = toolchain.resolve(spec.tool_id)
            invocation = invocation_paths.get(binding.tool_id)
            if invocation is None:
                invocation = self.executable_verifier.verify(binding)
                if not isinstance(invocation, str) or not invocation or not _is_absolute_executable(invocation):
                    raise CatalogError('executable verifier did not return a pinned absolute object')
                invocation_paths[binding.tool_id] = invocation
            templates.append(CommandTemplate(command_id=spec.command_id, argv=(invocation, *spec.args), cwd=spec.cwd, max_timeout_seconds=spec.max_timeout_seconds, env=spec.env))
        registry = CommandRegistry(templates)
        setattr(registry, '_catalog_executable_verifier', self.executable_verifier)
        return registry

def modelrig_command_catalog() -> ModelRigCommandCatalog:
    common = {'CI': '1', 'MODELRIG_DEVCONTROL': '1'}
    return ModelRigCommandCatalog((ProjectCommandSpec('modelrig.version.check', 'python', ('scripts/version_tool.py', 'check'), '.', 120, common), ProjectCommandSpec('modelrig.devcontrol.tests', 'python', ('-m', 'unittest', 'discover', '-s', '../tests', '-p', 'test_*.py', '-v'), 'devcontrol/src', 900, common), ProjectCommandSpec('modelrig.workflow.test-coverage', 'python', ('tests/workflow_test_coverage.py',), '.', 3600, common), ProjectCommandSpec('modelrig.backend.vet', 'go', ('vet', './...'), 'backend', 900, {**common, 'GOTOOLCHAIN': 'local'}), ProjectCommandSpec('modelrig.backend.tests', 'go', ('test', './...'), 'backend', 3600, {**common, 'GOTOOLCHAIN': 'local'})))
