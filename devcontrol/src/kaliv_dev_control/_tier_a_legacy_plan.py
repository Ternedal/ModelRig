"""Retained v1 Tier-A launch-plan model and deterministic plan construction."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ._tier_a_environment import _validated_application_env
from ._tier_a_lease import (
    TierAExecutionError,
    _HEX40,
    _HEX64,
    _TASK_ID,
    _canonical,
    _sha256,
    _task_sha,
)
from ._tier_a_legacy_toolhost import tier_a_toolhost_sha256
from ._tier_a_materialization import LeasedCommandRegistry
from ._tier_a_path_authority import (
    _canonical_directory,
    _has_symlink_component,
    _regular_file_hash,
    workspace_root_authority_sha256,
)
from .catalog import IsolationBoundary, NetworkMode
from .contract import DevelopmentTask


PLAN_SCHEMA = "kaliv-development-tier-a-launch-plan/v1"
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


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
