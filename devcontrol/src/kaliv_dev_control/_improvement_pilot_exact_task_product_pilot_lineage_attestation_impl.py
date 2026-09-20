"""ADR-DC-098 inert end-to-end DC-L16 product-pilot lineage attestation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

from ._improvement_pilot_start_consumption_impl import PilotStartConsumptionReceipt
from ._improvement_pilot_exact_task_execution_admission_impl import (
    PilotExactTaskExecutionAdmissionReceipt,
)
from .improvement_pilot_exact_task_staging_runtime_build_identity import (
    PilotExactTaskStagingRuntimeBuildIdentityReceipt,
)
from .improvement_pilot_exact_task_production_activation_readiness import (
    PilotExactTaskProductionActivationReadinessReceipt,
)
from .improvement_pilot_exact_task_post_production_activation_attestation import (
    PilotExactTaskPostProductionActivationAttestationReceipt,
)

PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-lineage-attestation/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY = (
    "verified-dc-l16-exact-task-product-pilot-lineage-attestation-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE = (
    "historical-authority-to-live-production-candidate-lineage-only-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskProductPilotLineageAttestationError(ValueError):
    """Lineage evidence is malformed, mismatched or over-authorizing."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "lineage attestation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"{name} is invalid"
        )
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _replay(value: Any, cls: type, *, name: str) -> Any:
    if type(value) is not cls:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"exact {name} is required"
        )
    try:
        replayed = cls.from_mapping(value.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"{name} replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskProductPilotLineageAttestationError(
            f"{name} replay identity mismatch"
        )
    return value


