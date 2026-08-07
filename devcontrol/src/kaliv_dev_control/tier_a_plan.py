"""Canonical closure-bound Tier-A launch plan; this module does not execute."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import _tier_a_execution_core as _core
from .catalog import IsolationBoundary, NetworkMode
from .contract import DevelopmentTask
from .runtime_closure_staging import RuntimeClosureStagingReceipt
from .tier_a_authority import (
    PLAN_SCHEMA,
    LeasedCommandRegistry,
    TierAExecutionError,
    _COMMAND_ID,
    _HEX40,
    _HEX64,
    _MAX_OUTPUT_BYTES,
    _TASK_ID,
    _ZERO_SHA256,
    _canonical,
    _has_linkish_component,
    _inside,
    _is_linkish,
    _task_sha,
    _working_directory,
    tier_a_toolhost_sha256,
    working_directory_authority_sha256,
    workspace_root_authority_sha256,
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
    working_directory_sha256: str = ""
    runtime_closure_sha256: str = _ZERO_SHA256
    signed_runtime_closure_sha256: str = _ZERO_SHA256
    runtime_closure_staging_receipt_sha256: str = _ZERO_SHA256
    runtime_closure_verified: bool = False
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
            ("working_directory_sha256", self.working_directory_sha256, _HEX64),
            ("runtime_closure_sha256", self.runtime_closure_sha256, _HEX64),
            (
                "signed_runtime_closure_sha256",
                self.signed_runtime_closure_sha256,
                _HEX64,
            ),
            (
                "runtime_closure_staging_receipt_sha256",
                self.runtime_closure_staging_receipt_sha256,
                _HEX64,
            ),
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
        if not isinstance(self.cwd, str):
            raise TierAExecutionError("Tier-A launch cwd is invalid")
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
        directory_hash = working_directory_authority_sha256(root, self.cwd)
        if directory_hash != self.working_directory_sha256:
            raise TierAExecutionError(
                "Tier-A launch working-directory identity is inconsistent"
            )
        object.__setattr__(
            self,
            "env",
            _core._validated_application_env(self.env),
        )
        if not isinstance(self.runtime_closure_verified, bool):
            raise TierAExecutionError("Tier-A launch runtime closure status is invalid")
        closure_hashes = (
            self.runtime_closure_sha256,
            self.signed_runtime_closure_sha256,
            self.runtime_closure_staging_receipt_sha256,
        )
        if self.runtime_closure_verified:
            if any(value == _ZERO_SHA256 for value in closure_hashes):
                raise TierAExecutionError(
                    "verified Tier-A runtime closure contains an empty identity"
                )
        elif any(value != _ZERO_SHA256 for value in closure_hashes):
            raise TierAExecutionError(
                "unverified Tier-A plan cannot carry runtime closure authority"
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
            "working_directory_sha256",
            "runtime_closure_sha256",
            "signed_runtime_closure_sha256",
            "runtime_closure_staging_receipt_sha256",
            "runtime_closure_verified",
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
            working_directory_sha256=value["working_directory_sha256"],
            runtime_closure_sha256=value["runtime_closure_sha256"],
            signed_runtime_closure_sha256=value[
                "signed_runtime_closure_sha256"
            ],
            runtime_closure_staging_receipt_sha256=value[
                "runtime_closure_staging_receipt_sha256"
            ],
            runtime_closure_verified=value["runtime_closure_verified"],
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
            "working_directory_sha256": self.working_directory_sha256,
            "runtime_closure_sha256": self.runtime_closure_sha256,
            "signed_runtime_closure_sha256": self.signed_runtime_closure_sha256,
            "runtime_closure_staging_receipt_sha256": (
                self.runtime_closure_staging_receipt_sha256
            ),
            "runtime_closure_verified": self.runtime_closure_verified,
            "boundary": self.boundary.value,
            "network_mode": self.network_mode.value,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _closure_plan_fields(
    receipt: Any | None,
    *,
    registry: LeasedCommandRegistry,
    task: DevelopmentTask,
    command_id: str,
    root: Path,
    executable: Path,
    cwd: str,
) -> tuple[str, str, str, bool]:
    if receipt is None:
        return _ZERO_SHA256, _ZERO_SHA256, _ZERO_SHA256, False

    if not isinstance(receipt, RuntimeClosureStagingReceipt):
        raise TierAExecutionError(
            "Tier-A runtime closure requires a validated staging receipt"
        )
    expected = {
        "task_id": task.task_id,
        "task_sha256": _task_sha(task),
        "repository": task.repository,
        "base_sha": task.base_sha,
        "command_id": command_id,
        "catalog_sha256": registry.catalog.sha256,
        "toolchain_sha256": registry.toolchain.sha256,
        "lease_sha256": registry.lease.sha256,
        "workspace_root_sha256": registry.lease.workspace_root_sha256,
        "working_directory": cwd,
    }
    actual = {
        "task_id": receipt.task_id,
        "task_sha256": receipt.task_sha256,
        "repository": receipt.repository,
        "base_sha": receipt.base_sha,
        "command_id": receipt.command_id,
        "catalog_sha256": receipt.catalog_sha256,
        "toolchain_sha256": receipt.toolchain_sha256,
        "lease_sha256": receipt.lease_sha256,
        "workspace_root_sha256": receipt.workspace_root_sha256,
        "working_directory": receipt.working_directory,
    }
    if actual != expected:
        raise TierAExecutionError(
            "Tier-A runtime closure receipt is not bound to this launch"
        )
    expected_entrypoint = executable.relative_to(root).as_posix()
    if receipt.staged_entrypoint_relative_path != expected_entrypoint:
        raise TierAExecutionError(
            "Tier-A runtime closure entrypoint does not match the staged command"
        )
    return (
        receipt.manifest_sha256,
        receipt.signed_manifest_sha256,
        receipt.sha256,
        True,
    )


def build_tier_a_launch_plan(
    registry: LeasedCommandRegistry,
    task: DevelopmentTask,
    command_id: str,
    *,
    workspace_root: Path,
    control_plane_root: Path,
    runtime_closure_receipt: Any | None = None,
) -> TierALaunchPlan:
    """Bind one fixed command, cwd and optional verified closure to authority."""

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
    if _has_linkish_component(executable):
        raise TierAExecutionError("Tier-A executable contains a link or junction")
    executable = executable.resolve()
    if not _inside(executable, root):
        raise TierAExecutionError(
            "Tier-A executable must be staged inside the approved workspace"
        )
    if (
        _core._regular_file_hash(executable, name="Tier-A executable")
        != binding.executable_sha256
    ):
        raise TierAExecutionError(
            "staged Tier-A executable changed after catalog materialization"
        )

    _working_directory(root, template.cwd)
    closure_sha, signed_closure_sha, receipt_sha, closure_verified = (
        _closure_plan_fields(
            runtime_closure_receipt,
            registry=registry,
            task=task,
            command_id=command_id,
            root=root,
            executable=executable,
            cwd=template.cwd,
        )
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
        working_directory_sha256=working_directory_authority_sha256(
            root, template.cwd
        ),
        runtime_closure_sha256=closure_sha,
        signed_runtime_closure_sha256=signed_closure_sha,
        runtime_closure_staging_receipt_sha256=receipt_sha,
        runtime_closure_verified=closure_verified,
        boundary=lease.boundary,
        network_mode=lease.network_mode,
    )


def _verify_staged_runtime_closure(
    plan: TierALaunchPlan,
    receipt: Any,
    root: Path,
) -> None:
    if not isinstance(receipt, RuntimeClosureStagingReceipt):
        raise TierAExecutionError("Tier-A execution requires its closure receipt")
    if receipt.sha256 != plan.runtime_closure_staging_receipt_sha256:
        raise TierAExecutionError("Tier-A runtime closure receipt changed after planning")
    expected = {
        "task_id": plan.task_id,
        "task_sha256": plan.task_sha256,
        "base_sha": plan.base_sha,
        "command_id": plan.command_id,
        "catalog_sha256": plan.catalog_sha256,
        "toolchain_sha256": plan.toolchain_sha256,
        "lease_sha256": plan.lease_sha256,
        "workspace_root_sha256": plan.workspace_root_sha256,
        "manifest_sha256": plan.runtime_closure_sha256,
        "signed_manifest_sha256": plan.signed_runtime_closure_sha256,
        "working_directory": plan.cwd,
    }
    actual = {
        "task_id": receipt.task_id,
        "task_sha256": receipt.task_sha256,
        "base_sha": receipt.base_sha,
        "command_id": receipt.command_id,
        "catalog_sha256": receipt.catalog_sha256,
        "toolchain_sha256": receipt.toolchain_sha256,
        "lease_sha256": receipt.lease_sha256,
        "workspace_root_sha256": receipt.workspace_root_sha256,
        "manifest_sha256": receipt.manifest_sha256,
        "signed_manifest_sha256": receipt.signed_manifest_sha256,
        "working_directory": receipt.working_directory,
    }
    if actual != expected:
        raise TierAExecutionError("Tier-A runtime closure authority changed after planning")
    staged_root = root.joinpath(
        *PurePosixPath(receipt.staged_root_relative_path).parts
    )
    if (
        _has_linkish_component(staged_root)
        or not staged_root.is_dir()
        or not _inside(staged_root.resolve(), root)
    ):
        raise TierAExecutionError("Tier-A runtime closure root is missing or unsafe")
    observed: set[str] = set()
    for path in staged_root.rglob("*"):
        if _is_linkish(path):
            raise TierAExecutionError("Tier-A runtime closure contains a link")
        if path.is_dir():
            continue
        if not path.is_file() or path.stat().st_nlink != 1:
            raise TierAExecutionError(
                "Tier-A runtime closure contains a non-regular entry or hardlink"
            )
        observed.add(path.relative_to(staged_root).as_posix())
    expected_paths = {entry.relative_path for entry in receipt.files}
    if observed != expected_paths:
        raise TierAExecutionError(
            "Tier-A runtime closure contains missing or unmanifested files"
        )
    for entry in receipt.files:
        path = staged_root.joinpath(*PurePosixPath(entry.relative_path).parts)
        if (
            _has_linkish_component(path)
            or not path.is_file()
            or path.stat().st_nlink != 1
        ):
            raise TierAExecutionError("Tier-A runtime closure file is unsafe")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        if size != entry.size_bytes or digest.hexdigest() != entry.sha256:
            raise TierAExecutionError(
                f"Tier-A runtime closure file changed: {entry.relative_path}"
            )
