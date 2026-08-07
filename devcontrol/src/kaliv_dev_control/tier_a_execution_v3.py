"""Sole closure-bound Tier-A process execution implementation."""
from __future__ import annotations

import importlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from . import _tier_a_execution_core as _core
from .catalog import (
    IsolationAttestation,
    ModelRigCommandCatalog,
    Toolchain,
)
from .contract import DevelopmentTask
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .runtime_closure import (
    RuntimeClosureVerifier,
    SignedRuntimeClosureManifest,
    TrustedRuntimeClosureStager,
)
from .tier_a_authority import (
    LeasedCatalogMaterializer,
    TierAExecutionError,
    _has_linkish_component,
    tier_a_toolhost_sha256,
    workspace_root_authority_sha256,
)
from .tier_a_plan import (
    TierALaunchPlan,
    _verify_staged_runtime_closure,
    _working_directory,
    build_tier_a_launch_plan,
    working_directory_authority_sha256,
)
from .tier_a_result import TierAExecutionResult, TierAOutputStream

# If native cleanup cannot prove the Job Object was closed, releasing the
# runtime locks would reopen a mutation window while a child may still exist.
# Retain those guards until process shutdown instead of weakening the boundary.
_QUARANTINED_RUNTIME_GUARDS: list[Any] = []


class TierAExecutionTimeout(TierAExecutionError):
    """The Job Object timed out after producing canonical bounded evidence."""

    def __init__(self, result: TierAExecutionResult) -> None:
        if not isinstance(result, TierAExecutionResult) or not result.timed_out:
            raise TierAExecutionError("timeout requires a timed-out execution result")
        self.result = result
        super().__init__("Tier-A command exceeded its fixed timeout")


