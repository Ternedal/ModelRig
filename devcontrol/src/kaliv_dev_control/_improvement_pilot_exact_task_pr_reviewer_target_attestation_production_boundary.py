"""Host-pinned production boundary for ADR-DC-067 reviewer target attestation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)

_POSIX_POLICY = Path(
    "/etc/modelrig/devcontrol/review/"
    "rsi-pilot-exact-task-pr-reviewer-target-policy-v1.json"
)
_WINDOWS_POLICY = Path(
    r"C:\Program Files\ModelRig\DevControl\review\rsi-pilot-exact-task-pr-reviewer-target-policy-v1.json"
)


class PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(ValueError):
    """Production reviewer-target policy is unavailable or not host controlled."""


def _canonical_reviewer_policy_path() -> Path:
    if os.name == "posix":
        return _POSIX_POLICY
    if os.name == "nt":
        return _WINDOWS_POLICY
    raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
        "reviewer target policy is unsupported on this platform"
    )


def _load_reviewer_policy_at(
    implementation: Any,
    path: Path,
    *,
    require_host_control: bool = True,
) -> Any:
    try:
        payload = _read_keyring_bytes(
            Path(path),
            require_host_control=require_host_control,
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
            "reviewer target policy could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
            "reviewer target policy is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
            "reviewer target policy must be an object"
        )
    try:
        policy = implementation.PilotExactTaskPrReviewerTargetPolicy.from_mapping(value)
    except Exception as exc:
        raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
            "reviewer target policy is structurally invalid"
        ) from exc
    if payload != policy.canonical_json().encode("utf-8"):
        raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
            "reviewer target policy is not canonical"
        )
    return policy


def _canonical_reviewer_policy(implementation: Any) -> Any:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
            "reviewer target attestation requires an elevated host operator"
        ) from exc
    return _load_reviewer_policy_at(
        implementation,
        _canonical_reviewer_policy_path(),
        require_host_control=True,
    )


def install_pilot_exact_task_pr_reviewer_target_attestation_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError(
            "reviewer target attestation implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_pr_reviewer_target_attestation_boundary_installed"
    if getattr(implementation, marker, False):
        return
    private_attest = implementation._attest_verified_pilot_exact_task_pr_reviewer_target

    def attest_pilot_exact_task_pr_reviewer_target(
        reviewer_handoff_requirements: Any,
    ) -> Any:
        try:
            requirements, _transaction = implementation._require_live_requirements(
                reviewer_handoff_requirements
            )
            policy = _canonical_reviewer_policy(implementation)
        except implementation.PilotExactTaskPrReviewerTargetAttestationError:
            raise
        except Exception as exc:
            raise implementation.PilotExactTaskPrReviewerTargetAttestationError(
                "host-controlled reviewer target authority is unavailable"
            ) from exc
        return private_attest(
            reviewer_handoff_requirements=requirements,
            reviewer_target_policy=policy,
            now_provider=implementation._now_utc_seconds,
        )

    implementation.attest_pilot_exact_task_pr_reviewer_target = (
        attest_pilot_exact_task_pr_reviewer_target
    )
    setattr(implementation, marker, True)


__all__: list[str] = []
