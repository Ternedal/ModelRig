"""C9-A persistent goal and intention contracts for Consciousness Core.

This slice provides serializable Core-owned goal state and deterministic
admission/transition/arbitration. It deliberately owns no scheduler, executor,
tool gate or durable database.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]

GoalKind = Literal[
    "USER_GOAL",
    "PROJECT_GOAL",
    "RELATIONSHIP_GOAL",
    "CONVERSATION_GOAL",
    "MAINTENANCE_GOAL",
    "SELF_MAINTENANCE_GOAL",
    "CURIOSITY_GOAL",
]
GoalStatus = Literal[
    "proposed",
    "active",
    "paused",
    "completed",
    "abandoned",
    "blocked",
]
GoalCandidateSource = Literal[
    "user_explicit",
    "project_state",
    "relationship_state",
    "maintenance_policy",
    "thought_engine",
    "memory_reference",
]
AdmissionAuthority = Literal[
    "user_explicit",
    "operator_review",
    "existing_project_commitment",
    "maintenance_policy",
]
RequiredAuthority = Literal[
    "none",
    "agent3",
    "bodyrig",
    "voicerig",
    "memory4",
    "human_review",
]


class GoalContractError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class GoalCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/goal-candidate/v1"]
    candidate_id: Annotated[str, Field(pattern=r"^gcand-[a-f0-9]{32}$")]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    kind: GoalKind
    statement: BoundedText
    source_kind: GoalCandidateSource
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    suggested_priority: UnitInterval
    confidence: UnitInterval
    parent_goal_ref: NonEmptyRef | None
    constraints: Annotated[list[BoundedText], Field(max_length=32)]
    success_conditions: Annotated[list[BoundedText], Field(min_length=1, max_length=32)]
    production_activation: Literal[False]


class GoalAdmissionEvidence(StrictModel):
    schema: Literal["kaliv-consciousness-core/goal-admission-evidence/v1"]
    candidate_id: Annotated[str, Field(pattern=r"^gcand-[a-f0-9]{32}$")]
    authority: AdmissionAuthority
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    admitted_priority: UnitInterval
    admitted_sequence: Annotated[int, Field(ge=0, strict=True)]
    production_activation: Literal[False]


class GoalRecord(StrictModel):
    schema: Literal["kaliv-consciousness-core/goal-record/v1"]
    goal_id: Annotated[str, Field(pattern=r"^goal-[a-f0-9]{32}$")]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    kind: GoalKind
    statement: BoundedText
    source_kind: GoalCandidateSource
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=64)]
    admission_authority: AdmissionAuthority
    priority: UnitInterval
    confidence: UnitInterval
    status: GoalStatus
    parent_goal_ref: NonEmptyRef | None
    constraints: Annotated[list[BoundedText], Field(max_length=32)]
    success_conditions: Annotated[list[BoundedText], Field(min_length=1, max_length=32)]
    created_sequence: Annotated[int, Field(ge=0, strict=True)]
    last_review_sequence: Annotated[int, Field(ge=0, strict=True)]
    expiry_sequence: Annotated[int | None, Field(ge=0, strict=True)] = None
    transition_evidence_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    production_activation: Literal[False]


class IntentionRecord(StrictModel):
    schema: Literal["kaliv-consciousness-core/intention-record/v1"]
    intention_id: Annotated[str, Field(pattern=r"^intent-[a-f0-9]{32}$")]
    goal_id: Annotated[str, Field(pattern=r"^goal-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    statement: BoundedText
    rationale_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    predicted_outcome_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    required_authority: RequiredAuthority
    status: Literal["candidate", "selected", "dispatched", "satisfied", "failed", "cancelled"]
    production_activation: Literal[False]


class Agent3IntentHandoff(StrictModel):
    schema: Literal["kaliv-consciousness-core/agent3-intent-handoff/v1"]
    goal_id: Annotated[str, Field(pattern=r"^goal-[a-f0-9]{32}$")]
    intention_id: Annotated[str, Field(pattern=r"^intent-[a-f0-9]{32}$")]
    statement: BoundedText
    rationale_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    predicted_outcome_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    required_authority: Literal["agent3"]
    execution_started: Literal[False]
    production_activation: Literal[False]


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def admit_goal(
    candidate: GoalCandidate | Mapping[str, Any],
    evidence: GoalAdmissionEvidence | Mapping[str, Any],
) -> GoalRecord:
    """Turn a candidate into an active Core goal only with external admission."""
    try:
        cand = (
            candidate
            if isinstance(candidate, GoalCandidate)
            else GoalCandidate.model_validate(candidate)
        )
        admission = (
            evidence
            if isinstance(evidence, GoalAdmissionEvidence)
            else GoalAdmissionEvidence.model_validate(evidence)
        )
    except ValidationError as exc:
        raise GoalContractError("invalid goal admission input") from exc

    if admission.candidate_id != cand.candidate_id:
        raise GoalContractError("goal admission belongs to another candidate")

    # A ThoughtEngine suggestion can be considered only after independent
    # admission. The model itself is intentionally absent from this authority enum.
    if cand.source_kind == "thought_engine" and admission.authority not in {
        "user_explicit",
        "operator_review",
        "existing_project_commitment",
        "maintenance_policy",
    }:
        raise GoalContractError("ThoughtEngine cannot activate a persistent goal")

    if cand.kind == "CURIOSITY_GOAL" and admission.authority == "maintenance_policy":
        # Curiosity can exist as a goal, but this grants no external action.
        pass

    source_refs = list(dict.fromkeys([*cand.source_refs, *admission.source_refs]))[:64]
    seed = {
        "candidate_id": cand.candidate_id,
        "authority": admission.authority,
        "sequence": admission.admitted_sequence,
    }
    return GoalRecord(
        schema="kaliv-consciousness-core/goal-record/v1",
        goal_id="goal-" + _digest(seed)[:32],
        self_id=cand.self_id,
        person_revision=cand.person_revision,
        kind=cand.kind,
        statement=cand.statement,
        source_kind=cand.source_kind,
        source_refs=source_refs,
        admission_authority=admission.authority,
        priority=admission.admitted_priority,
        confidence=cand.confidence,
        status="active",
        parent_goal_ref=cand.parent_goal_ref,
        constraints=cand.constraints,
        success_conditions=cand.success_conditions,
        created_sequence=admission.admitted_sequence,
        last_review_sequence=admission.admitted_sequence,
        expiry_sequence=None,
        transition_evidence_refs=[],
        production_activation=False,
    )


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "active": {"paused", "completed", "abandoned", "blocked"},
    "paused": {"active", "abandoned", "blocked"},
    "blocked": {"active", "abandoned"},
    "proposed": {"active", "abandoned"},
    "completed": set(),
    "abandoned": set(),
}


def transition_goal(
    goal: GoalRecord | Mapping[str, Any],
    *,
    new_status: GoalStatus,
    sequence: int,
    evidence_refs: list[str],
) -> GoalRecord:
    try:
        current = (
            goal
            if isinstance(goal, GoalRecord)
            else GoalRecord.model_validate(goal)
        )
    except ValidationError as exc:
        raise GoalContractError("invalid GoalRecord") from exc

    allowed = _ALLOWED_TRANSITIONS.get(current.status, set())
    if new_status not in allowed:
        raise GoalContractError(
            f"invalid goal transition {current.status}->{new_status}"
        )
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise GoalContractError("goal transition sequence must be integer")
    if sequence < current.last_review_sequence:
        raise GoalContractError("goal transition sequence moved backwards")
    if not evidence_refs:
        raise GoalContractError("goal transition requires evidence")
    if new_status == "completed" and not current.success_conditions:
        raise GoalContractError("goal completion requires declared success conditions")

    return current.model_copy(
        update={
            "status": new_status,
            "last_review_sequence": sequence,
            "transition_evidence_refs": list(
                dict.fromkeys([*current.transition_evidence_refs, *evidence_refs])
            )[-64:],
        }
    )


def select_next_goal(goals: list[GoalRecord | Mapping[str, Any]]) -> GoalRecord | None:
    """Deterministic arbitration; no model/provider input."""
    parsed: list[GoalRecord] = []
    try:
        for item in goals:
            parsed.append(
                item if isinstance(item, GoalRecord) else GoalRecord.model_validate(item)
            )
    except ValidationError as exc:
        raise GoalContractError("invalid goal arbitration input") from exc

    eligible = [
        item
        for item in parsed
        if item.status == "active"
        and (
            item.expiry_sequence is None
            or item.last_review_sequence <= item.expiry_sequence
        )
    ]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda item: (-item.priority, item.created_sequence, item.goal_id),
    )[0]


def select_intention(
    goal: GoalRecord | Mapping[str, Any],
    *,
    cycle_id: str,
    statement: str,
    rationale_refs: list[str],
    predicted_outcome_refs: list[str],
    required_authority: RequiredAuthority,
) -> IntentionRecord:
    try:
        current = (
            goal
            if isinstance(goal, GoalRecord)
            else GoalRecord.model_validate(goal)
        )
    except ValidationError as exc:
        raise GoalContractError("invalid GoalRecord for intention") from exc

    if current.status != "active":
        raise GoalContractError("only active goals can select intentions")
    if not rationale_refs:
        raise GoalContractError("intention requires rationale provenance")

    seed = {
        "goal_id": current.goal_id,
        "cycle_id": cycle_id,
        "statement": statement,
        "required_authority": required_authority,
    }
    try:
        return IntentionRecord(
            schema="kaliv-consciousness-core/intention-record/v1",
            intention_id="intent-" + _digest(seed)[:32],
            goal_id=current.goal_id,
            cycle_id=cycle_id,
            statement=statement,
            rationale_refs=list(dict.fromkeys(rationale_refs))[:32],
            predicted_outcome_refs=list(dict.fromkeys(predicted_outcome_refs))[:32],
            required_authority=required_authority,
            status="selected",
            production_activation=False,
        )
    except ValidationError as exc:
        raise GoalContractError("invalid intention selection") from exc


def build_agent3_handoff(
    intention: IntentionRecord | Mapping[str, Any],
) -> Agent3IntentHandoff:
    try:
        item = (
            intention
            if isinstance(intention, IntentionRecord)
            else IntentionRecord.model_validate(intention)
        )
    except ValidationError as exc:
        raise GoalContractError("invalid IntentionRecord") from exc

    if item.status != "selected":
        raise GoalContractError("only selected intentions can be handed off")
    if item.required_authority != "agent3":
        raise GoalContractError("intention does not require Agent 3")

    return Agent3IntentHandoff(
        schema="kaliv-consciousness-core/agent3-intent-handoff/v1",
        goal_id=item.goal_id,
        intention_id=item.intention_id,
        statement=item.statement,
        rationale_refs=item.rationale_refs,
        predicted_outcome_refs=item.predicted_outcome_refs,
        required_authority="agent3",
        execution_started=False,
        production_activation=False,
    )