def _run_tier_a_launch_plan(
    plan: TierALaunchPlan,
    *,
    runtime_closure_receipt: Any,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> TierAExecutionResult:
    """Run one fresh closure-bound plan through the existing Windows substrate."""

    if not isinstance(plan, TierALaunchPlan):
        raise TierAExecutionError("Tier-A runtime requires a validated launch plan")
    if not plan.runtime_closure_verified:
        raise TierAExecutionError(
            "Tier-A runtime refuses a plan without a verified signed closure"
        )
    if os.name != "nt":
        raise TierAExecutionError("Tier-A launch requires Windows")
    root = _core._canonical_directory(Path(plan.workspace_root), name="workspace root")
    if workspace_root_authority_sha256(root) != plan.workspace_root_sha256:
        raise TierAExecutionError("Tier-A workspace authority changed after planning")
    if tier_a_toolhost_sha256(control_plane_root) != plan.toolhost_sha256:
        raise TierAExecutionError("Tier-A authority code changed after planning")
    executable = Path(plan.argv[0])
    if _has_linkish_component(executable):
        raise TierAExecutionError("Tier-A executable became a link after planning")
    executable = executable.resolve()
    if (
        _core._regular_file_hash(executable, name="Tier-A executable")
        != plan.executable_sha256
    ):
        raise TierAExecutionError("Tier-A executable changed after planning")
    working_directory = _working_directory(root, plan.cwd)
    if (
        working_directory_authority_sha256(root, plan.cwd)
        != plan.working_directory_sha256
    ):
        raise TierAExecutionError("Tier-A working directory changed after planning")
    _verify_staged_runtime_closure(plan, runtime_closure_receipt, root)

    try:
        windows_capture = importlib.import_module("app.windows_capture")
        windows_job = importlib.import_module("app.windows_job")
        windows_restricted = importlib.import_module("app.windows_restricted")
        windows_runtime_guard = importlib.import_module("app.windows_runtime_guard")
        windows_tier_a = importlib.import_module("app.windows_tier_a")
    except ImportError as exc:
        raise TierAExecutionError(
            "authoritative worker Tier-A modules are unavailable"
        ) from exc

    policy = windows_restricted.RestrictedLaunchPolicy(os.fspath(root))
    profile = windows_restricted.AppContainerProfile(policy)
    capture = windows_capture.WindowsOutputCapture(
        profile._api,
        plan.max_output_bytes,
        workspace_root=root,
        working_directory=working_directory,
    )
    process = None
    lifetime_guard = None
    capture_finished = False
    job_closed = False
    started = time.monotonic()
    try:
        acl_receipt = windows_restricted.provision_workspace_acl(policy, profile)
        lifetime_guard = windows_runtime_guard.WindowsRuntimeClosureLifetimeGuard.acquire(
            policy,
            profile,
            staged_root_relative_path=(
                runtime_closure_receipt.staged_root_relative_path
            ),
            files=tuple(
                (entry.relative_path, entry.sha256, entry.size_bytes)
                for entry in runtime_closure_receipt.files
            ),
        )
        process = windows_tier_a.spawn_tier_a_in_job(
            plan.argv,
            source_env=os.environ if source_env is None else source_env,
            application_env=plan.env,
            limits=windows_job.JobLimits(
                process_memory_bytes=process_memory_bytes,
                active_process_limit=active_process_limit,
            ),
            policy=policy,
            profile=profile,
            acl_receipt=acl_receipt,
            output_capture=capture,
        )

        timed_out = False
        try:
            returncode = process.wait(timeout=plan.max_timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            if not windows_job.terminate_attached_job(process):
                raise TierAExecutionError(
                    "timed-out Tier-A process lost its Job Object authority"
                )
            job_closed = True
            try:
                returncode = process.wait(timeout=5)
            except Exception as exc:
                raise TierAExecutionError(
                    "timed-out Tier-A process could not be reaped"
                ) from exc
        else:
            if not windows_job.close_attached_job(process):
                raise TierAExecutionError(
                    "completed Tier-A process lost its Job Object authority"
                )
            job_closed = True

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
        cleanup_error: Exception | None = None
        if process is not None:
            if not job_closed:
                try:
                    if not windows_job.terminate_attached_job(process):
                        raise TierAExecutionError(
                            "Tier-A cleanup found no attached Job Object"
                        )
                    job_closed = True
                except Exception as cleanup_exc:
                    cleanup_error = cleanup_exc
            try:
                process.wait(timeout=5)
            except Exception as cleanup_exc:
                if cleanup_error is None:
                    cleanup_error = cleanup_exc
            try:
                process.close()
            except Exception as cleanup_exc:
                if cleanup_error is None:
                    cleanup_error = cleanup_exc
        if not capture_finished:
            capture.abort()
        if lifetime_guard is not None and process is not None and not job_closed:
            _QUARANTINED_RUNTIME_GUARDS.append(lifetime_guard)
            lifetime_guard = None
        if cleanup_error is not None:
            raise TierAExecutionError(
                "Tier-A process tree cleanup failed; runtime locks retained"
            ) from cleanup_error
        if isinstance(exc, TierAExecutionError):
            raise
        raise TierAExecutionError("Tier-A command execution failed safely") from exc
    finally:
        guard_error: Exception | None = None
        if lifetime_guard is not None:
            try:
                lifetime_guard.close()
            except Exception as exc:
                guard_error = exc
        try:
            profile.delete()
        except Exception as exc:
            if guard_error is None:
                guard_error = exc
        if guard_error is not None:
            raise TierAExecutionError(
                "Tier-A lifetime guard cleanup failed"
            ) from guard_error


def run_verified_tier_a_command(
    task: DevelopmentTask,
    catalog: ModelRigCommandCatalog,
    toolchain: Toolchain,
    attestation: IsolationAttestation,
    physical_verifier: WindowsPhysicalIsolationVerifier,
    command_id: str,
    *,
    signed_runtime_closure: Any,
    runtime_closure_verifier: Any,
    trusted_runtime_root: Path,
    workspace_root: Path,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    executable_verifier: Any | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> TierAExecutionResult:
    """Reverify, stage one signed closure, plan and execute through one path."""

    registry = LeasedCatalogMaterializer(
        catalog,
        physical_verifier,
        executable_verifier=executable_verifier,
    ).materialize(task, toolchain, attestation)

    if not isinstance(signed_runtime_closure, SignedRuntimeClosureManifest):
        raise TierAExecutionError("Tier-A runtime requires a signed runtime closure")
    if not isinstance(runtime_closure_verifier, RuntimeClosureVerifier):
        raise TierAExecutionError("Tier-A runtime requires a closure verifier")

    stager = TrustedRuntimeClosureStager(trusted_runtime_root, workspace_root)
    staging_receipt = stager.stage(
        signed_runtime_closure,
        runtime_closure_verifier,
        registry,
        task,
        command_id,
    )
    staged_registry = stager.bind_for_launch(
        staging_receipt,
        signed_runtime_closure,
        runtime_closure_verifier,
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
        runtime_closure_receipt=staging_receipt,
    )
    return _run_tier_a_launch_plan(
        plan,
        runtime_closure_receipt=staging_receipt,
        control_plane_root=control_plane_root,
        source_env=source_env,
        process_memory_bytes=process_memory_bytes,
        active_process_limit=active_process_limit,
    )
