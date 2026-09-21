"""Non-authorizing RSI qualification packet before DC-L15/DC-L16 physical gates.

The packet proves that the software/evidence chain is internally bound from one
ImprovementProposal through human-signed promotion, local candidate collection,
regression proof and runtime provenance. It deliberately cannot satisfy the
physical or human gates that remain outside software.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .improvement_candidate_provenance import CandidateRuntimeProvenance
from .improvement_candidate_snapshot import CandidateSnapshotReceipt
from .improvement_promotion import PromotionReceipt, proposal_sha256
from .improvement_proposal import ImprovementProposal
from .improvement_regression import CandidateRegressionProof

QUALIFICATION_PACKET_SCHEMA = "kaliv-rsi-qualification-packet/v1"
QUALIFICATION_PACKET_AUTHORITY = "evidence-only"
QUALIFICATION_PHASE = "pre-dc-l15-physical-qualification"

MISSING_PHYSICAL_GATES = (
    "dc_l14_independent_human_verdict",
    "exact_frozen_main_head_confirmation",
    "fresh_physical_i0b_campaign",
    "independent_physical_collector_approver",
    "human_pilot_go_decision",
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_PACKET_FIELDS = {
    "schema",
    "phase",
    "proposal_id",
    "repository",
    "base_sha",
    "proposal_sha256",
    "promotion_receipt_sha256",
    "task_id",
    "task_sha256",
    "materialization_receipt_sha256",
    "snapshot_receipt_sha256",
    "candidate_commit_sha",
    "candidate_tree_sha",
    "worker_code_sha256",
    "baseline_eval_sha256",
    "candidate_eval_sha256",
    "regression_proof_sha256",
    "runtime_provenance_sha256",
    "required_evals",
    "software_chain_complete",
    "ready_for_human_go",
    "activation_authorized",
    "automatic_activation",
    "remote_publication_authorized",
    "fresh_physical_evidence_required",
    "independent_collector_approver_required",
    "missing_physical_gates",
    "authority",
    "merge_authority",
}


class QualificationPacketError(ValueError):
    """The supplied RSI evidence chain is incomplete or internally inconsistent."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise QualificationPacketError("qualification packet is not canonical JSON") from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _string(value: Any, *, name: str, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise QualificationPacketError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    text = _string(value, name=name, maximum=64)
    if pattern.fullmatch(text) is None:
        raise QualificationPacketError(f"{name} is invalid")
    return text


