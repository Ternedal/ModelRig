"""Independent human verdict boundary for one ADR-DC-013 physical campaign.

ADR-DC-014 consumes only already-produced ADR-DC-012/013 evidence. It cannot
sign a verdict, run a campaign, grant pilot GO, or publish anything. A separate
human reviewer must sign an exact verdict outside ModelRig; this module only
verifies that claim and, on APPROVE, closes DC-L15 completion.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_physical_campaign_execution_binding import PhysicalCampaignExecutionProof
from .improvement_physical_campaign_main_freeze import PhysicalCampaignMainFreezeProof

INDEPENDENT_VERDICT_SCHEMA = "kaliv-rsi-physical-campaign-independent-human-verdict/v1"
INDEPENDENT_VERDICT_PROOF_SCHEMA = "kaliv-rsi-physical-campaign-independent-human-verdict-proof/v1"
INDEPENDENT_VERDICT_AUTHORITY = "human-independent-dc-l15-verdict-only"
INDEPENDENT_VERDICT_PROOF_AUTHORITY = "verified-independent-human-dc-l15-completion-only"
INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID = "kaliv-rsi-dc-l15-independent-human-verdict-authority-v1"
REMAINING_COMPLETION_GATES = ("human_pilot_go_decision",)
_MAX_REVIEW_DELAY = timedelta(hours=24)
_MAX_VERIFICATION_DELAY = timedelta(hours=24)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DECISIONS = {"approve", "request_changes", "reject"}


class PhysicalCampaignIndependentHumanVerdictError(ValueError):
    """Independent human verdict evidence is malformed, stale or over-authorizing."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict is not canonical JSON") from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhysicalCampaignIndependentHumanVerdictError(f"{name} fields mismatch")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalCampaignIndependentHumanVerdictError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PhysicalCampaignIndependentHumanVerdictError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PhysicalCampaignIndependentHumanVerdictError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalCampaignIndependentHumanVerdictError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PhysicalCampaignIndependentHumanVerdictError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _findings(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict findings must be an array")
    items = tuple(value)
    if len(items) > 64:
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict has too many findings")
    for item in items:
        if not isinstance(item, str) or not item or item.strip() != item or "\x00" in item or len(item.encode("utf-8")) > 2048:
            raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict finding is invalid")
    if len(items) != len(set(items)):
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict findings must not contain duplicates")
    return items


_VERDICT_FIELDS = {
    "schema", "verdict_id", "main_freeze_proof_sha256", "execution_proof_sha256",
    "evidence_snapshot_sha256", "admission_sha256", "campaign_id", "task_id",
    "task_sha256", "repository", "base_sha", "requested_main_sha", "operator_actor_id",
    "approver_actor_id", "reviewer_actor_id", "decision", "findings", "reviewed_at_utc",
    "physical_evidence_reviewed", "runner_execution_binding_reviewed",
    "continuous_main_freeze_reviewed", "independent_reviewer_confirmed", "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignIndependentHumanVerdict:
    verdict_id: str
    main_freeze_proof_sha256: str
    execution_proof_sha256: str
    evidence_snapshot_sha256: str
    admission_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    operator_actor_id: str
    approver_actor_id: str
    reviewer_actor_id: str
    decision: str
    findings: tuple[str, ...]
    reviewed_at_utc: str
    physical_evidence_reviewed: bool = True
    runner_execution_binding_reviewed: bool = True
    continuous_main_freeze_reviewed: bool = True
    independent_reviewer_confirmed: bool = True
    authority: str = INDEPENDENT_VERDICT_AUTHORITY
    schema: str = INDEPENDENT_VERDICT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != INDEPENDENT_VERDICT_SCHEMA:
            raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict schema is unsupported")
        _identifier(self.verdict_id, name="verdict_id")
        _identifier(self.campaign_id, name="campaign_id")
        for name, value, pattern in (
            ("main_freeze_proof_sha256", self.main_freeze_proof_sha256, _HEX64),
            ("execution_proof_sha256", self.execution_proof_sha256, _HEX64),
            ("evidence_snapshot_sha256", self.evidence_snapshot_sha256, _HEX64),
            ("admission_sha256", self.admission_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
        ):
            _hex(value, name=name, pattern=pattern)
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise PhysicalCampaignIndependentHumanVerdictError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignIndependentHumanVerdictError("repository is unsupported")
        operator = _actor(self.operator_actor_id, name="operator_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        reviewer = _actor(self.reviewer_actor_id, name="reviewer_actor_id")
        if len({operator, approver, reviewer}) != 3:
            raise PhysicalCampaignIndependentHumanVerdictError("independent reviewer must differ from operator and approver")
        if self.decision not in _DECISIONS:
            raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict decision is unsupported")
        _findings(self.findings)
        _utc(self.reviewed_at_utc, name="reviewed_at_utc")
        if self.decision != "approve" and not self.findings:
            raise PhysicalCampaignIndependentHumanVerdictError("non-approval independent verdict requires findings")
        if (
            self.physical_evidence_reviewed is not True
            or self.runner_execution_binding_reviewed is not True
            or self.continuous_main_freeze_reviewed is not True
            or self.independent_reviewer_confirmed is not True
            or self.authority != INDEPENDENT_VERDICT_AUTHORITY
        ):
            raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignIndependentHumanVerdict":
        data = dict(_strict(value, fields=_VERDICT_FIELDS, name="independent human verdict"))
        if not isinstance(data.get("findings"), list):
            raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict findings must be an array")
        data["findings"] = tuple(data["findings"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "verdict_id": self.verdict_id,
            "main_freeze_proof_sha256": self.main_freeze_proof_sha256,
            "execution_proof_sha256": self.execution_proof_sha256,
            "evidence_snapshot_sha256": self.evidence_snapshot_sha256,
            "admission_sha256": self.admission_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "operator_actor_id": self.operator_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "reviewer_actor_id": self.reviewer_actor_id,
            "decision": self.decision,
            "findings": list(self.findings),
            "reviewed_at_utc": self.reviewed_at_utc,
            "physical_evidence_reviewed": self.physical_evidence_reviewed,
            "runner_execution_binding_reviewed": self.runner_execution_binding_reviewed,
            "continuous_main_freeze_reviewed": self.continuous_main_freeze_reviewed,
            "independent_reviewer_confirmed": self.independent_reviewer_confirmed,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


_PROOF_FIELDS = {
    "schema", "verdict_sha256", "signature_sha256", "key_id", "issuer_actor_id",
    "issuer_system_id", "main_freeze_proof_sha256", "execution_proof_sha256",
    "evidence_snapshot_sha256", "admission_sha256", "campaign_id", "task_id",
    "task_sha256", "repository", "base_sha", "requested_main_sha", "operator_actor_id",
    "approver_actor_id", "reviewer_actor_id", "verdict_id", "decision", "findings",
    "reviewed_at_utc", "verified_at_utc", "independent_human_verdict_verified",
    "runner_execution_binding_proven", "continuous_main_freeze_proven",
    "physical_campaign_completed", "dc_l15_complete",
    "dc_l14_independent_human_verdict_required", "human_pilot_go_required",
    "pilot_go_authorized", "activation_authorized", "remote_publication_authorized",
    "remaining_completion_gates", "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignIndependentHumanVerdictProof:
    verdict_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    main_freeze_proof_sha256: str
    execution_proof_sha256: str
    evidence_snapshot_sha256: str
    admission_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    operator_actor_id: str
    approver_actor_id: str
    reviewer_actor_id: str
    verdict_id: str
    decision: str
    findings: tuple[str, ...]
    reviewed_at_utc: str
    verified_at_utc: str
    independent_human_verdict_verified: bool = True
    runner_execution_binding_proven: bool = True
    continuous_main_freeze_proven: bool = True
    physical_campaign_completed: bool = True
    dc_l15_complete: bool = True
    dc_l14_independent_human_verdict_required: bool = False
    human_pilot_go_required: bool = True
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    remaining_completion_gates: tuple[str, ...] = REMAINING_COMPLETION_GATES
    authority: str = INDEPENDENT_VERDICT_PROOF_AUTHORITY
    schema: str = INDEPENDENT_VERDICT_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != INDEPENDENT_VERDICT_PROOF_SCHEMA:
            raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict proof schema is unsupported")
        for name, value, pattern in (
            ("verdict_sha256", self.verdict_sha256, _HEX64),
            ("signature_sha256", self.signature_sha256, _HEX64),
            ("main_freeze_proof_sha256", self.main_freeze_proof_sha256, _HEX64),
            ("execution_proof_sha256", self.execution_proof_sha256, _HEX64),
            ("evidence_snapshot_sha256", self.evidence_snapshot_sha256, _HEX64),
            ("admission_sha256", self.admission_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        _identifier(self.verdict_id, name="verdict_id")
        _identifier(self.campaign_id, name="campaign_id")
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise PhysicalCampaignIndependentHumanVerdictError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignIndependentHumanVerdictError("repository is unsupported")
        operator = _actor(self.operator_actor_id, name="operator_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        reviewer = _actor(self.reviewer_actor_id, name="reviewer_actor_id")
        if len({operator, approver, reviewer}) != 3 or self.issuer_actor_id != reviewer:
            raise PhysicalCampaignIndependentHumanVerdictError("independent verdict proof actor separation is invalid")
        if (
            self.issuer_system_id != INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID
            or self.decision != "approve"
            or _findings(self.findings) != self.findings
            or _utc(self.verified_at_utc, name="verified_at_utc") < _utc(self.reviewed_at_utc, name="reviewed_at_utc")
            or self.independent_human_verdict_verified is not True
            or self.runner_execution_binding_proven is not True
            or self.continuous_main_freeze_proven is not True
            or self.physical_campaign_completed is not True
            or self.dc_l15_complete is not True
            or self.dc_l14_independent_human_verdict_required is not False
            or self.human_pilot_go_required is not True
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.remaining_completion_gates != REMAINING_COMPLETION_GATES
            or self.authority != INDEPENDENT_VERDICT_PROOF_AUTHORITY
        ):
            raise PhysicalCampaignIndependentHumanVerdictError("independent verdict proof authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignIndependentHumanVerdictProof":
        data = dict(_strict(value, fields=_PROOF_FIELDS, name="independent human verdict proof"))
        if not isinstance(data.get("findings"), list) or not isinstance(data.get("remaining_completion_gates"), list):
            raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict proof arrays are invalid")
        data["findings"] = tuple(data["findings"])
        data["remaining_completion_gates"] = tuple(data["remaining_completion_gates"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "verdict_sha256": self.verdict_sha256,
            "signature_sha256": self.signature_sha256,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "main_freeze_proof_sha256": self.main_freeze_proof_sha256,
            "execution_proof_sha256": self.execution_proof_sha256,
            "evidence_snapshot_sha256": self.evidence_snapshot_sha256,
            "admission_sha256": self.admission_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "operator_actor_id": self.operator_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "reviewer_actor_id": self.reviewer_actor_id,
            "verdict_id": self.verdict_id,
            "decision": self.decision,
            "findings": list(self.findings),
            "reviewed_at_utc": self.reviewed_at_utc,
            "verified_at_utc": self.verified_at_utc,
            "independent_human_verdict_verified": self.independent_human_verdict_verified,
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


def _require_chain(*, main_freeze_proof: Any, execution_proof: Any) -> tuple[PhysicalCampaignMainFreezeProof, PhysicalCampaignExecutionProof]:
    if type(main_freeze_proof) is not PhysicalCampaignMainFreezeProof:
        raise PhysicalCampaignIndependentHumanVerdictError("exact PhysicalCampaignMainFreezeProof is required")
    if type(execution_proof) is not PhysicalCampaignExecutionProof:
        raise PhysicalCampaignIndependentHumanVerdictError("exact PhysicalCampaignExecutionProof is required")
    freeze = main_freeze_proof
    execution = execution_proof
    if (
        freeze.execution_proof_sha256 != execution.sha256
        or freeze.evidence_snapshot_sha256 != execution.evidence_snapshot_sha256
        or freeze.admission_sha256 != execution.admission_sha256
        or freeze.campaign_id != execution.campaign_id
        or freeze.task_id != execution.task_id
        or freeze.task_sha256 != execution.task_sha256
        or freeze.repository != execution.repository
        or freeze.base_sha != execution.base_sha
        or freeze.requested_main_sha != execution.requested_main_sha
    ):
        raise PhysicalCampaignIndependentHumanVerdictError("main-freeze proof is not exactly bound to execution proof")
    if (
        freeze.runner_execution_binding_proven is not True
        or freeze.continuous_main_freeze_proven is not True
        or freeze.physical_campaign_completed is not False
        or freeze.dc_l15_complete is not False
        or freeze.dc_l14_independent_human_verdict_required is not True
        or freeze.human_pilot_go_required is not True
        or freeze.pilot_go_authorized is not False
        or freeze.activation_authorized is not False
        or freeze.remote_publication_authorized is not False
        or freeze.remaining_completion_gates != ("dc_l14_independent_human_verdict", "human_pilot_go_decision")
    ):
        raise PhysicalCampaignIndependentHumanVerdictError("main-freeze proof authority state is invalid")
    if (
        execution.runner_execution_binding_proven is not True
        or execution.physical_campaign_completed is not False
        or execution.dc_l15_complete is not False
        or execution.pilot_go_authorized is not False
        or execution.activation_authorized is not False
        or execution.remote_publication_authorized is not False
        or execution.operator_actor_id == execution.approver_actor_id
    ):
        raise PhysicalCampaignIndependentHumanVerdictError("execution proof authority state is invalid")
    return freeze, execution


def build_physical_campaign_independent_human_verdict(
    *,
    main_freeze_proof: PhysicalCampaignMainFreezeProof,
    execution_proof: PhysicalCampaignExecutionProof,
    verdict_id: str,
    reviewer_actor_id: str,
    decision: str,
    findings: Sequence[str] = (),
    reviewed_at_utc: str,
) -> PhysicalCampaignIndependentHumanVerdict:
    """Build the exact external-human claim to sign; this grants no authority."""
    freeze, execution = _require_chain(main_freeze_proof=main_freeze_proof, execution_proof=execution_proof)
    reviewed = _utc(reviewed_at_utc, name="reviewed_at_utc")
    finalized = _utc(freeze.freeze_finalized_at_utc, name="freeze_finalized_at_utc")
    if reviewed < finalized or reviewed - finalized > _MAX_REVIEW_DELAY:
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict was recorded outside the review window")
    return PhysicalCampaignIndependentHumanVerdict(
        verdict_id=verdict_id,
        main_freeze_proof_sha256=freeze.sha256,
        execution_proof_sha256=execution.sha256,
        evidence_snapshot_sha256=execution.evidence_snapshot_sha256,
        admission_sha256=execution.admission_sha256,
        campaign_id=execution.campaign_id,
        task_id=execution.task_id,
        task_sha256=execution.task_sha256,
        repository=execution.repository,
        base_sha=execution.base_sha,
        requested_main_sha=execution.requested_main_sha,
        operator_actor_id=execution.operator_actor_id,
        approver_actor_id=execution.approver_actor_id,
        reviewer_actor_id=reviewer_actor_id,
        decision=decision,
        findings=_findings(findings),
        reviewed_at_utc=reviewed_at_utc,
    )


def _verdict_matches_chain(*, main_freeze_proof: PhysicalCampaignMainFreezeProof, execution_proof: PhysicalCampaignExecutionProof, verdict: PhysicalCampaignIndependentHumanVerdict) -> bool:
    expected = {
        "main_freeze_proof_sha256": main_freeze_proof.sha256,
        "execution_proof_sha256": execution_proof.sha256,
        "evidence_snapshot_sha256": execution_proof.evidence_snapshot_sha256,
        "admission_sha256": execution_proof.admission_sha256,
        "campaign_id": execution_proof.campaign_id,
        "task_id": execution_proof.task_id,
        "task_sha256": execution_proof.task_sha256,
        "repository": execution_proof.repository,
        "base_sha": execution_proof.base_sha,
        "requested_main_sha": execution_proof.requested_main_sha,
        "operator_actor_id": execution_proof.operator_actor_id,
        "approver_actor_id": execution_proof.approver_actor_id,
    }
    return all(getattr(verdict, name) == value for name, value in expected.items())


def _verify_physical_campaign_independent_human_verdict(
    *,
    main_freeze_proof: PhysicalCampaignMainFreezeProof,
    execution_proof: PhysicalCampaignExecutionProof,
    verdict: PhysicalCampaignIndependentHumanVerdict,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PhysicalCampaignIndependentHumanVerdictProof:
    freeze, execution = _require_chain(main_freeze_proof=main_freeze_proof, execution_proof=execution_proof)
    if type(verdict) is not PhysicalCampaignIndependentHumanVerdict:
        raise PhysicalCampaignIndependentHumanVerdictError("exact PhysicalCampaignIndependentHumanVerdict is required")
    if not _verdict_matches_chain(main_freeze_proof=freeze, execution_proof=execution, verdict=verdict):
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict is not exactly bound to campaign evidence")
    if verdict.reviewer_actor_id in {execution.operator_actor_id, execution.approver_actor_id}:
        raise PhysicalCampaignIndependentHumanVerdictError("independent reviewer must differ from operator and approver")
    if verdict.decision != "approve":
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict does not approve DC-L15 completion")
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PhysicalCampaignIndependentHumanVerdictError("detached Ed25519 independent-verdict signature is required")
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PhysicalCampaignIndependentHumanVerdictError("Ed25519 independent-verdict verifier is required")
    if signature.issuer_system_id != INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID:
        raise PhysicalCampaignIndependentHumanVerdictError("independent verdict signature belongs to another issuer system")
    if signature.issuer_actor_id != verdict.reviewer_actor_id:
        raise PhysicalCampaignIndependentHumanVerdictError("independent verdict signer must be the reviewer")
    if signature.signed_at_utc != verdict.reviewed_at_utc:
        raise PhysicalCampaignIndependentHumanVerdictError("independent verdict signature time does not match the claim")
    verified_at = now_provider()
    verified = _utc(verified_at, name="independent verdict verification time")
    reviewed = _utc(verdict.reviewed_at_utc, name="reviewed_at_utc")
    if verified < reviewed or verified - reviewed > _MAX_VERIFICATION_DELAY:
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict verification is outside its freshness window")
    try:
        verified_payload_sha256 = verifier.verify(
            payload=verdict.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict authority verification failed") from exc
    if verified_payload_sha256 != verdict.sha256:
        raise PhysicalCampaignIndependentHumanVerdictError("independent human verdict verified payload hash mismatch")
    return PhysicalCampaignIndependentHumanVerdictProof(
        verdict_sha256=verdict.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        main_freeze_proof_sha256=freeze.sha256,
        execution_proof_sha256=execution.sha256,
        evidence_snapshot_sha256=execution.evidence_snapshot_sha256,
        admission_sha256=execution.admission_sha256,
        campaign_id=execution.campaign_id,
        task_id=execution.task_id,
        task_sha256=execution.task_sha256,
        repository=execution.repository,
        base_sha=execution.base_sha,
        requested_main_sha=execution.requested_main_sha,
        operator_actor_id=execution.operator_actor_id,
        approver_actor_id=execution.approver_actor_id,
        reviewer_actor_id=verdict.reviewer_actor_id,
        verdict_id=verdict.verdict_id,
        decision=verdict.decision,
        findings=verdict.findings,
        reviewed_at_utc=verdict.reviewed_at_utc,
        verified_at_utc=verified_at,
    )


def verify_physical_campaign_independent_human_verdict(
    *,
    main_freeze_proof: PhysicalCampaignMainFreezeProof,
    execution_proof: PhysicalCampaignExecutionProof,
    verdict: PhysicalCampaignIndependentHumanVerdict,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PhysicalCampaignIndependentHumanVerdictProof:
    """Injectable compatibility surface replaced by the production facade."""
    if verifier is None:
        raise PhysicalCampaignIndependentHumanVerdictError("independent verdict verifier is unavailable outside production facade")
    return _verify_physical_campaign_independent_human_verdict(
        main_freeze_proof=main_freeze_proof,
        execution_proof=execution_proof,
        verdict=verdict,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "INDEPENDENT_VERDICT_SCHEMA",
    "INDEPENDENT_VERDICT_PROOF_SCHEMA",
    "INDEPENDENT_VERDICT_AUTHORITY",
    "INDEPENDENT_VERDICT_PROOF_AUTHORITY",
    "INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID",
    "REMAINING_COMPLETION_GATES",
    "PhysicalCampaignIndependentHumanVerdictError",
    "PhysicalCampaignIndependentHumanVerdict",
    "PhysicalCampaignIndependentHumanVerdictProof",
    "build_physical_campaign_independent_human_verdict",
    "verify_physical_campaign_independent_human_verdict",
]
