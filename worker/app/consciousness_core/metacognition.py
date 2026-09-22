"""C5 prediction, outcome and metacognition contracts.

This module is pure deterministic Core logic. It owns no route, durable store,
Memory 4 writer, Agent 3 executor, scheduler, BodyRig mutation, or model session.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Mapping, Any

from pydantic import ConfigDict, BaseModel, Field, ValidationError

from .contracts import CognitiveProfile, ThoughtProposal, ThoughtRequest


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
SignedUnit = Annotated[
    float,
    Field(ge=-1.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]

ObservationKind = Literal[
    "user_report",
    "tool_result",
    "embodiment",
    "core_observation",
    "inferred",
]
ExpectedObservationKind = Literal[
    "any",
    "user_report",
    "tool_result",
    "embodiment",
    "core_observation",
    "inferred",
]
PredictionRelation = Literal[
    "supports",
    "partially_supports",
    "contradicts",
    "unknown",
]


class MetacognitionContractError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class PredictionRecord(StrictModel):
    schema: Literal["kaliv-consciousness-core/prediction-record/v1"]
    prediction_id: Annotated[str, Field(pattern=r"^pred-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    subject_ref: NonEmptyRef
    proposition: BoundedText
    confidence_before: UnitInterval
    expected_observation_kind: ExpectedObservationKind
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    created_from_thought_proposal_ref: NonEmptyRef
    status: Literal["open", "resolved", "expired"]
    production_activation: Literal[False]


class OutcomeObservation(StrictModel):
    schema: Literal["kaliv-consciousness-core/outcome-observation/v1"]
    outcome_id: Annotated[str, Field(pattern=r"^out-[a-f0-9]{32}$")]
    prediction_id: Annotated[str, Field(pattern=r"^pred-[a-f0-9]{32}$")]
    observed_proposition: BoundedText
    observation_kind: ObservationKind
    prediction_relation: PredictionRelation
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    confidence: UnitInterval
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    production_activation: Literal[False]


class PredictionResolution(StrictModel):
    schema: Literal["kaliv-consciousness-core/prediction-resolution/v1"]
    resolution_id: Annotated[str, Field(pattern=r"^pres-[a-f0-9]{32}$")]
    prediction_id: Annotated[str, Field(pattern=r"^pred-[a-f0-9]{32}$")]
    outcome_id: Annotated[str, Field(pattern=r"^out-[a-f0-9]{32}$")]
    result: Literal["match", "partial", "mismatch", "indeterminate"]
    error_score: UnitInterval
    confidence_delta_candidate: SignedUnit
    evidence_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=64)]
    production_activation: Literal[False]


class MetacognitiveState(StrictModel):
    schema: Literal["kaliv-consciousness-core/metacognitive-state/v1"]
    state_id: Annotated[str, Field(pattern=r"^meta-[a-f0-9]{32}$")]
    revision: Annotated[int, Field(ge=1, strict=True)]
    current_task_uncertainty: UnitInterval
    known_capability_limitations: Annotated[
        list[BoundedText],
        Field(max_length=32),
    ]
    unresolved_contradiction_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=32),
    ]
    recent_resolution_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=32),
    ]
    decomposition_required: bool
    verification_required: bool
    confidence_ceiling: UnitInterval
    production_activation: Literal[False]


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bounded_unique(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
        if len(out) >= limit:
            break
    return out


def prediction_from_proposal(
    request: ThoughtRequest | Mapping[str, Any],
    proposal: ThoughtProposal | Mapping[str, Any],
    *,
    outcome_index: int,
    subject_ref: str,
    expected_observation_kind: ExpectedObservationKind,
    source_refs: list[str],
) -> PredictionRecord:
    """Convert one model proposal into an OPEN Core-owned prediction."""
    try:
        req = (
            request
            if isinstance(request, ThoughtRequest)
            else ThoughtRequest.model_validate(request)
        )
        prop = (
            proposal
            if isinstance(proposal, ThoughtProposal)
            else ThoughtProposal.model_validate(proposal)
        )
    except ValidationError as exc:
        raise MetacognitionContractError("invalid thought input for prediction") from exc

    if prop.request_id != req.request_id:
        raise MetacognitionContractError("proposal/request binding mismatch")
    if outcome_index < 0 or outcome_index >= len(prop.predicted_outcomes):
        raise MetacognitionContractError("predicted outcome index out of range")
    if not source_refs:
        raise MetacognitionContractError("prediction requires source provenance")

    candidate = prop.predicted_outcomes[outcome_index]
    seed = {
        "cycle_id": req.cycle_id,
        "proposal_id": prop.proposal_id,
        "outcome_index": outcome_index,
        "subject_ref": subject_ref,
    }
    prediction_id = "pred-" + _canonical_digest(seed)[:32]
    refs = _bounded_unique(
        [f"thought-proposal:{prop.proposal_id}", *source_refs],
        32,
    )
    try:
        return PredictionRecord(
            schema="kaliv-consciousness-core/prediction-record/v1",
            prediction_id=prediction_id,
            cycle_id=req.cycle_id,
            subject_ref=subject_ref,
            proposition=candidate.summary,
            confidence_before=candidate.confidence,
            expected_observation_kind=expected_observation_kind,
            source_refs=refs,
            created_from_thought_proposal_ref=f"thought-proposal:{prop.proposal_id}",
            status="open",
            production_activation=False,
        )
    except ValidationError as exc:
        raise MetacognitionContractError("invalid prediction candidate") from exc


def resolve_prediction(
    prediction: PredictionRecord | Mapping[str, Any],
    outcome: OutcomeObservation | Mapping[str, Any],
) -> PredictionResolution:
    """Resolve from structured evidence; no model-authored score is accepted."""
    try:
        pred = (
            prediction
            if isinstance(prediction, PredictionRecord)
            else PredictionRecord.model_validate(prediction)
        )
        obs = (
            outcome
            if isinstance(outcome, OutcomeObservation)
            else OutcomeObservation.model_validate(outcome)
        )
    except ValidationError as exc:
        raise MetacognitionContractError("invalid prediction/outcome contract") from exc

    if pred.status != "open":
        raise MetacognitionContractError("only open predictions can be resolved")
    if obs.prediction_id != pred.prediction_id:
        raise MetacognitionContractError("outcome belongs to another prediction")

    kind_matches = (
        pred.expected_observation_kind == "any"
        or pred.expected_observation_kind == obs.observation_kind
    )
    if not kind_matches:
        result = "indeterminate"
        error_score = 0.5
        confidence_delta = 0.0
    elif obs.prediction_relation == "supports":
        result = "match"
        error_score = 0.0
        confidence_delta = 0.05
    elif obs.prediction_relation == "partially_supports":
        result = "partial"
        error_score = 0.5
        confidence_delta = -0.05
    elif obs.prediction_relation == "contradicts":
        result = "mismatch"
        error_score = 1.0
        confidence_delta = -0.20
    else:
        result = "indeterminate"
        error_score = 0.5
        confidence_delta = 0.0

    seed = {
        "prediction_id": pred.prediction_id,
        "outcome_id": obs.outcome_id,
        "result": result,
    }
    refs = _bounded_unique(
        [
            *pred.source_refs,
            *obs.source_refs,
            f"outcome:{obs.outcome_id}",
        ],
        64,
    )
    return PredictionResolution(
        schema="kaliv-consciousness-core/prediction-resolution/v1",
        resolution_id="pres-" + _canonical_digest(seed)[:32],
        prediction_id=pred.prediction_id,
        outcome_id=obs.outcome_id,
        result=result,
        error_score=error_score,
        confidence_delta_candidate=confidence_delta,
        evidence_refs=refs,
        production_activation=False,
    )


def initial_metacognitive_state(*, self_ref: str) -> MetacognitiveState:
    state_id = "meta-" + _canonical_digest({"self_ref": self_ref})[:32]
    return MetacognitiveState(
        schema="kaliv-consciousness-core/metacognitive-state/v1",
        state_id=state_id,
        revision=1,
        current_task_uncertainty=0.5,
        known_capability_limitations=[],
        unresolved_contradiction_refs=[],
        recent_resolution_refs=[],
        decomposition_required=False,
        verification_required=False,
        confidence_ceiling=0.75,
        production_activation=False,
    )


def apply_resolution(
    state: MetacognitiveState | Mapping[str, Any],
    resolution: PredictionResolution | Mapping[str, Any],
    cognitive_profile: CognitiveProfile | Mapping[str, Any],
) -> MetacognitiveState:
    """Deterministically adapt cognitive strategy without persisting model identity."""
    try:
        current = (
            state
            if isinstance(state, MetacognitiveState)
            else MetacognitiveState.model_validate(state)
        )
        resolved = (
            resolution
            if isinstance(resolution, PredictionResolution)
            else PredictionResolution.model_validate(resolution)
        )
        profile = (
            cognitive_profile
            if isinstance(cognitive_profile, CognitiveProfile)
            else CognitiveProfile.model_validate(cognitive_profile)
        )
    except ValidationError as exc:
        raise MetacognitionContractError("invalid metacognitive update input") from exc

    capability = (
        profile.reasoning_depth
        + profile.planning_capacity
        + profile.uncertainty_calibration
    ) / 3.0
    confidence_ceiling = max(0.35, min(0.98, 0.35 + 0.60 * capability))

    limitations = list(current.known_capability_limitations)
    if profile.reasoning_depth < 0.5:
        limitations.append("limited reasoning depth in current cognitive profile")
    if profile.planning_capacity < 0.5:
        limitations.append("limited planning capacity in current cognitive profile")
    if profile.uncertainty_calibration < 0.5:
        limitations.append("weak uncertainty calibration in current cognitive profile")

    verification_required = (
        resolved.result in {"mismatch", "indeterminate"}
        or current.verification_required
    )
    decomposition_required = (
        profile.reasoning_depth < 0.5
        or profile.planning_capacity < 0.5
        or resolved.error_score >= 0.75
        or current.decomposition_required
    )
    uncertainty = max(
        1.0 - confidence_ceiling,
        resolved.error_score * 0.75,
    )
    contradiction_refs = list(current.unresolved_contradiction_refs)
    if resolved.result == "mismatch":
        contradiction_refs.append(f"prediction-resolution:{resolved.resolution_id}")

    return MetacognitiveState(
        schema="kaliv-consciousness-core/metacognitive-state/v1",
        state_id=current.state_id,
        revision=current.revision + 1,
        current_task_uncertainty=min(1.0, uncertainty),
        known_capability_limitations=_bounded_unique(limitations, 32),
        unresolved_contradiction_refs=_bounded_unique(contradiction_refs, 32),
        recent_resolution_refs=_bounded_unique(
            [
                *current.recent_resolution_refs,
                f"prediction-resolution:{resolved.resolution_id}",
            ][-32:],
            32,
        ),
        decomposition_required=decomposition_required,
        verification_required=verification_required,
        confidence_ceiling=confidence_ceiling,
        production_activation=False,
    )