def _bool(value: Any, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise QualificationPacketError(f"{name} must be boolean")
    return value


def _string_tuple(value: Any, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise QualificationPacketError(f"{name} must be a non-empty array")
    result = tuple(
        _string(item, name=f"{name}[{index}]", maximum=1024)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise QualificationPacketError(f"{name} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class QualificationPacket:
    proposal_id: str
    repository: str
    base_sha: str
    proposal_sha256: str
    promotion_receipt_sha256: str
    task_id: str
    task_sha256: str
    materialization_receipt_sha256: str
    snapshot_receipt_sha256: str
    candidate_commit_sha: str
    candidate_tree_sha: str
    worker_code_sha256: str
    baseline_eval_sha256: str
    candidate_eval_sha256: str
    regression_proof_sha256: str
    runtime_provenance_sha256: str
    required_evals: tuple[str, ...]
    software_chain_complete: bool
    ready_for_human_go: bool
    activation_authorized: bool
    automatic_activation: bool
    remote_publication_authorized: bool
    fresh_physical_evidence_required: bool
    independent_collector_approver_required: bool
    missing_physical_gates: tuple[str, ...]
    phase: str = QUALIFICATION_PHASE
    authority: str = QUALIFICATION_PACKET_AUTHORITY
    merge_authority: str = "human"
    schema: str = QUALIFICATION_PACKET_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != QUALIFICATION_PACKET_SCHEMA:
            raise QualificationPacketError("qualification packet schema is unsupported")
        if self.phase != QUALIFICATION_PHASE:
            raise QualificationPacketError("qualification packet phase is unsupported")
        _string(self.proposal_id, name="proposal_id", maximum=64)
        repository = _string(self.repository, name="repository", maximum=200)
        parts = repository.split("/")
        if len(parts) != 2 or not all(part and part.strip() == part for part in parts):
            raise QualificationPacketError("repository must be owner/name")
        _hex(self.base_sha, name="base_sha", pattern=_SHA40)
        for name in (
            "proposal_sha256",
            "promotion_receipt_sha256",
            "task_sha256",
            "materialization_receipt_sha256",
            "snapshot_receipt_sha256",
            "worker_code_sha256",
            "baseline_eval_sha256",
            "candidate_eval_sha256",
            "regression_proof_sha256",
            "runtime_provenance_sha256",
        ):
            _hex(getattr(self, name), name=name, pattern=_SHA64)
        _string(self.task_id, name="task_id", maximum=64)
        _hex(self.candidate_commit_sha, name="candidate_commit_sha", pattern=_SHA40)
        _hex(self.candidate_tree_sha, name="candidate_tree_sha", pattern=_SHA40)
        _string_tuple(self.required_evals, name="required_evals")
        for name in (
            "software_chain_complete",
            "ready_for_human_go",
            "activation_authorized",
            "automatic_activation",
            "remote_publication_authorized",
            "fresh_physical_evidence_required",
            "independent_collector_approver_required",
        ):
            _bool(getattr(self, name), name=name)
        _string_tuple(self.missing_physical_gates, name="missing_physical_gates")
        if self.authority != "evidence-only" or self.merge_authority != "human":
            raise QualificationPacketError("qualification packet authority is invalid")
        if self.software_chain_complete is not True:
            raise QualificationPacketError("qualification packet requires a complete software chain")
        if (
            self.ready_for_human_go is not False
            or self.activation_authorized is not False
            or self.automatic_activation is not False
            or self.remote_publication_authorized is not False
        ):
            raise QualificationPacketError(
                "software qualification may not grant pilot or activation authority"
            )
        if (
            self.fresh_physical_evidence_required is not True
            or self.independent_collector_approver_required is not True
        ):
            raise QualificationPacketError(
                "physical qualification requirements may not be relaxed"
            )
        if self.missing_physical_gates != MISSING_PHYSICAL_GATES:
            raise QualificationPacketError(
                "qualification packet must preserve all external physical/human gates"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "QualificationPacket":
        if not isinstance(value, Mapping):
            raise QualificationPacketError("qualification packet must be an object")
        unknown = sorted(set(value) - _PACKET_FIELDS)
        missing = sorted(_PACKET_FIELDS - set(value))
        if unknown or missing:
            raise QualificationPacketError(
                "qualification packet fields mismatch"
                + (f"; unknown={unknown}" if unknown else "")
                + (f"; missing={missing}" if missing else "")
            )
        return cls(
            proposal_id=value["proposal_id"],
            repository=value["repository"],
            base_sha=value["base_sha"],
            proposal_sha256=value["proposal_sha256"],
            promotion_receipt_sha256=value["promotion_receipt_sha256"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            materialization_receipt_sha256=value["materialization_receipt_sha256"],
            snapshot_receipt_sha256=value["snapshot_receipt_sha256"],
            candidate_commit_sha=value["candidate_commit_sha"],
            candidate_tree_sha=value["candidate_tree_sha"],
            worker_code_sha256=value["worker_code_sha256"],
            baseline_eval_sha256=value["baseline_eval_sha256"],
            candidate_eval_sha256=value["candidate_eval_sha256"],
            regression_proof_sha256=value["regression_proof_sha256"],
            runtime_provenance_sha256=value["runtime_provenance_sha256"],
            required_evals=_string_tuple(value["required_evals"], name="required_evals"),
            software_chain_complete=value["software_chain_complete"],
            ready_for_human_go=value["ready_for_human_go"],
            activation_authorized=value["activation_authorized"],
            automatic_activation=value["automatic_activation"],
            remote_publication_authorized=value["remote_publication_authorized"],
            fresh_physical_evidence_required=value["fresh_physical_evidence_required"],
            independent_collector_approver_required=value[
                "independent_collector_approver_required"
            ],
            missing_physical_gates=_string_tuple(
                value["missing_physical_gates"], name="missing_physical_gates"
            ),
            phase=value["phase"],
            authority=value["authority"],
            merge_authority=value["merge_authority"],
            schema=value["schema"],
        )

    @classmethod
    def from_json(cls, text: str) -> "QualificationPacket":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise QualificationPacketError("qualification packet JSON is invalid") from exc
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "phase": self.phase,
            "proposal_id": self.proposal_id,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "proposal_sha256": self.proposal_sha256,
            "promotion_receipt_sha256": self.promotion_receipt_sha256,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "materialization_receipt_sha256": self.materialization_receipt_sha256,
            "snapshot_receipt_sha256": self.snapshot_receipt_sha256,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_tree_sha": self.candidate_tree_sha,
            "worker_code_sha256": self.worker_code_sha256,
            "baseline_eval_sha256": self.baseline_eval_sha256,
            "candidate_eval_sha256": self.candidate_eval_sha256,
            "regression_proof_sha256": self.regression_proof_sha256,
            "runtime_provenance_sha256": self.runtime_provenance_sha256,
            "required_evals": list(self.required_evals),
            "software_chain_complete": self.software_chain_complete,
            "ready_for_human_go": self.ready_for_human_go,
            "activation_authorized": self.activation_authorized,
            "automatic_activation": self.automatic_activation,
            "remote_publication_authorized": self.remote_publication_authorized,
            "fresh_physical_evidence_required": self.fresh_physical_evidence_required,
            "independent_collector_approver_required": self.independent_collector_approver_required,
            "missing_physical_gates": list(self.missing_physical_gates),
            "authority": self.authority,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


def build_qualification_packet(
    *,
    proposal: ImprovementProposal,
    promotion: PromotionReceipt,
    snapshot: CandidateSnapshotReceipt,
    regression: CandidateRegressionProof,
    provenance: CandidateRuntimeProvenance,
) -> QualificationPacket:
    """Validate the software chain and emit a still-pending physical pilot packet."""

    if not isinstance(proposal, ImprovementProposal):
        raise QualificationPacketError("qualification requires ImprovementProposal")
    if not isinstance(promotion, PromotionReceipt):
        raise QualificationPacketError("qualification requires PromotionReceipt")
    if not isinstance(snapshot, CandidateSnapshotReceipt):
        raise QualificationPacketError("qualification requires CandidateSnapshotReceipt")
    if not isinstance(regression, CandidateRegressionProof):
        raise QualificationPacketError("qualification requires CandidateRegressionProof")
    if not isinstance(provenance, CandidateRuntimeProvenance):
        raise QualificationPacketError("qualification requires CandidateRuntimeProvenance")

    p_hash = proposal_sha256(proposal)
    if (
        promotion.proposal_id != proposal.proposal_id
        or promotion.proposal_sha256 != p_hash
        or promotion.repository != proposal.repository
        or promotion.base_sha != proposal.base_sha
        or promotion.required_evals != proposal.required_evals
    ):
        raise QualificationPacketError("promotion receipt is not bound to proposal")

    if (
        regression.proposal_id != proposal.proposal_id
        or regression.proposal_sha256 != p_hash
        or regression.promotion_receipt_sha256 != promotion.sha256
        or regression.task_id != promotion.task_id
        or regression.task_sha256 != promotion.task_sha256
        or regression.repository != promotion.repository
        or regression.base_sha != promotion.base_sha
        or regression.accepted is not True
    ):
        raise QualificationPacketError(
            "accepted regression proof is not bound to promotion chain"
        )

    if snapshot.task_sha256 != promotion.task_sha256:
        raise QualificationPacketError("candidate snapshot is bound to another task")

    if (
        provenance.materialization_receipt_sha256
        != snapshot.materialization_receipt_sha256
        or provenance.task_sha256 != snapshot.task_sha256
        or provenance.candidate_commit_sha != snapshot.candidate_commit_sha
        or provenance.candidate_tree_sha != snapshot.candidate_tree_sha
        or provenance.snapshot_tree_sha != snapshot.candidate_tree_sha
        or provenance.candidate_eval_sha256 != regression.candidate_eval_sha256
        or provenance.regression_proof_sha256 != regression.sha256
        or provenance.worker_code_sha256 != regression.candidate_code_sha256
        or provenance.accepted_regression is not True
        or provenance.authority != "evidence-only"
        or provenance.merge_authority != "human"
    ):
        raise QualificationPacketError(
            "runtime provenance is not bound to candidate evidence chain"
        )

    if (
        snapshot.authority != "evidence-only"
        or snapshot.merge_authority != "human"
        or snapshot.network_performed is not False
        or snapshot.repository_mutated is not False
    ):
        raise QualificationPacketError(
            "snapshot receipt is not the offline evidence-only boundary"
        )

    return QualificationPacket(
        proposal_id=proposal.proposal_id,
        repository=proposal.repository,
        base_sha=proposal.base_sha,
        proposal_sha256=p_hash,
        promotion_receipt_sha256=promotion.sha256,
        task_id=promotion.task_id,
        task_sha256=promotion.task_sha256,
        materialization_receipt_sha256=snapshot.materialization_receipt_sha256,
        snapshot_receipt_sha256=snapshot.sha256,
        candidate_commit_sha=snapshot.candidate_commit_sha,
        candidate_tree_sha=snapshot.candidate_tree_sha,
        worker_code_sha256=provenance.worker_code_sha256,
        baseline_eval_sha256=regression.baseline_eval_sha256,
        candidate_eval_sha256=regression.candidate_eval_sha256,
        regression_proof_sha256=regression.sha256,
        runtime_provenance_sha256=provenance.sha256,
        required_evals=proposal.required_evals,
        software_chain_complete=True,
        ready_for_human_go=False,
        activation_authorized=False,
        automatic_activation=False,
        remote_publication_authorized=False,
        fresh_physical_evidence_required=True,
        independent_collector_approver_required=True,
        missing_physical_gates=MISSING_PHYSICAL_GATES,
    )
