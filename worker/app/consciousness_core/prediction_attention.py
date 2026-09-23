"""C26-B prediction-mismatch attention admission.

Structured C5 evidence may create one bounded prediction_error CognitionEvent
only when Core deterministically resolves an open prediction as a mismatch.
No model, scheduler, persistence or execution authority is introduced here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .metacognition import (
    OutcomeObservation,
    PredictionRecord,
    PredictionResolution,
    resolve_prediction,
)
from .supervisor import CognitionEvent


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class PredictionAttentionError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class PredictionOutcomePlan(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/prediction-outcome-plan/v1"
    ]
    resolution: PredictionResolution
    resolution_ref: NonEmptyRef
    outcome_ref: NonEmptyRef
    cognition_event: CognitionEvent | None
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    model_calls: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "PredictionOutcomePlan":
        should_admit = self.resolution.result == "mismatch"
        if should_admit:
            if self.resolution.error_score != 1.0:
                raise ValueError(
                    "mismatch attention requires exact error_score=1.0"
                )
            if self.cognition_event is None:
                raise ValueError(
                    "mismatch prediction requires one cognition event"
                )
            if self.cognition_event.kind != "prediction_error":
                raise ValueError(
                    "mismatch attention must be prediction_error"
                )
            if self.cognition_event.observed_sequence != self.observed_sequence:
                raise ValueError(
                    "prediction-error event sequence mismatch"
                )
        elif self.cognition_event is not None:
            raise ValueError(
                "non-mismatch prediction outcome cannot create cognition event"
            )
        return self


class PredictionOutcomeAdmissionResult(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/prediction-outcome-admission/v1"
    ]
    plan: PredictionOutcomePlan
    cognition_event_admitted: bool
    supervisor_revision_before: Annotated[int, Field(ge=1, strict=True)]
    supervisor_revision_after: Annotated[int, Field(ge=1, strict=True)]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def admission_shape(self) -> "PredictionOutcomeAdmissionResult":
        has_event = self.plan.cognition_event is not None
        if self.cognition_event_admitted != has_event:
            raise ValueError(
                "prediction outcome admission/event presence mismatch"
            )
        delta = self.supervisor_revision_after - self.supervisor_revision_before
        if has_event:
            if delta not in {0, 1}:
                raise ValueError(
                    "event admission may be idempotent or advance one revision"
                )
        elif delta != 0:
            raise ValueError(
                "non-event outcome cannot change supervisor revision"
            )
        return self


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _ref(prefix: str, value: Any) -> str:
    return prefix + ":" + hashlib.sha256(_canonical_json(value)).hexdigest()


def prediction_resolution_ref(
    resolution: PredictionResolution | Mapping[str, Any],
) -> str:
    try:
        value = (
            resolution
            if isinstance(resolution, PredictionResolution)
            else PredictionResolution.model_validate(resolution)
        )
    except ValidationError as exc:
        raise PredictionAttentionError(
            "invalid PredictionResolution"
        ) from exc
    return _ref("prediction-resolution", value)


def outcome_observation_ref(
    outcome: OutcomeObservation | Mapping[str, Any],
) -> str:
    try:
        value = (
            outcome
            if isinstance(outcome, OutcomeObservation)
            else OutcomeObservation.model_validate(outcome)
        )
    except ValidationError as exc:
        raise PredictionAttentionError(
            "invalid OutcomeObservation"
        ) from exc
    return _ref("outcome-observation", value)


def prediction_attention_ref(
    *,
    resolution: PredictionResolution,
    outcome: OutcomeObservation,
) -> str:
    if resolution.prediction_id != outcome.prediction_id:
        raise PredictionAttentionError(
            "resolution/outcome prediction binding mismatch"
        )
    if resolution.outcome_id != outcome.outcome_id:
        raise PredictionAttentionError(
            "resolution belongs to another outcome"
        )
    return _ref(
        "prediction-attention",
        {
            "resolution": resolution.model_dump(mode="json"),
            "outcome": outcome.model_dump(mode="json"),
        },
    )


def _prediction_error_event(
    *,
    resolution: PredictionResolution,
    outcome: OutcomeObservation,
) -> CognitionEvent:
    if resolution.result != "mismatch" or resolution.error_score != 1.0:
        raise PredictionAttentionError(
            "only exact prediction mismatch may create prediction_error event"
        )
    source_ref = prediction_attention_ref(
        resolution=resolution,
        outcome=outcome,
    )
    event_id = "cevt-" + hashlib.sha256(
        ("prediction-error-v1|" + source_ref).encode("utf-8")
    ).hexdigest()[:32]
    return CognitionEvent(
        schema="kaliv-consciousness-core/cognition-event/v1",
        event_id=event_id,
        kind="prediction_error",
        source_ref=source_ref,
        summary=(
            f"Prediction {resolution.prediction_id} was contradicted by "
            f"structured {outcome.observation_kind} evidence; Core resolved "
            "the prediction as mismatch with error score 1.0."
        ),
        salience=1.0,
        observed_sequence=outcome.observed_sequence,
        production_activation=False,
    )


def plan_prediction_outcome(
    *,
    prediction: PredictionRecord | Mapping[str, Any],
    outcome: OutcomeObservation | Mapping[str, Any],
) -> PredictionOutcomePlan:
    """Resolve one structured outcome and optionally project mismatch attention."""
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
        raise PredictionAttentionError(
            "invalid prediction outcome admission input"
        ) from exc

    resolution = resolve_prediction(pred, obs)
    resolution_reference = prediction_resolution_ref(resolution)
    outcome_reference = outcome_observation_ref(obs)

    event = (
        _prediction_error_event(
            resolution=resolution,
            outcome=obs,
        )
        if resolution.result == "mismatch"
        else None
    )

    return PredictionOutcomePlan(
        schema=(
            "kaliv-consciousness-core/"
            "prediction-outcome-plan/v1"
        ),
        resolution=resolution,
        resolution_ref=resolution_reference,
        outcome_ref=outcome_reference,
        cognition_event=event,
        observed_sequence=obs.observed_sequence,
        model_calls=0,
        production_activation=False,
    )
