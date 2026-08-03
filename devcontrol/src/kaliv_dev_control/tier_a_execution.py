"""Lease-bound bridge from signed physical evidence to dormant Tier-A launch.

This module connects the development command catalog to the Windows AppContainer
substrate without activating any registered ModelRig tool. A command receives a
launch plan only after the exact signed physical report is reloaded, verified,
bound to the task, catalog and toolchain, and converted into an immutable lease.

The only public execution entry point repeats that verification immediately
before launch. The lower-level plan executor is private so ordinary runtime code
cannot turn a merely well-formed plan into authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from .catalog import (
    CatalogError,
    CatalogMaterializer,
    ExecutableVerifier,
    IsolationAttestation,
    IsolationBoundary,
    ModelRigCommandCatalog,
    NetworkMode,
    Toolchain,
)
from .commands import CommandRegistry, CommandTemplate
from .contract import DevelopmentTask
from .physical_isolation import (
    SignedWindowsIsolationReport,
    WindowsPhysicalIsolationVerifier,
)

LEASE_SCHEMA = "kaliv-development-execution-lease/v1"
PLAN_SCHEMA = "kaliv-development-tier-a-launch-plan/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")

TIER_A_APPLICATION_ENVIRONMENT = MappingProxyType(
    {
        "CI": "1",
        "MODELRIG_DEVCONTROL": "1",
        "GOTOOLCHAIN": "local",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)

# Every Python source file that can create, validate, transform or execute a
# Tier-A authority is part of the signed code identity. Package __init__ files
# are included because Python executes them while importing these modules.
_TIER_A_BUNDLE_FILES = (
    "worker/app/__init__.py",
    "worker/app/windows_job.py",
    "worker/app/windows_restricted.py",
    "worker/app/windows_tier_a.py",
    "devcontrol/src/kaliv_dev_control/__init__.py",
    "devcontrol/src/kaliv_dev_control/catalog.py",
    "devcontrol/src/kaliv_dev_control/commands.py",
    "devcontrol/src/kaliv_dev_control/contract.py",
    "devcontrol/src/kaliv_dev_control/physical_isolation.py",
    "devcontrol/src/kaliv_dev_control/tier_a_execution.py",
    "devcontrol/src/kaliv_dev_control/workspace.py",
)


class TierAExecutionError(CatalogError):
    """A signed authority could not be converted into a safe Tier-A launch."""


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


def _has_symlink_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _canonical_directory(path: Path, *, name: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise TierAExecutionError(f"{name} must be absolute")
    if _has_symlink_component(raw):
        raise TierAExecutionError(f"{name} must not contain symlinks")
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise TierAExecutionError(f"{name} must be an existing directory")
    return resolved


def workspace_root_authority_sha256(path: Path) -> str:
    """Hash the exact canonical workspace path used by the physical campaign."""

    root = _canonical_directory(path, name="workspace root")
    canonical = os.path.normcase(os.fspath(root))
    return _sha256(
        b"kaliv-tier-a-workspace/v1\0"
        + canonical.encode("utf-8", "surrogatepass")
    )


def tier_a_toolhost_sha256(control_plane_root: Path) -> str:
    """Hash the complete source chain that can issue or execute Tier-A authority."""

    root = _canonical_directory(control_plane_root, name="control-plane root")
    digest = hashlib.sha256()
    digest.update(b"kaliv-tier-a-toolhost/v2\0")
    for relative in _TIER_A_BUNDLE_FILES:
        path = root / PurePosixPath(relative)
        if path.is_symlink() or not path.is_file():
            raise TierAExecutionError(
                f"Tier-A toolhost bundle file is missing or unsafe: {relative}"
            )
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _validated_application_env(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TierAExecutionError("Tier-A application environment must be a mapping")
    clean: dict[str, str] = {}
    seen: set[str] = set()
    allowed = {
        key.casefold(): (key, expected)
        for key, expected in TIER_A_APPLICATION_ENVIRONMENT.items()
    }
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\0" in key
            or not isinstance(item, str)
            or "\0" in item
        ):
            raise TierAExecutionError("Tier-A application environment is invalid")
        folded = key.casefold()
        if folded in seen:
            raise TierAExecutionError(
                f"Tier-A application environment contains a duplicate key: {key}"
            )
        seen.add(folded)
        try:
            canonical_key, expected = allowed[folded]
        except KeyError as exc:
            raise TierAExecutionError(
                f"Tier-A application environment key is not reviewed: {key}"
            ) from exc
        if item != expected:
            raise TierAExecutionError(
                f"Tier-A application environment value is not reviewed: {canonical_key}"
            )
        clean[canonical_key] = item
    return MappingProxyType(dict(sorted(clean.items())))


@dataclass(frozen=True, slots=True)
class TierAExecutionLease:
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    catalog_sha256: str
    toolchain_sha256: str
    boundary: IsolationBoundary
    network_mode: NetworkMode
    evidence_sha256: tuple[str, ...]
    signed_report_sha256: str
    report_id: str
    rig_id: str
    rig_fingerprint_sha256: str
    toolhost_sha256: str
    workspace_root_sha256: str
    completed_at: str
    key_id: str
    schema: str = LEASE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != LEASE_SCHEMA:
            raise TierAExecutionError("unsupported execution lease schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise TierAExecutionError("execution lease task id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise TierAExecutionError("execution lease repository is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
            ("signed_report_sha256", self.signed_report_sha256, _HEX64),
            ("rig_fingerprint_sha256", self.rig_fingerprint_sha256, _HEX64),
            ("toolhost_sha256", self.toolhost_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise TierAExecutionError(f"execution lease {name} is invalid")
        if self.boundary is not IsolationBoundary.OS_ISOLATED:
            raise TierAExecutionError("execution lease boundary is not OS isolated")
        if self.network_mode is not NetworkMode.DENY:
            raise TierAExecutionError("execution lease network mode is not deny")
        if (
            not isinstance(self.evidence_sha256, tuple)
            or self.signed_report_sha256 not in self.evidence_sha256
            or any(_HEX64.fullmatch(item) is None for item in self.evidence_sha256)
            or len(set(self.evidence_sha256)) != len(self.evidence_sha256)
        ):
            raise TierAExecutionError("execution lease evidence set is invalid")
        for name, value, maximum in (
            ("report_id", self.report_id, 128),
            ("rig_id", self.rig_id, 128),
            ("completed_at", self.completed_at, 20),
            ("key_id", self.key_id, 128),
        ):
            if (
                not isinstance(value, str)
                or not value
                or value.strip() != value
                or "\0" in value
                or len(value.encode("utf-8")) > maximum
            ):
                raise TierAExecutionError(f"execution lease {name} is invalid")

    @classmethod
    def from_signed_report(
        cls,
        attestation: IsolationAttestation,
        signed: SignedWindowsIsolationReport,
    ) -> "TierAExecutionLease":
        signed.report.bind_to_attestation(attestation)
        return cls(
            task_id=attestation.task_id,
            task_sha256=attestation.task_sha256,
            repository=attestation.repository,
            base_sha=attestation.base_sha,
            catalog_sha256=attestation.catalog_sha256,
            toolchain_sha256=attestation.toolchain_sha256,
            boundary=attestation.boundary,
            network_mode=attestation.network_mode,
            evidence_sha256=attestation.evidence_sha256,
            signed_report_sha256=signed.sha256,
            report_id=signed.report.report_id,
            rig_id=signed.report.rig_id,
            rig_fingerprint_sha256=signed.report.rig_fingerprint_sha256,
            toolhost_sha256=signed.report.toolhost_sha256,
            workspace_root_sha256=signed.report.workspace_root_sha256,
            completed_at=signed.report.completed_at,
            key_id=signed.key_id,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "TierAExecutionLease":
        if not isinstance(value, Mapping):
            raise TierAExecutionError("execution lease must be an object")
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
            "signed_report_sha256",
            "report_id",
            "rig_id",
            "rig_fingerprint_sha256",
            "toolhost_sha256",
            "workspace_root_sha256",
            "completed_at",
            "key_id",
        }
        if set(value) != fields:
            raise TierAExecutionError("execution lease fields mismatch")
        evidence = value["evidence_sha256"]
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) for item in evidence
        ):
            raise TierAExecutionError(
                "execution lease evidence must be a string array"
            )
        try:
            boundary = IsolationBoundary(value["boundary"])
            network_mode = NetworkMode(value["network_mode"])
        except (TypeError, ValueError) as exc:
            raise TierAExecutionError(
                "execution lease isolation mode is invalid"
            ) from exc
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
            signed_report_sha256=value["signed_report_sha256"],
            report_id=value["report_id"],
            rig_id=value["rig_id"],
            rig_fingerprint_sha256=value["rig_fingerprint_sha256"],
            toolhost_sha256=value["toolhost_sha256"],
            workspace_root_sha256=value["workspace_root_sha256"],
            completed_at=value["completed_at"],
            key_id=value["key_id"],
        )

    def verify_attestation(self, attestation: IsolationAttestation) -> None:
        expected = {
            "task_id": attestation.task_id,
            "task_sha256": attestation.task_sha256,
            "repository": attestation.repository,
            "base_sha": attestation.base_sha,
            "catalog_sha256": attestation.catalog_sha256,
            "toolchain_sha256": attestation.toolchain_sha256,
            "boundary": attestation.boundary,
            "network_mode": attestation.network_mode,
            "evidence_sha256": attestation.evidence_sha256,
        }
        actual = {
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "boundary": self.boundary,
            "network_mode": self.network_mode,
            "evidence_sha256": self.evidence_sha256,
        }
        if actual != expected:
            raise TierAExecutionError(
                "execution lease is not bound to the exact isolation attestation"
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
            "signed_report_sha256": self.signed_report_sha256,
            "report_id": self.report_id,
            "rig_id": self.rig_id,
            "rig_fingerprint_sha256": self.rig_fingerprint_sha256,
            "toolhost_sha256": self.toolhost_sha256,
            "workspace_root_sha256": self.workspace_root_sha256,
            "completed_at": self.completed_at,
            "key_id": self.key_id,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))


class _LeaseCapturingVerifier:
    def __init__(self, verifier: WindowsPhysicalIsolationVerifier) -> None:
        if not isinstance(verifier, WindowsPhysicalIsolationVerifier):
            raise TierAExecutionError(
                "leased materialization requires WindowsPhysicalIsolationVerifier"
            )
        self.verifier = verifier
        self._lease: TierAExecutionLease | None = None

    def verify(self, attestation: IsolationAttestation) -> None:
        self._lease = None
        self.verifier.verify(attestation)
        candidates = self.verifier._load_candidates(set(attestation.evidence_sha256))
        if len(candidates) != 1:
            raise TierAExecutionError(
                "physical evidence changed while issuing the execution lease"
            )
        signed = candidates[0]
        if signed.sha256 not in attestation.evidence_sha256:
            raise TierAExecutionError(
                "execution lease report is not named by the attestation"
            )
        self._lease = TierAExecutionLease.from_signed_report(attestation, signed)

    @property
    def lease(self) -> TierAExecutionLease:
        if self._lease is None:
            raise TierAExecutionError("no verified execution lease was issued")
        return self._lease


class LeasedCommandRegistry:
    """A command registry that retains the exact signed execution authority."""

    def __init__(
        self,
        registry: CommandRegistry,
        lease: TierAExecutionLease,
        *,
        task: DevelopmentTask,
        catalog: ModelRigCommandCatalog,
        toolchain: Toolchain,
        attestation: IsolationAttestation,
    ) -> None:
        if not isinstance(registry, CommandRegistry):
            raise TierAExecutionError("leased registry requires a command registry")
        lease.verify_attestation(attestation)
        if (
            lease.task_sha256 != _task_sha(task)
            or lease.catalog_sha256 != catalog.sha256
            or lease.toolchain_sha256 != toolchain.sha256
        ):
            raise TierAExecutionError(
                "leased registry authority does not match task, catalog and toolchain"
            )
        self._registry = registry
        self.lease = lease
        self.catalog = catalog
        self.toolchain = toolchain
        self.attestation = attestation
        self._task_sha256 = _task_sha(task)

    def resolve(self, task: DevelopmentTask, command_id: str) -> CommandTemplate:
        if _task_sha(task) != self._task_sha256:
            raise TierAExecutionError(
                "leased command registry cannot be rebound to another task"
            )
        self.lease.verify_attestation(self.attestation)
        return self._registry.resolve(task, command_id)


class LeasedCatalogMaterializer:
    """Materialize fixed commands and retain the signed physical evidence result."""

    def __init__(
        self,
        catalog: ModelRigCommandCatalog,
        physical_verifier: WindowsPhysicalIsolationVerifier,
        *,
        executable_verifier: ExecutableVerifier | None = None,
    ) -> None:
        self.catalog = catalog
        self._capturing = _LeaseCapturingVerifier(physical_verifier)
        self._materializer = CatalogMaterializer(
            catalog,
            isolation_verifier=self._capturing,
            executable_verifier=executable_verifier,
        )

    def materialize(
        self,
        task: DevelopmentTask,
        toolchain: Toolchain,
        attestation: IsolationAttestation,
    ) -> LeasedCommandRegistry:
        registry = self._materializer.materialize(task, toolchain, attestation)
        return LeasedCommandRegistry(
            registry,
            self._capturing.lease,
            task=task,
            catalog=self.catalog,
            toolchain=toolchain,
            attestation=attestation,
        )


@dataclass(frozen=True, slots=True)
class TierALaunchPlan:
    task_id: str
    task_sha256: str
    base_sha: str
    command_id: str
    argv: tuple[str, ...]
    cwd: str
    max_timeout_seconds: int
    env: Mapping[str, str] = field(default_factory=dict)
    catalog_sha256: str = ""
    toolchain_sha256: str = ""
    lease_sha256: str = ""
    signed_report_sha256: str = ""
    workspace_root: str = ""
    workspace_root_sha256: str = ""
    executable_sha256: str = ""
    toolhost_sha256: str = ""
    boundary: IsolationBoundary = IsolationBoundary.OS_ISOLATED
    network_mode: NetworkMode = NetworkMode.DENY
    schema: str = PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PLAN_SCHEMA:
            raise TierAExecutionError("unsupported Tier-A launch plan schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise TierAExecutionError("Tier-A launch task id is invalid")
        if not isinstance(self.command_id, str) or _COMMAND_ID.fullmatch(self.command_id) is None:
            raise TierAExecutionError("Tier-A launch command id is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
            ("lease_sha256", self.lease_sha256, _HEX64),
            ("signed_report_sha256", self.signed_report_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
            ("executable_sha256", self.executable_sha256, _HEX64),
            ("toolhost_sha256", self.toolhost_sha256, _HEX64),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise TierAExecutionError(f"Tier-A launch {name} is invalid")
        if (
            not isinstance(self.argv, tuple)
            or not self.argv
            or any(
                not isinstance(item, str) or not item or "\0" in item
                for item in self.argv
            )
        ):
            raise TierAExecutionError("Tier-A launch argv is invalid")
        if self.cwd != ".":
            relative = PurePosixPath(self.cwd)
            if (
                self.cwd.startswith("/")
                or "\\" in self.cwd
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise TierAExecutionError("Tier-A launch cwd is invalid")
        if (
            isinstance(self.max_timeout_seconds, bool)
            or not isinstance(self.max_timeout_seconds, int)
            or not 1 <= self.max_timeout_seconds <= 86_400
        ):
            raise TierAExecutionError("Tier-A launch timeout is invalid")
        root = _canonical_directory(Path(self.workspace_root), name="workspace root")
        object.__setattr__(self, "workspace_root", os.fspath(root))
        object.__setattr__(self, "env", _validated_application_env(self.env))
        if self.boundary is not IsolationBoundary.OS_ISOLATED:
            raise TierAExecutionError("Tier-A launch boundary is not OS isolated")
        if self.network_mode is not NetworkMode.DENY:
            raise TierAExecutionError("Tier-A launch network mode is not deny")

    @classmethod
    def from_mapping(cls, value: Any) -> "TierALaunchPlan":
        if not isinstance(value, Mapping):
            raise TierAExecutionError("Tier-A launch plan must be an object")
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "base_sha",
            "command_id",
            "argv",
            "cwd",
            "max_timeout_seconds",
            "env",
            "catalog_sha256",
            "toolchain_sha256",
            "lease_sha256",
            "signed_report_sha256",
            "workspace_root",
            "workspace_root_sha256",
            "executable_sha256",
            "toolhost_sha256",
            "boundary",
            "network_mode",
        }
        if set(value) != fields:
            raise TierAExecutionError("Tier-A launch plan fields mismatch")
        argv = value["argv"]
        env = value["env"]
        if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
            raise TierAExecutionError("Tier-A launch argv must be a string array")
        if not isinstance(env, Mapping):
            raise TierAExecutionError("Tier-A launch env must be an object")
        try:
            boundary = IsolationBoundary(value["boundary"])
            network_mode = NetworkMode(value["network_mode"])
        except (TypeError, ValueError) as exc:
            raise TierAExecutionError("Tier-A launch isolation mode is invalid") from exc
        return cls(
            schema=value["schema"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            base_sha=value["base_sha"],
            command_id=value["command_id"],
            argv=tuple(argv),
            cwd=value["cwd"],
            max_timeout_seconds=value["max_timeout_seconds"],
            env=dict(env),
            catalog_sha256=value["catalog_sha256"],
            toolchain_sha256=value["toolchain_sha256"],
            lease_sha256=value["lease_sha256"],
            signed_report_sha256=value["signed_report_sha256"],
            workspace_root=value["workspace_root"],
            workspace_root_sha256=value["workspace_root_sha256"],
            executable_sha256=value["executable_sha256"],
            toolhost_sha256=value["toolhost_sha256"],
            boundary=boundary,
            network_mode=network_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "command_id": self.command_id,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "max_timeout_seconds": self.max_timeout_seconds,
            "env": dict(sorted(self.env.items())),
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "lease_sha256": self.lease_sha256,
            "signed_report_sha256": self.signed_report_sha256,
            "workspace_root": self.workspace_root,
            "workspace_root_sha256": self.workspace_root_sha256,
            "executable_sha256": self.executable_sha256,
            "toolhost_sha256": self.toolhost_sha256,
            "boundary": self.boundary.value,
            "network_mode": self.network_mode.value,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))


def _regular_file_hash(path: Path, *, name: str) -> str:
    if not path.is_absolute() or _has_symlink_component(path) or not path.is_file():
        raise TierAExecutionError(
            f"{name} must be an absolute regular non-symlink file"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_tier_a_launch_plan(
    registry: LeasedCommandRegistry,
    task: DevelopmentTask,
    command_id: str,
    *,
    workspace_root: Path,
    control_plane_root: Path,
) -> TierALaunchPlan:
    """Bind one fixed materialized command to the physically proven Tier-A root."""

    if not isinstance(registry, LeasedCommandRegistry):
        raise TierAExecutionError("Tier-A launch requires a leased command registry")
    template = registry.resolve(task, command_id)
    lease = registry.lease
    root = _canonical_directory(workspace_root, name="workspace root")
    control_root = _canonical_directory(
        control_plane_root, name="control-plane root"
    )
    actual_workspace_hash = workspace_root_authority_sha256(root)
    if actual_workspace_hash != lease.workspace_root_sha256:
        raise TierAExecutionError(
            "workspace root does not match the signed physical isolation report"
        )
    actual_toolhost_hash = tier_a_toolhost_sha256(control_root)
    if actual_toolhost_hash != lease.toolhost_sha256:
        raise TierAExecutionError(
            "Tier-A authority code does not match the signed physical isolation report"
        )

    specification = registry.catalog.resolve(command_id)
    binding = registry.toolchain.resolve(specification.tool_id)
    executable = Path(template.argv[0])
    if not executable.is_absolute():
        raise TierAExecutionError("Tier-A executable must be absolute")
    executable = executable.resolve()
    try:
        executable.relative_to(root)
    except ValueError as exc:
        raise TierAExecutionError(
            "Tier-A executable must be staged inside the approved workspace"
        ) from exc
    actual_executable_hash = _regular_file_hash(
        executable, name="Tier-A executable"
    )
    if actual_executable_hash != binding.executable_sha256:
        raise TierAExecutionError(
            "staged Tier-A executable changed after catalog materialization"
        )

    cwd = root if template.cwd == "." else (root / PurePosixPath(template.cwd)).resolve()
    try:
        cwd.relative_to(root)
    except ValueError as exc:
        raise TierAExecutionError("Tier-A command cwd escaped the workspace") from exc
    if not cwd.is_dir() or _has_symlink_component(cwd):
        raise TierAExecutionError("Tier-A command cwd is missing or unsafe")
    if cwd != root:
        raise TierAExecutionError(
            "Tier-A launch plans currently require workspace-root cwd"
        )

    environment = _validated_application_env(template.env)
    return TierALaunchPlan(
        task_id=task.task_id,
        task_sha256=_task_sha(task),
        base_sha=task.base_sha,
        command_id=command_id,
        argv=template.argv,
        cwd=template.cwd,
        max_timeout_seconds=min(
            task.budget.max_runtime_seconds,
            template.max_timeout_seconds,
        ),
        env=environment,
        catalog_sha256=lease.catalog_sha256,
        toolchain_sha256=lease.toolchain_sha256,
        lease_sha256=lease.sha256,
        signed_report_sha256=lease.signed_report_sha256,
        workspace_root=os.fspath(root),
        workspace_root_sha256=lease.workspace_root_sha256,
        executable_sha256=binding.executable_sha256,
        toolhost_sha256=lease.toolhost_sha256,
        boundary=lease.boundary,
        network_mode=lease.network_mode,
    )


def _run_tier_a_launch_plan(
    plan: TierALaunchPlan,
    *,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> int:
    """Execute a freshly verified internal plan through AppContainer + Job Object."""

    if not isinstance(plan, TierALaunchPlan):
        raise TierAExecutionError("Tier-A runtime requires a validated launch plan")
    if os.name != "nt":
        raise TierAExecutionError("Tier-A launch requires Windows")
    root = _canonical_directory(Path(plan.workspace_root), name="workspace root")
    if workspace_root_authority_sha256(root) != plan.workspace_root_sha256:
        raise TierAExecutionError("Tier-A workspace authority changed after planning")
    if tier_a_toolhost_sha256(control_plane_root) != plan.toolhost_sha256:
        raise TierAExecutionError("Tier-A authority code changed after planning")
    executable = Path(plan.argv[0]).resolve()
    if _regular_file_hash(
        executable, name="Tier-A executable"
    ) != plan.executable_sha256:
        raise TierAExecutionError("Tier-A executable changed after planning")

    try:
        from app.windows_job import (
            JobLimits,
            close_attached_job,
            terminate_attached_job,
        )
        from app.windows_restricted import (
            AppContainerProfile,
            RestrictedLaunchPolicy,
            provision_workspace_acl,
        )
        from app.windows_tier_a import spawn_tier_a_in_job
    except ImportError as exc:
        raise TierAExecutionError(
            "authoritative worker Tier-A modules are unavailable"
        ) from exc

    policy = RestrictedLaunchPolicy(os.fspath(root))
    profile = AppContainerProfile(policy)
    process = None
    try:
        receipt = provision_workspace_acl(policy, profile)
        process = spawn_tier_a_in_job(
            plan.argv,
            source_env=os.environ if source_env is None else source_env,
            application_env=plan.env,
            limits=JobLimits(
                process_memory_bytes=process_memory_bytes,
                active_process_limit=active_process_limit,
            ),
            policy=policy,
            profile=profile,
            acl_receipt=receipt,
        )
        try:
            return process.wait(timeout=plan.max_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            terminate_attached_job(process)
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            raise TierAExecutionError(
                "Tier-A command exceeded its fixed timeout"
            ) from exc
        finally:
            if process is not None:
                try:
                    close_attached_job(process)
                except Exception:
                    pass
                try:
                    process.close()
                except Exception:
                    pass
    finally:
        profile.delete()


def run_verified_tier_a_command(
    task: DevelopmentTask,
    catalog: ModelRigCommandCatalog,
    toolchain: Toolchain,
    attestation: IsolationAttestation,
    physical_verifier: WindowsPhysicalIsolationVerifier,
    command_id: str,
    *,
    workspace_root: Path,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    executable_verifier: ExecutableVerifier | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> int:
    """Reverify signed authority, build one fresh plan and launch it immediately."""

    registry = LeasedCatalogMaterializer(
        catalog,
        physical_verifier,
        executable_verifier=executable_verifier,
    ).materialize(task, toolchain, attestation)
    plan = build_tier_a_launch_plan(
        registry,
        task,
        command_id,
        workspace_root=workspace_root,
        control_plane_root=control_plane_root,
    )
    return _run_tier_a_launch_plan(
        plan,
        control_plane_root=control_plane_root,
        source_env=source_env,
        process_memory_bytes=process_memory_bytes,
        active_process_limit=active_process_limit,
    )
