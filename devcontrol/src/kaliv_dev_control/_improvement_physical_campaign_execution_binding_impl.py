"""Human/asymmetric exact-runner execution binding for one DC-L15 campaign.

This layer closes only the missing ``exact_runner_execution_binding`` gate from
ADR-DC-011. It verifies a detached Ed25519 signature from the physical operator
over one canonical claim that binds the exact evidence snapshot, campaign,
runner and report identities. The signature is human attestation, not kernel
process telemetry; continuous-main freeze and all terminal authority remain open.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_physical_campaign_evidence import PhysicalCampaignEvidenceSnapshot

EXECUTION_BINDING_SCHEMA = "kaliv-rsi-physical-campaign-execution-binding/v1"
EXECUTION_PROOF_SCHEMA = "kaliv-rsi-physical-campaign-execution-proof/v1"
EXECUTION_BINDING_CLAIM_AUTHORITY = "human-exact-runner-execution-claim-only"
EXECUTION_PROOF_AUTHORITY = "verified-human-exact-runner-execution-binding-only"
EXECUTION_BINDING_ISSUER_SYSTEM_ID = "kaliv-rsi-dc-l15-execution-binding-authority-v1"
REMAINING_COMPLETION_GATES = (
    "continuous_main_freeze_confirmation",
    "dc_l14_independent_human_verdict",
    "human_pilot_go_decision",
)
_MAX_BINDING_DELAY = timedelta(minutes=30)
_MAX_RUNNER_BYTES = 16_000_000
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PhysicalCampaignExecutionBindingError(ValueError):
    """Exact-runner execution evidence is malformed, untrusted or over-authorizing."""


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
        raise PhysicalCampaignExecutionBindingError(
            "physical campaign execution binding is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhysicalCampaignExecutionBindingError(f"{name} fields mismatch")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalCampaignExecutionBindingError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PhysicalCampaignExecutionBindingError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PhysicalCampaignExecutionBindingError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalCampaignExecutionBindingError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PhysicalCampaignExecutionBindingError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


_BINDING_FIELDS = {
    "schema", "binding_id", "evidence_snapshot_sha256", "admission_sha256",
    "campaign_id", "task_id", "task_sha256", "repository", "base_sha",
    "requested_main_sha", "runner_relative_path", "runner_sha256", "runner_bytes",
    "signed_report_sha256", "physical_report_sha256", "report_id",
    "operator_actor_id", "approver_actor_id", "report_started_at_utc",
    "report_completed_at_utc", "execution_started_at_utc",
    "execution_completed_at_utc", "post_main_observed_at_utc",
    "binding_created_at_utc", "exact_campaign_id_confirmed",
    "exact_runner_path_confirmed", "exact_runner_sha256_confirmed",
    "exact_runner_byte_count_confirmed", "exact_report_binding_confirmed",
    "continuous_main_freeze_confirmed", "dc_l14_independent_human_verdict",
    "human_pilot_go_decision", "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignExecutionBinding:
    binding_id: str
    evidence_snapshot_sha256: str
    admission_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    runner_relative_path: str
    runner_sha256: str
    runner_bytes: int
    signed_report_sha256: str
    physical_report_sha256: str
    report_id: str
    operator_actor_id: str
    approver_actor_id: str
    report_started_at_utc: str
    report_completed_at_utc: str
    execution_started_at_utc: str
    execution_completed_at_utc: str
    post_main_observed_at_utc: str
    binding_created_at_utc: str
    exact_campaign_id_confirmed: bool = True
    exact_runner_path_confirmed: bool = True
    exact_runner_sha256_confirmed: bool = True
    exact_runner_byte_count_confirmed: bool = True
    exact_report_binding_confirmed: bool = True
    continuous_main_freeze_confirmed: bool = False
    dc_l14_independent_human_verdict: bool = False
    human_pilot_go_decision: bool = False
    authority: str = EXECUTION_BINDING_CLAIM_AUTHORITY
    schema: str = EXECUTION_BINDING_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EXECUTION_BINDING_SCHEMA:
            raise PhysicalCampaignExecutionBindingError("physical execution binding schema is unsupported")
        _identifier(self.binding_id, name="binding_id")
        _identifier(self.campaign_id, name="campaign_id")
        _identifier(self.report_id, name="report_id")
        for name, value, pattern in (
            ("evidence_snapshot_sha256", self.evidence_snapshot_sha256, _HEX64),
            ("admission_sha256", self.admission_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("runner_sha256", self.runner_sha256, _HEX64),
            ("signed_report_sha256", self.signed_report_sha256, _HEX64),
            ("physical_report_sha256", self.physical_report_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise PhysicalCampaignExecutionBindingError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignExecutionBindingError("repository is unsupported")
        if not isinstance(self.runner_relative_path, str) or not 1 <= len(self.runner_relative_path) <= 512:
            raise PhysicalCampaignExecutionBindingError("runner_relative_path is invalid")
        if isinstance(self.runner_bytes, bool) or not isinstance(self.runner_bytes, int) or not 1 <= self.runner_bytes <= _MAX_RUNNER_BYTES:
            raise PhysicalCampaignExecutionBindingError("runner_bytes is invalid")
        operator = _actor(self.operator_actor_id, name="operator_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        if operator == approver:
            raise PhysicalCampaignExecutionBindingError("operator and approver must remain different")
        report_started = _utc(self.report_started_at_utc, name="report_started_at_utc")
        report_completed = _utc(self.report_completed_at_utc, name="report_completed_at_utc")
        execution_started = _utc(self.execution_started_at_utc, name="execution_started_at_utc")
        execution_completed = _utc(self.execution_completed_at_utc, name="execution_completed_at_utc")
        post_main = _utc(self.post_main_observed_at_utc, name="post_main_observed_at_utc")
        created = _utc(self.binding_created_at_utc, name="binding_created_at_utc")
        if not (report_started <= execution_started < execution_completed <= report_completed <= post_main <= created):
            raise PhysicalCampaignExecutionBindingError("physical execution/report/binding timing is invalid")
        if created - post_main > _MAX_BINDING_DELAY:
            raise PhysicalCampaignExecutionBindingError("physical execution binding was signed too late")
        if (
            self.exact_campaign_id_confirmed is not True
            or self.exact_runner_path_confirmed is not True
            or self.exact_runner_sha256_confirmed is not True
            or self.exact_runner_byte_count_confirmed is not True
            or self.exact_report_binding_confirmed is not True
            or self.continuous_main_freeze_confirmed is not False
            or self.dc_l14_independent_human_verdict is not False
            or self.human_pilot_go_decision is not False
            or self.authority != EXECUTION_BINDING_CLAIM_AUTHORITY
        ):
            raise PhysicalCampaignExecutionBindingError("physical execution binding authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignExecutionBinding":
        return cls(**_strict(value, fields=_BINDING_FIELDS, name="physical campaign execution binding"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "binding_id": self.binding_id,
            "evidence_snapshot_sha256": self.evidence_snapshot_sha256,
            "admission_sha256": self.admission_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "runner_relative_path": self.runner_relative_path,
            "runner_sha256": self.runner_sha256,
            "runner_bytes": self.runner_bytes,
            "signed_report_sha256": self.signed_report_sha256,
            "physical_report_sha256": self.physical_report_sha256,
            "report_id": self.report_id,
            "operator_actor_id": self.operator_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "report_started_at_utc": self.report_started_at_utc,
            "report_completed_at_utc": self.report_completed_at_utc,
            "execution_started_at_utc": self.execution_started_at_utc,
            "execution_completed_at_utc": self.execution_completed_at_utc,
            "post_main_observed_at_utc": self.post_main_observed_at_utc,
            "binding_created_at_utc": self.binding_created_at_utc,
            "exact_campaign_id_confirmed": self.exact_campaign_id_confirmed,
            "exact_runner_path_confirmed": self.exact_runner_path_confirmed,
            "exact_runner_sha256_confirmed": self.exact_runner_sha256_confirmed,
            "exact_runner_byte_count_confirmed": self.exact_runner_byte_count_confirmed,
            "exact_report_binding_confirmed": self.exact_report_binding_confirmed,
            "continuous_main_freeze_confirmed": self.continuous_main_freeze_confirmed,
            "dc_l14_independent_human_verdict": self.dc_l14_independent_human_verdict,
            "human_pilot_go_decision": self.human_pilot_go_decision,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


_PROOF_FIELDS = {
    "schema", "binding_sha256", "evidence_snapshot_sha256", "signature_sha256",
    "key_id", "issuer_actor_id", "issuer_system_id", "binding_id",
    "admission_sha256", "campaign_id", "task_id", "task_sha256", "repository",
    "base_sha", "requested_main_sha", "runner_relative_path", "runner_sha256",
    "runner_bytes", "signed_report_sha256", "physical_report_sha256", "report_id",
    "operator_actor_id", "approver_actor_id", "execution_started_at_utc",
    "execution_completed_at_utc", "binding_created_at_utc", "verified_at_utc",
    "evidence_snapshot_binding_verified", "human_execution_signature_verified",
    "runner_execution_binding_proven", "continuous_main_freeze_proven",
    "physical_campaign_completed", "dc_l15_complete",
    "dc_l14_independent_human_verdict_required", "human_pilot_go_required",
    "pilot_go_authorized", "activation_authorized", "remote_publication_authorized",
    "remaining_completion_gates", "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignExecutionProof:
    binding_sha256: str
    evidence_snapshot_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    binding_id: str
    admission_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    runner_relative_path: str
    runner_sha256: str
    runner_bytes: int
    signed_report_sha256: str
    physical_report_sha256: str
    report_id: str
    operator_actor_id: str
    approver_actor_id: str
    execution_started_at_utc: str
    execution_completed_at_utc: str
    binding_created_at_utc: str
    verified_at_utc: str
    evidence_snapshot_binding_verified: bool = True
    human_execution_signature_verified: bool = True
    runner_execution_binding_proven: bool = True
    continuous_main_freeze_proven: bool = False
    physical_campaign_completed: bool = False
    dc_l15_complete: bool = False
    dc_l14_independent_human_verdict_required: bool = True
    human_pilot_go_required: bool = True
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    remaining_completion_gates: tuple[str, ...] = REMAINING_COMPLETION_GATES
    authority: str = EXECUTION_PROOF_AUTHORITY
    schema: str = EXECUTION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EXECUTION_PROOF_SCHEMA:
            raise PhysicalCampaignExecutionBindingError("physical execution proof schema is unsupported")
        for name, value, pattern in (
            ("binding_sha256", self.binding_sha256, _HEX64),
            ("evidence_snapshot_sha256", self.evidence_snapshot_sha256, _HEX64),
            ("signature_sha256", self.signature_sha256, _HEX64),
            ("admission_sha256", self.admission_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("runner_sha256", self.runner_sha256, _HEX64),
            ("signed_report_sha256", self.signed_report_sha256, _HEX64),
            ("physical_report_sha256", self.physical_report_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        _identifier(self.binding_id, name="binding_id")
        _identifier(self.campaign_id, name="campaign_id")
        _identifier(self.report_id, name="report_id")
        _actor(self.operator_actor_id, name="operator_actor_id")
        _actor(self.approver_actor_id, name="approver_actor_id")
        if self.issuer_actor_id != self.operator_actor_id:
            raise PhysicalCampaignExecutionBindingError("execution proof issuer must be the physical operator")
        if self.issuer_system_id != EXECUTION_BINDING_ISSUER_SYSTEM_ID:
            raise PhysicalCampaignExecutionBindingError("execution proof belongs to another issuer system")
        if self.operator_actor_id == self.approver_actor_id:
            raise PhysicalCampaignExecutionBindingError("operator and approver must remain different")
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise PhysicalCampaignExecutionBindingError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignExecutionBindingError("repository is unsupported")
        if not isinstance(self.runner_relative_path, str) or not 1 <= len(self.runner_relative_path) <= 512:
            raise PhysicalCampaignExecutionBindingError("runner_relative_path is invalid")
        if isinstance(self.runner_bytes, bool) or not isinstance(self.runner_bytes, int) or not 1 <= self.runner_bytes <= _MAX_RUNNER_BYTES:
            raise PhysicalCampaignExecutionBindingError("runner_bytes is invalid")
        started = _utc(self.execution_started_at_utc, name="execution_started_at_utc")
        completed = _utc(self.execution_completed_at_utc, name="execution_completed_at_utc")
        created = _utc(self.binding_created_at_utc, name="binding_created_at_utc")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        if not started < completed <= created <= verified:
            raise PhysicalCampaignExecutionBindingError("physical execution proof timing is invalid")
        if self.remaining_completion_gates != REMAINING_COMPLETION_GATES:
            raise PhysicalCampaignExecutionBindingError("remaining completion gates are not exact")
        if (
            self.evidence_snapshot_binding_verified is not True
            or self.human_execution_signature_verified is not True
            or self.runner_execution_binding_proven is not True
            or self.continuous_main_freeze_proven is not False
            or self.physical_campaign_completed is not False
            or self.dc_l15_complete is not False
            or self.dc_l14_independent_human_verdict_required is not True
            or self.human_pilot_go_required is not True
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.authority != EXECUTION_PROOF_AUTHORITY
        ):
            raise PhysicalCampaignExecutionBindingError("physical execution proof authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignExecutionProof":
        data = _strict(value, fields=_PROOF_FIELDS, name="physical campaign execution proof")
        gates = data["remaining_completion_gates"]
        if not isinstance(gates, list):
            raise PhysicalCampaignExecutionBindingError("remaining_completion_gates must be an array")
        kwargs = dict(data)
        kwargs["remaining_completion_gates"] = tuple(gates)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "binding_sha256": self.binding_sha256,
            "evidence_snapshot_sha256": self.evidence_snapshot_sha256,
            "signature_sha256": self.signature_sha256,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "binding_id": self.binding_id,
            "admission_sha256": self.admission_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "runner_relative_path": self.runner_relative_path,
            "runner_sha256": self.runner_sha256,
            "runner_bytes": self.runner_bytes,
            "signed_report_sha256": self.signed_report_sha256,
            "physical_report_sha256": self.physical_report_sha256,
            "report_id": self.report_id,
            "operator_actor_id": self.operator_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "execution_started_at_utc": self.execution_started_at_utc,
            "execution_completed_at_utc": self.execution_completed_at_utc,
            "binding_created_at_utc": self.binding_created_at_utc,
            "verified_at_utc": self.verified_at_utc,
            "evidence_snapshot_binding_verified": self.evidence_snapshot_binding_verified,
            "human_execution_signature_verified": self.human_execution_signature_verified,
            "runner_execution_binding_proven": self.runner_execution_binding_proven,
            "continuous_main_freeze_proven": self.continuous_main_freeze_proven,
            "physical_campaign_completed": self.physical_campaign_completed,
            "dc_l15_complete": self.dc_l15_complete,
            "dc_l14_independent_human_verdict_required": self.dc_l14_independent_human_verdict_required,
            "human_pilot_go_required": self.human_pilot_go_required,
            "pilot_go_authorized": self.pilot_go_authorized,
            "activation_authorized": self.activation_authorized,
            "remote_publication_authorized": self.remote_publication_authorized,
            "remaining_completion_gates": list(self.remaining_completion_gates),
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _require_evidence_snapshot(value: Any) -> PhysicalCampaignEvidenceSnapshot:
    if type(value) is not PhysicalCampaignEvidenceSnapshot:
        raise PhysicalCampaignExecutionBindingError("exact PhysicalCampaignEvidenceSnapshot is required")
    if (
        value.runner_execution_binding_proven is not False
        or value.continuous_main_freeze_proven is not False
        or value.physical_campaign_completed is not False
        or value.dc_l15_complete is not False
        or value.pilot_go_authorized is not False
        or value.activation_authorized is not False
        or value.remote_publication_authorized is not False
    ):
        raise PhysicalCampaignExecutionBindingError("physical evidence snapshot authority state is invalid")
    return value


def build_physical_campaign_execution_binding(
    *,
    evidence: PhysicalCampaignEvidenceSnapshot,
    binding_id: str,
    operator_actor_id: str,
    execution_started_at_utc: str,
    execution_completed_at_utc: str,
    binding_created_at_utc: str,
) -> PhysicalCampaignExecutionBinding:
    """Build the exact canonical human claim to sign; this grants no authority."""
    snapshot = _require_evidence_snapshot(evidence)
    if operator_actor_id != snapshot.collector_actor_id:
        raise PhysicalCampaignExecutionBindingError("execution binding operator must be the physical evidence collector")
    return PhysicalCampaignExecutionBinding(
        binding_id=binding_id,
        evidence_snapshot_sha256=snapshot.sha256,
        admission_sha256=snapshot.admission_sha256,
        campaign_id=snapshot.campaign_id,
        task_id=snapshot.task_id,
        task_sha256=snapshot.task_sha256,
        repository=snapshot.repository,
        base_sha=snapshot.base_sha,
        requested_main_sha=snapshot.requested_main_sha,
        runner_relative_path=snapshot.runner_relative_path,
        runner_sha256=snapshot.runner_sha256,
        runner_bytes=snapshot.runner_bytes,
        signed_report_sha256=snapshot.signed_report_sha256,
        physical_report_sha256=snapshot.physical_report_sha256,
        report_id=snapshot.report_id,
        operator_actor_id=operator_actor_id,
        approver_actor_id=snapshot.approver_actor_id,
        report_started_at_utc=snapshot.report_started_at_utc,
        report_completed_at_utc=snapshot.report_completed_at_utc,
        execution_started_at_utc=execution_started_at_utc,
        execution_completed_at_utc=execution_completed_at_utc,
        post_main_observed_at_utc=snapshot.post_main_observed_at_utc,
        binding_created_at_utc=binding_created_at_utc,
    )


def _binding_matches_evidence(*, evidence: PhysicalCampaignEvidenceSnapshot, binding: PhysicalCampaignExecutionBinding) -> bool:
    expected = {
        "evidence_snapshot_sha256": evidence.sha256,
        "admission_sha256": evidence.admission_sha256,
        "campaign_id": evidence.campaign_id,
        "task_id": evidence.task_id,
        "task_sha256": evidence.task_sha256,
        "repository": evidence.repository,
        "base_sha": evidence.base_sha,
        "requested_main_sha": evidence.requested_main_sha,
        "runner_relative_path": evidence.runner_relative_path,
        "runner_sha256": evidence.runner_sha256,
        "runner_bytes": evidence.runner_bytes,
        "signed_report_sha256": evidence.signed_report_sha256,
        "physical_report_sha256": evidence.physical_report_sha256,
        "report_id": evidence.report_id,
        "operator_actor_id": evidence.collector_actor_id,
        "approver_actor_id": evidence.approver_actor_id,
        "report_started_at_utc": evidence.report_started_at_utc,
        "report_completed_at_utc": evidence.report_completed_at_utc,
        "post_main_observed_at_utc": evidence.post_main_observed_at_utc,
    }
    return all(getattr(binding, name) == value for name, value in expected.items())


def _verify_physical_campaign_execution_binding(
    *,
    evidence: PhysicalCampaignEvidenceSnapshot,
    binding: PhysicalCampaignExecutionBinding,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PhysicalCampaignExecutionProof:
    snapshot = _require_evidence_snapshot(evidence)
    if type(binding) is not PhysicalCampaignExecutionBinding:
        raise PhysicalCampaignExecutionBindingError("exact PhysicalCampaignExecutionBinding is required")
    if not _binding_matches_evidence(evidence=snapshot, binding=binding):
        raise PhysicalCampaignExecutionBindingError("execution binding is not exactly bound to the physical evidence snapshot")
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PhysicalCampaignExecutionBindingError("detached Ed25519 execution-binding signature is required")
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PhysicalCampaignExecutionBindingError("Ed25519 execution-binding verifier is required")
    if signature.issuer_system_id != EXECUTION_BINDING_ISSUER_SYSTEM_ID:
        raise PhysicalCampaignExecutionBindingError("execution binding signature belongs to another issuer system")
    if signature.issuer_actor_id != binding.operator_actor_id:
        raise PhysicalCampaignExecutionBindingError("execution binding signer must be the physical operator")
    if signature.signed_at_utc != binding.binding_created_at_utc:
        raise PhysicalCampaignExecutionBindingError("execution binding signature time does not match the claim")
    verified_at = now_provider()
    _utc(verified_at, name="execution binding verification time")
    try:
        verified_payload_sha256 = verifier.verify(
            payload=binding.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PhysicalCampaignExecutionBindingError("execution binding authority verification failed") from exc
    if verified_payload_sha256 != binding.sha256:
        raise PhysicalCampaignExecutionBindingError("execution binding verified payload hash mismatch")
    return PhysicalCampaignExecutionProof(
        binding_sha256=binding.sha256,
        evidence_snapshot_sha256=snapshot.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        binding_id=binding.binding_id,
        admission_sha256=binding.admission_sha256,
        campaign_id=binding.campaign_id,
        task_id=binding.task_id,
        task_sha256=binding.task_sha256,
        repository=binding.repository,
        base_sha=binding.base_sha,
        requested_main_sha=binding.requested_main_sha,
        runner_relative_path=binding.runner_relative_path,
        runner_sha256=binding.runner_sha256,
        runner_bytes=binding.runner_bytes,
        signed_report_sha256=binding.signed_report_sha256,
        physical_report_sha256=binding.physical_report_sha256,
        report_id=binding.report_id,
        operator_actor_id=binding.operator_actor_id,
        approver_actor_id=binding.approver_actor_id,
        execution_started_at_utc=binding.execution_started_at_utc,
        execution_completed_at_utc=binding.execution_completed_at_utc,
        binding_created_at_utc=binding.binding_created_at_utc,
        verified_at_utc=verified_at,
    )


def verify_physical_campaign_execution_binding(
    *,
    evidence: PhysicalCampaignEvidenceSnapshot,
    binding: PhysicalCampaignExecutionBinding,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PhysicalCampaignExecutionProof:
    """Injectable compatibility surface replaced by the production facade."""
    if verifier is None:
        raise PhysicalCampaignExecutionBindingError("execution binding verifier is unavailable outside production facade")
    return _verify_physical_campaign_execution_binding(
        evidence=evidence,
        binding=binding,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "EXECUTION_BINDING_SCHEMA",
    "EXECUTION_PROOF_SCHEMA",
    "EXECUTION_BINDING_CLAIM_AUTHORITY",
    "EXECUTION_PROOF_AUTHORITY",
    "EXECUTION_BINDING_ISSUER_SYSTEM_ID",
    "REMAINING_COMPLETION_GATES",
    "PhysicalCampaignExecutionBindingError",
    "PhysicalCampaignExecutionBinding",
    "PhysicalCampaignExecutionProof",
    "build_physical_campaign_execution_binding",
    "verify_physical_campaign_execution_binding",
]
