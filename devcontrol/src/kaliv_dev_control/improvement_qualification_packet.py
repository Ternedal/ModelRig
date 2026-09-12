"""Non-authorizing RSI qualification packet before DC-L15/DC-L16 physical gates.

The packet proves that the software/evidence chain is internally bound from one
ImprovementProposal through human-signed promotion, local candidate collection,
regression proof and runtime provenance.  It deliberately cannot satisfy the
physical or human gates that remain outside software.

A successfully constructed packet therefore still reports
``ready_for_human_go = False`` and ``activation_authorized = False``.  Fresh
physical I0b evidence, exact frozen-main confirmation, independent human review
and the final pilot decision remain external requirements.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

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
            raise QualificationPacketError("physical qualification requirements may not be relaxed")
        if self.missing_physical_gates != MISSING_PHYSICAL_GATES:
            raise QualificationPacketError(
                "qualification packet must preserve all external physical/human gates"
            )
        if not self.required_evals or len(self.required_evals) != len(set(self.required_evals)):
            raise QualificationPacketError("required evals are empty or duplicated")

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
    """Validate the complete software chain and emit a still-pending pilot packet."""

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
        raise QualificationPacketError("accepted regression proof is not bound to promotion chain")

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
        raise QualificationPacketError("runtime provenance is not bound to candidate evidence chain")

    if (
        snapshot.authority != "evidence-only"
        or snapshot.merge_authority != "human"
        or snapshot.network_performed is not False
        or snapshot.repository_mutated is not False
    ):
        raise QualificationPacketError("snapshot receipt is not the offline evidence-only boundary")

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
