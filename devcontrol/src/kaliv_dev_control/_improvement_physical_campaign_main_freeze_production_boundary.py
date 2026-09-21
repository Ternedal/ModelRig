"""Host-pinned production boundary for ADR-DC-013 continuous-main freeze."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import improvement_physical_reservation as reservation_module
from ._improvement_physical_campaign_main_freeze_watcher import (
    GitMainFreezeWatcher,
    GitMainFreezeWatcherError,
)
from ._improvement_physical_runtime_host_control import (
    PhysicalHostRuntimeError,
    _HostControlledPhysicalGitReader,
    _require_host_controlled_physical_git_runtime,
)
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .trusted_git_runtime_staging import TrustedGitRuntime


class PhysicalCampaignMainFreezeProductionBoundaryError(ValueError):
    """Production continuous-main freeze host state is unavailable or unsafe."""


def _runtime_identity(runtime: TrustedGitRuntime) -> tuple[str, str]:
    manifest = runtime.receipt.manifest
    executable = next(
        item
        for item in manifest.files
        if item.relative_path == manifest.executable_relative_path
    )
    return manifest.sha256, executable.sha256


def _production_observer(
    runtime: TrustedGitRuntime,
    repository_root: Path,
    repository: str,
):
    manifest_sha256, executable_sha256 = _runtime_identity(runtime)

    def observe(observed_at_utc: str):
        current = _require_host_controlled_physical_git_runtime(runtime)
        observation = reservation_module._observe_with_reader(
            reader=_HostControlledPhysicalGitReader(current),
            repository_root=repository_root,
            repository=repository,
            observed_at_utc=observed_at_utc,
            git_runtime_manifest_sha256=manifest_sha256,
            git_executable_sha256=executable_sha256,
        )
        _require_host_controlled_physical_git_runtime(current)
        return observation

    return observe


def install_physical_campaign_main_freeze_production_boundary(implementation: Any) -> None:
    if implementation is None:
        raise PhysicalCampaignMainFreezeProductionBoundaryError(
            "physical campaign main-freeze implementation is unavailable"
        )
    if getattr(implementation, "_production_main_freeze_boundary_installed", False):
        return

    private_begin = implementation._begin_physical_campaign_main_freeze
    private_finalize = implementation._finalize_physical_campaign_main_freeze
    private_abort = implementation._abort_physical_campaign_main_freeze

    def _host_runtime(trusted_git: TrustedGitRuntime) -> TrustedGitRuntime:
        if type(trusted_git) is not TrustedGitRuntime:
            raise implementation.PhysicalCampaignMainFreezeError(
                "continuous main freeze requires exact TrustedGitRuntime"
            )
        try:
            _require_elevated_operator()
            return _require_host_controlled_physical_git_runtime(trusted_git)
        except (PhysicalHostStateError, PhysicalHostRuntimeError) as exc:
            raise implementation.PhysicalCampaignMainFreezeError(
                "host-controlled continuous main-freeze runtime is unavailable"
            ) from exc

    def begin_physical_campaign_main_freeze(
        *,
        trusted_git: TrustedGitRuntime,
        admission: Any,
    ):
        runtime = _host_runtime(trusted_git)
        repository_root = reservation_module._canonical_repository_root()
        manifest_sha256, executable_sha256 = _runtime_identity(runtime)
        try:
            return private_begin(
                admission=admission,
                admission_authenticated=bool(
                    getattr(admission, "transaction_authenticated", False)
                ),
                repository_root=repository_root,
                git_runtime_manifest_sha256=manifest_sha256,
                git_executable_sha256=executable_sha256,
                watcher_factory=GitMainFreezeWatcher,
                observe_main=_production_observer(
                    runtime,
                    repository_root,
                    getattr(admission, "repository", ""),
                ),
                now_provider=reservation_module._now_utc_seconds,
            )
        except GitMainFreezeWatcherError as exc:
            raise implementation.PhysicalCampaignMainFreezeError(
                "host continuous main-freeze watcher is unavailable"
            ) from exc

    def finalize_physical_campaign_main_freeze(
        *,
        trusted_git: TrustedGitRuntime,
        lease: Any,
        execution_proof: Any,
    ):
        runtime = _host_runtime(trusted_git)
        repository_root = reservation_module._canonical_repository_root()
        manifest_sha256, executable_sha256 = _runtime_identity(runtime)
        if (
            getattr(lease, "repository_root_path_sha256", None)
            != reservation_module._path_sha256(repository_root)
            or getattr(lease, "git_runtime_manifest_sha256", None) != manifest_sha256
            or getattr(lease, "git_executable_sha256", None) != executable_sha256
        ):
            try:
                private_abort(lease=lease)
            except Exception:
                pass
            raise implementation.PhysicalCampaignMainFreezeError(
                "continuous main-freeze lease no longer matches host runtime/repository"
            )
        try:
            proof = private_finalize(
                lease=lease,
                execution_proof=execution_proof,
                observe_main=_production_observer(
                    runtime,
                    repository_root,
                    getattr(lease, "repository", ""),
                ),
                now_provider=reservation_module._now_utc_seconds,
            )
            _require_host_controlled_physical_git_runtime(runtime)
            return proof
        except GitMainFreezeWatcherError as exc:
            raise implementation.PhysicalCampaignMainFreezeError(
                "host continuous main-freeze watcher failed closed"
            ) from exc

    def abort_physical_campaign_main_freeze(*, lease: Any) -> None:
        private_abort(lease=lease)

    implementation.begin_physical_campaign_main_freeze = (
        begin_physical_campaign_main_freeze
    )
    implementation.finalize_physical_campaign_main_freeze = (
        finalize_physical_campaign_main_freeze
    )
    implementation.abort_physical_campaign_main_freeze = (
        abort_physical_campaign_main_freeze
    )
    implementation._production_main_freeze_boundary_installed = True


__all__: list[str] = []
