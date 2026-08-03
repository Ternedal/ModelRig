"""Fresh-evidence Tier-A launch with deterministic bounded output capture.

The reviewed lease/materialization implementation remains byte-identical in the
private ``_tier_a_execution_core`` module. This public module owns the only
runtime execution entry point. It adds the signed task output budget, native
stdout/stderr capture and a canonical execution result without introducing a
second command-selection or process-launch surface.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from . import _tier_a_execution_core as _core
from .catalog import (
    ExecutableVerifier,
    IsolationAttestation,
    IsolationBoundary,
    ModelRigCommandCatalog,
    NetworkMode,
    Toolchain,
)
from .contract import DevelopmentTask
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .tier_a_result import TierAExecutionResult, TierAOutputStream

LEASE_SCHEMA = _core.LEASE_SCHEMA
PLAN_SCHEMA = "kaliv-development-tier-a-launch-plan/v2"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_MAX_OUTPUT_BYTES = 100_000_000

TierAExecutionError = _core.TierAExecutionError
TierAExecutionLease = _core.TierAExecutionLease
LeasedCommandRegistry = _core.LeasedCommandRegistry
LeasedCatalogMaterializer = _core.LeasedCatalogMaterializer
TIER_A_APPLICATION_ENVIRONMENT = _core.TIER_A_APPLICATION_ENVIRONMENT
workspace_root_authority_sha256 = _core.workspace_root_authority_sha256

# Remove the obsolete, non-capturing executor from the loaded private module.
# Lease/materialization classes remain available, but execution authority is
# exposed only by run_verified_tier_a_command below.
for _obsolete_execution_name in (
    "_run_tier_a_launch_plan",
    "run_verified_tier_a_command",
):
    if hasattr(_core, _obsolete_execution_name):
        delattr(_core, _obsolete_execution_name)
del _obsolete_execution_name

# Every source file that can issue, transform, launch or report Tier-A authority
# is part of the physical-evidence code identity. Adding capture/result handling
# deliberately invalidates every older physical report.
_TIER_A_BUNDLE_FILES = (
    "worker/app/__init__.py",
    "worker/app/windows_job.py",
    "worker/app/windows_restricted.py",
    "worker/app/windows_capture.py",
    "worker/app/windows_tier_a.py",
    "devcontrol/src/kaliv_dev_control/__init__.py",
    "devcontrol/src/kaliv_dev_control/catalog.py",
    "devcontrol/src/kaliv_dev_control/commands.py",
    "devcontrol/src/kaliv_dev_control/contract.py",
    "devcontrol/src/kaliv_dev_control/physical_isolation.py",
    "devcontrol/src/kaliv_dev_control/runtime_staging.py",
    "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py",
    "devcontrol/src/kaliv_dev_control/tier_a_result.py",
    "devcontrol/src/kaliv_dev_control/tier_a_execution.py",
    "devcontrol/src/kaliv_dev_control/workspace.py",
)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _task_sha(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def tier_a_toolhost_sha256(control_plane_root: Path) -> str:
    """Hash the complete v3 source chain that can exercise Tier-A authority."""

    root = _core._canonical_directory(
        control_plane_root,
        name="control-plane root",
    )
    digest = hashlib.sha256()
    digest.update(b"kaliv-tier-a-toolhost/v3\0")
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


@dataclass(frozen=True, slots=True)
class TierALaunchPlan:
    task_id: str
    task_sha256: str
    base_sha: str
    command_id: str
    argv: tuple[str, ...]
    cwd: str
    max_timeout_seconds: int
    max_output_bytes: int
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
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or not 1_024 <= self.max_output_bytes <= _MAX_OUTPUT_BYTES
        ):
            raise TierAExecutionError("Tier-A launch output budget is invalid")
        root = _core._canonical_directory(
            Path(self.workspace_root),
            name="workspace root",
        )
        object.__setattr__(self, "workspace_root", os.fspath(root))
        object.__setattr__(
            self,
            "env",
            _core._validated_application_env(self.env),
        )
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
            "max_output_bytes",
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
            max_output_bytes=value["max_output_bytes"],
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
            "max_output_bytes": self.max_output_bytes,
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
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class TierAExecutionTimeout(TierAExecutionError):
    """The Job Object timed out after producing a canonical bounded result."""

    def __init__(self, result: TierAExecutionResult) -> None:
        if not isinstance(result, TierAExecutionResult) or not result.timed_out:
            raise TierAExecutionError("timeout requires a timed-out execution result")
        self.result = result
        super().__init__("Tier-A command exceeded its fixed timeout")


def build_tier_a_launch_plan(
    registry: LeasedCommandRegistry,
    task: DevelopmentTask,
    command_id: str,
    *,
    workspace_root: Path,
    control_plane_root: Path,
) -> TierALaunchPlan:
    """Bind one staged fixed command and its output budget to signed authority."""

    if not isinstance(registry, LeasedCommandRegistry):
        raise TierAExecutionError("Tier-A launch requires a leased command registry")
    template = registry.resolve(task, command_id)
    lease = registry.lease
    root = _core._canonical_directory(workspace_root, name="workspace root")
    control_root = _core._canonical_directory(
        control_plane_root,
        name="control-plane root",
    )
    if workspace_root_authority_sha256(root) != lease.workspace_root_sha256:
        raise TierAExecutionError(
            "workspace root does not match the signed physical isolation report"
        )
    if tier_a_toolhost_sha256(control_root) != lease.toolhost_sha256:
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
    if (
        _core._regular_file_hash(executable, name="Tier-A executable")
        != binding.executable_sha256
    ):
        raise TierAExecutionError(
            "staged Tier-A executable changed after catalog materialization"
        )

    cwd = root if template.cwd == "." else (root / PurePosixPath(template.cwd)).resolve()
    try:
        cwd.relative_to(root)
    except ValueError as exc:
        raise TierAExecutionError("Tier-A command cwd escaped the workspace") from exc
    if not cwd.is_dir() or _core._has_symlink_component(cwd):
        raise TierAExecutionError("Tier-A command cwd is missing or unsafe")
    if cwd != root:
        raise TierAExecutionError(
            "Tier-A launch plans currently require workspace-root cwd"
        )

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
        max_output_bytes=task.budget.max_output_bytes,
        env=_core._validated_application_env(template.env),
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
) -> TierAExecutionResult:
    """Run one fresh plan and return full hashes plus bounded output prefixes."""

    if not isinstance(plan, TierALaunchPlan):
        raise TierAExecutionError("Tier-A runtime requires a validated launch plan")
    if os.name != "nt":
        raise TierAExecutionError("Tier-A launch requires Windows")
    root = _core._canonical_directory(Path(plan.workspace_root), name="workspace root")
    if workspace_root_authority_sha256(root) != plan.workspace_root_sha256:
        raise TierAExecutionError("Tier-A workspace authority changed after planning")
    if tier_a_toolhost_sha256(control_plane_root) != plan.toolhost_sha256:
        raise TierAExecutionError("Tier-A authority code changed after planning")
    executable = Path(plan.argv[0]).resolve()
    if (
        _core._regular_file_hash(executable, name="Tier-A executable")
        != plan.executable_sha256
    ):
        raise TierAExecutionError("Tier-A executable changed after planning")

    try:
        from app.windows_capture import WindowsOutputCapture
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
    capture = WindowsOutputCapture(profile._api, plan.max_output_bytes)
    process = None
    capture_finished = False
    started = time.monotonic()
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
            output_capture=capture,
        )

        timed_out = False
        try:
            returncode = process.wait(timeout=plan.max_timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_attached_job(process)
            try:
                returncode = process.wait(timeout=5)
            except Exception as exc:
                raise TierAExecutionError(
                    "timed-out Tier-A process could not be reaped"
                ) from exc
        else:
            close_attached_job(process)

        process.close()
        process = None
        stdout_native, stderr_native = capture.finish(timeout_seconds=10.0)
        capture_finished = True
        result = TierAExecutionResult.create(
            task_id=plan.task_id,
            task_sha256=plan.task_sha256,
            base_sha=plan.base_sha,
            command_id=plan.command_id,
            plan_sha256=plan.sha256,
            lease_sha256=plan.lease_sha256,
            signed_report_sha256=plan.signed_report_sha256,
            returncode=returncode,
            duration_ms=max(0, int((time.monotonic() - started) * 1_000)),
            timed_out=timed_out,
            max_output_bytes=plan.max_output_bytes,
            stdout=TierAOutputStream.from_capture(stdout_native),
            stderr=TierAOutputStream.from_capture(stderr_native),
        )
        if timed_out:
            raise TierAExecutionTimeout(result)
        return result
    except TierAExecutionTimeout:
        raise
    except Exception as exc:
        if process is not None:
            try:
                terminate_attached_job(process)
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            try:
                process.close()
            except Exception:
                pass
        if not capture_finished:
            capture.abort()
        if isinstance(exc, TierAExecutionError):
            raise
        raise TierAExecutionError("Tier-A command execution failed safely") from exc
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
    trusted_runtime_root: Path,
    workspace_root: Path,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    executable_verifier: ExecutableVerifier | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> TierAExecutionResult:
    """Reverify, stage, plan, capture and report through one public runtime path."""

    registry = LeasedCatalogMaterializer(
        catalog,
        physical_verifier,
        executable_verifier=executable_verifier,
    ).materialize(task, toolchain, attestation)

    # Local import avoids a package initialization cycle. runtime_staging is in
    # the signed v3 authority bundle, so any change still invalidates the lease.
    from .runtime_staging import TrustedRuntimeStager

    stager = TrustedRuntimeStager(trusted_runtime_root, workspace_root)
    staging_receipt = stager.stage(registry, task, command_id)
    staged_registry = stager.bind_for_launch(
        staging_receipt,
        registry,
        task,
        command_id,
    )
    plan = build_tier_a_launch_plan(
        staged_registry,
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
