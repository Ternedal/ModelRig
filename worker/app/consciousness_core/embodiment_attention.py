"""C26-D semantic embodiment-change attention.

Evidence-bound C8 semantic inferences may become bounded embodiment_change
CognitionEvents. High-frequency gaze-state inference is deliberately excluded
from this autonomous attention seam.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .embodiment import EmbodimentState, InferredEmbodimentState
from .supervisor import CognitionEvent


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]

_EMBODIMENT_SALIENCE = {
    "action_outcome": 0.90,
    "reachability": 0.90,
    "locomotion_blocked": 1.00,
    "interaction_result": 0.95,
    "tracking_interpretation": 0.95,
}


class EmbodimentAttentionError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EmbodimentAttentionPlan(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/embodiment-attention-plan/v1"
    ]
    embodiment_state_ref: NonEmptyRef
    inference_ref: NonEmptyRef
    cognition_event: CognitionEvent | None
    model_calls: Literal[0]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EmbodimentAttentionPlan":
        if self.cognition_event is not None:
            if self.cognition_event.kind != "embodiment_change":
                raise ValueError(
                    "embodiment attention event must be embodiment_change"
                )
        return self


class EmbodimentAttentionAdmissionResult(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/embodiment-attention-admission/v1"
    ]
    plan: EmbodimentAttentionPlan
    cognition_event_admitted: bool
    supervisor_revision_before: Annotated[int, Field(ge=1, strict=True)]
    supervisor_revision_after: Annotated[int, Field(ge=1, strict=True)]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    body_mutation_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def admission_shape(self) -> "EmbodimentAttentionAdmissionResult":
        has_event = self.plan.cognition_event is not None
        if self.cognition_event_admitted != has_event:
            raise ValueError(
                "embodiment attention admission/event presence mismatch"
            )
        delta = self.supervisor_revision_after - self.supervisor_revision_before
        if has_event:
            if delta not in {0, 1}:
                raise ValueError(
                    "embodiment event admission may be idempotent or advance once"
                )
        elif delta != 0:
            raise ValueError(
                "non-event embodiment inference cannot change supervisor revision"
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


def embodiment_state_ref(
    state: EmbodimentState | Mapping[str, Any],
) -> str:
    try:
        value = (
            state
            if isinstance(state, EmbodimentState)
            else EmbodimentState.model_validate(state)
        )
    except ValidationError as exc:
        raise EmbodimentAttentionError("invalid EmbodimentState") from exc
    return _ref("embodiment-state", value)


def embodiment_inference_ref(
    inference: InferredEmbodimentState | Mapping[str, Any],
) -> str:
    try:
        value = (
            inference
            if isinstance(inference, InferredEmbodimentState)
            else InferredEmbodimentState.model_validate(inference)
        )
    except ValidationError as exc:
        raise EmbodimentAttentionError(
            "invalid InferredEmbodimentState"
        ) from exc
    return _ref("embodiment-inference", value)


def _validate_binding(
    state: EmbodimentState,
    inference: InferredEmbodimentState,
) -> None:
    if inference.cycle_id != state.cycle_id:
        raise EmbodimentAttentionError(
            "embodiment inference cycle mismatch"
        )
    if inference.person_id != state.person_id:
        raise EmbodimentAttentionError(
            "embodiment inference belongs to another person"
        )
    if inference.person_revision != state.person_revision:
        raise EmbodimentAttentionError(
            "embodiment inference Person Revision mismatch"
        )
    if inference.body_revision != state.body_revision:
        raise EmbodimentAttentionError(
            "embodiment inference body revision mismatch"
        )
    if not set(inference.evidence_observation_refs).issubset(
        set(state.observation_refs)
    ):
        raise EmbodimentAttentionError(
            "embodiment inference evidence is outside exact state"
        )


def plan_embodiment_attention(
    *,
    state: EmbodimentState | Mapping[str, Any],
    inference: InferredEmbodimentState | Mapping[str, Any],
) -> EmbodimentAttentionPlan:
    """Project one evidence-bound semantic inference into optional attention."""
    try:
        current = (
            state
            if isinstance(state, EmbodimentState)
            else EmbodimentState.model_validate(state)
        )
        inferred = (
            inference
            if isinstance(inference, InferredEmbodimentState)
            else InferredEmbodimentState.model_validate(inference)
        )
    except ValidationError as exc:
        raise EmbodimentAttentionError(
            "invalid embodiment attention input"
        ) from exc

    _validate_binding(current, inferred)
    state_ref = embodiment_state_ref(current)
    inference_ref = embodiment_inference_ref(inferred)

    salience = _EMBODIMENT_SALIENCE.get(inferred.inference_kind)
    if salience is None:
        return EmbodimentAttentionPlan(
            schema=(
                "kaliv-consciousness-core/"
                "embodiment-attention-plan/v1"
            ),
            embodiment_state_ref=state_ref,
            inference_ref=inference_ref,
            cognition_event=None,
            model_calls=0,
            production_activation=False,
        )

    source_ref = _ref(
        "embodiment-attention",
        {
            "state_ref": state_ref,
            "inference_ref": inference_ref,
        },
    )
    event_id = "cevt-" + hashlib.sha256(
        ("embodiment-change-v1|" + source_ref).encode("utf-8")
    ).hexdigest()[:32]
    event = CognitionEvent(
        schema="kaliv-consciousness-core/cognition-event/v1",
        event_id=event_id,
        kind="embodiment_change",
        source_ref=source_ref,
        summary=(
            f"Inferred embodiment change ({inferred.inference_kind}, "
            f"confidence {inferred.confidence:.2f}): "
            f"{inferred.proposition}"
        ),
        salience=salience,
        observed_sequence=current.last_observed_sequence,
        production_activation=False,
    )
    return EmbodimentAttentionPlan(
        schema=(
            "kaliv-consciousness-core/"
            "embodiment-attention-plan/v1"
        ),
        embodiment_state_ref=state_ref,
        inference_ref=inference_ref,
        cognition_event=event,
        model_calls=0,
        production_activation=False,
    )