def _historical_chain(
    receipt: PilotExactTaskExecutionAdmissionReceipt,
) -> dict[str, Any]:
    exact = _replay(
        receipt,
        PilotExactTaskExecutionAdmissionReceipt,
        name="ADR-DC-033 execution-admission receipt",
    )
    try:
        revalidation = exact.revalidation_attestation_proof
        execution_authorization = (
            revalidation.attestation.packet.execution_authorization_proof
        )
        execution_requirements = execution_authorization.authorization.execution_requirements
        admission = execution_requirements.admission_attestation_proof
        start_receipt = (
            admission.attestation.packet.admission_requirements.start_receipt
        )
        start_authorization = start_receipt.authorization_proof
        preflight = start_authorization.authorization.preflight_proof
        selection = preflight.attestation.packet.selection_proof
        candidate = selection.selection.candidate_proof
    except AttributeError as exc:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "nested DC-L16 historical authority chain is incomplete"
        ) from exc
    return {
        "revalidation": revalidation,
        "execution_authorization": execution_authorization,
        "admission": admission,
        "start_receipt": start_receipt,
        "start_authorization": start_authorization,
        "preflight": preflight,
        "selection": selection,
        "candidate": candidate,
    }


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotLineageAttestationReceipt:
    human_decision_proof_sha256: str
    human_selection_proof_sha256: str
    preflight_proof_sha256: str
    start_receipt_sha256: str
    execution_revalidation_proof_sha256: str
    execution_admission_receipt_sha256: str
    execution_nonce_sha256: str
    staging_runtime_build_identity_sha256: str
    production_activation_readiness_sha256: str
    production_activation_candidate_sha256: str
    post_production_activation_attestation_sha256: str
    repository: str
    merge_commit_sha: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    attested_at_utc: str
    historical_human_go_verified: bool = True
    historical_human_selection_verified: bool = True
    historical_preflight_verified: bool = True
    durable_start_consumption_verified: bool = True
    historical_execution_revalidation_verified: bool = True
    durable_execution_admission_verified: bool = True
    execution_nonce_runtime_binding_verified: bool = True
    runtime_production_candidate_binding_verified: bool = True
    live_post_production_activation_verified: bool = True
    product_pilot_start_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    attestation_scope: str = (
        PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE
    )
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY
            or self.attestation_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskProductPilotLineageAttestationError(
                "lineage attestation identity is unsupported"
            )
        for name in (
            "human_decision_proof_sha256",
            "human_selection_proof_sha256",
            "preflight_proof_sha256",
            "start_receipt_sha256",
            "execution_revalidation_proof_sha256",
            "execution_admission_receipt_sha256",
            "execution_nonce_sha256",
            "staging_runtime_build_identity_sha256",
            "production_activation_readiness_sha256",
            "production_activation_candidate_sha256",
            "post_production_activation_attestation_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskProductPilotLineageAttestationError(
                "lineage repository is unsupported"
            )
        for name in (
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
        ):
            _identifier(getattr(self, name), name=name)
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
            or len(self.product_route.encode("utf-8")) > 512
        ):
            raise PilotExactTaskProductPilotLineageAttestationError(
                "product_route is invalid"
            )
        _utc(self.attested_at_utc, name="attested_at_utc")

        required_true = (
            "historical_human_go_verified",
            "historical_human_selection_verified",
            "historical_preflight_verified",
            "durable_start_consumption_verified",
            "historical_execution_revalidation_verified",
            "durable_execution_admission_verified",
            "execution_nonce_runtime_binding_verified",
            "runtime_production_candidate_binding_verified",
            "live_post_production_activation_verified",
        )
        forced_false = (
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotLineageAttestationError(
                "lineage attestation lacks required evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotLineageAttestationError(
                "lineage attestation grants forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskProductPilotLineageAttestationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)
        ):
            raise PilotExactTaskProductPilotLineageAttestationError(
                "lineage attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_product_pilot_lineage(
    *,
    verified_human_decision_proof_sha256: str,
    verified_human_selection_proof_sha256: str,
    verified_preflight_proof_sha256: str,
    durable_start_receipt: PilotStartConsumptionReceipt,
    verified_execution_revalidation_proof_sha256: str,
    durable_execution_admission_receipt: PilotExactTaskExecutionAdmissionReceipt,
    staging_runtime_build_identity: PilotExactTaskStagingRuntimeBuildIdentityReceipt,
    production_activation_readiness: PilotExactTaskProductionActivationReadinessReceipt,
    post_production_activation_attestation: (
        PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    now_provider,
) -> PilotExactTaskProductPilotLineageAttestationReceipt:
    human_decision_sha = _hex64(
        verified_human_decision_proof_sha256,
        name="verified_human_decision_proof_sha256",
    )
    human_selection_sha = _hex64(
        verified_human_selection_proof_sha256,
        name="verified_human_selection_proof_sha256",
    )
    preflight_sha = _hex64(
        verified_preflight_proof_sha256,
        name="verified_preflight_proof_sha256",
    )
    execution_revalidation_sha = _hex64(
        verified_execution_revalidation_proof_sha256,
        name="verified_execution_revalidation_proof_sha256",
    )

    start_receipt = _replay(
        durable_start_receipt,
        PilotStartConsumptionReceipt,
        name="ADR-DC-025 start-consumption receipt",
    )
    execution_receipt = _replay(
        durable_execution_admission_receipt,
        PilotExactTaskExecutionAdmissionReceipt,
        name="ADR-DC-033 execution-admission receipt",
    )
    runtime = _replay(
        staging_runtime_build_identity,
        PilotExactTaskStagingRuntimeBuildIdentityReceipt,
        name="ADR-DC-084 staging runtime build identity",
    )
    readiness = _replay(
        production_activation_readiness,
        PilotExactTaskProductionActivationReadinessReceipt,
        name="ADR-DC-091 production-activation readiness",
    )
    post_production = _replay(
        post_production_activation_attestation,
        PilotExactTaskPostProductionActivationAttestationReceipt,
        name="ADR-DC-095 post-production activation attestation",
    )
    if post_production.attestation_authenticated is not True:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "fresh live ADR-DC-095 post-production attestation is required"
        )

    chain = _historical_chain(execution_receipt)
    nested_start = chain["start_receipt"]
    preflight = chain["preflight"]
    selection = chain["selection"]
    candidate = chain["candidate"]
    revalidation = chain["revalidation"]

    if nested_start.sha256 != start_receipt.sha256:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "durable ADR-DC-025 receipt does not match ADR-DC-033 lineage"
        )
    if execution_receipt.start_receipt_sha256 != start_receipt.sha256:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "ADR-DC-033 start receipt digest mismatch"
        )
    if revalidation.sha256 != execution_revalidation_sha:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "verified ADR-DC-032 proof does not match ADR-DC-033 lineage"
        )
    if preflight.sha256 != preflight_sha:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "verified ADR-DC-023 proof does not match start lineage"
        )
    if selection.sha256 != human_selection_sha:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "verified ADR-DC-021 proof does not match preflight lineage"
        )
    if candidate.decision_proof_sha256 != human_decision_sha:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "verified ADR-DC-015 proof does not match selected candidate"
        )

    if (
        execution_receipt.execution_nonce_sha256
        != runtime.execution_nonce_sha256
    ):
        raise PilotExactTaskProductPilotLineageAttestationError(
            "ADR-DC-033 execution nonce does not match ADR-DC-084 runtime"
        )
    if readiness.staging_runtime_build_identity_sha256 != runtime.sha256:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "ADR-DC-091 candidate is not bound to supplied ADR-DC-084 runtime"
        )
    if (
        post_production.production_activation_candidate_sha256
        != readiness.production_activation_candidate_sha256
    ):
        raise PilotExactTaskProductPilotLineageAttestationError(
            "live ADR-DC-095 activation does not match ADR-DC-091 candidate"
        )

    authorization = start_receipt.authorization_proof.authorization
    expected_scope = {
        "repository": candidate.repository,
        "operator_surface": candidate.operator_surface,
        "selected_pilot_task_id": candidate.selected_pilot_task_id,
        "workspace_root_path_sha256": candidate.workspace_root_path_sha256,
    }
    for name, item in expected_scope.items():
        if getattr(authorization, name) != item:
            raise PilotExactTaskProductPilotLineageAttestationError(
                f"start authorization scope mismatch: {name}"
            )
    if (
        execution_receipt.selected_pilot_task_id
        != candidate.selected_pilot_task_id
        or execution_receipt.workspace_root_path_sha256
        != candidate.workspace_root_path_sha256
    ):
        raise PilotExactTaskProductPilotLineageAttestationError(
            "execution-admission scope does not match selected DC-L16 candidate"
        )

    if any(
        value != candidate.repository
        for value in (
            runtime.repository,
            readiness.repository,
            post_production.repository,
        )
    ):
        raise PilotExactTaskProductPilotLineageAttestationError(
            "repository identity drifted across execution/runtime/production"
        )
    if any(
        value != runtime.merge_commit_sha
        for value in (
            readiness.merge_commit_sha,
            post_production.merge_commit_sha,
        )
    ):
        raise PilotExactTaskProductPilotLineageAttestationError(
            "merge commit identity drifted across runtime/production"
        )
    if (
        runtime.verification_authenticated is not True
        or readiness.evaluation_authenticated is not True
        or readiness.production_activation_ready is not True
        or runtime.staging_runtime_build_identity_verified is not True
        or post_production.production_activation is not True
        or post_production.production_activation_attested is not True
        or post_production.product_pilot_started is not False
    ):
        raise PilotExactTaskProductPilotLineageAttestationError(
            "production lineage is not inert verified activated-state evidence"
        )

    attested_at = now_provider()
    attested = _utc(attested_at, name="attested_at_utc")
    production_observed = _utc(
        post_production.second_observed_at_utc,
        name="post-production second_observed_at_utc",
    )
    if attested < production_observed:
        raise PilotExactTaskProductPilotLineageAttestationError(
            "lineage attestation predates post-production observation"
        )

    return PilotExactTaskProductPilotLineageAttestationReceipt(
        human_decision_proof_sha256=human_decision_sha,
        human_selection_proof_sha256=human_selection_sha,
        preflight_proof_sha256=preflight_sha,
        start_receipt_sha256=start_receipt.sha256,
        execution_revalidation_proof_sha256=execution_revalidation_sha,
        execution_admission_receipt_sha256=execution_receipt.sha256,
        execution_nonce_sha256=execution_receipt.execution_nonce_sha256,
        staging_runtime_build_identity_sha256=runtime.sha256,
        production_activation_readiness_sha256=readiness.sha256,
        production_activation_candidate_sha256=(
            readiness.production_activation_candidate_sha256
        ),
        post_production_activation_attestation_sha256=post_production.sha256,
        repository=runtime.repository,
        merge_commit_sha=runtime.merge_commit_sha,
        operator_surface=candidate.operator_surface,
        selected_pilot_task_id=candidate.selected_pilot_task_id,
        workspace_root_path_sha256=candidate.workspace_root_path_sha256,
        feature_flag_name=candidate.feature_flag_name,
        product_route=candidate.product_route,
        attested_at_utc=attested_at,
    )


def attest_pilot_exact_task_product_pilot_lineage(**kwargs):
    """Production facade replaces this compatibility surface at import time."""
    del kwargs
    raise PilotExactTaskProductPilotLineageAttestationError(
        "product-pilot lineage attestation is unavailable outside production facade"
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE",
    "PilotExactTaskProductPilotLineageAttestationError",
    "PilotExactTaskProductPilotLineageAttestationReceipt",
    "attest_pilot_exact_task_product_pilot_lineage",
]
