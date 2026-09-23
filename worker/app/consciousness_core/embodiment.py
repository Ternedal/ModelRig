"""C8-A embodiment observation contracts and deterministic mock loop.

C8-A is read-only with respect to embodiment authority. BodyRig remains the body
identity / Movement Identity / Motor State authority; renderers and observers
report evidence only.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]

ObservationKind = Literal[
    "pose",
    "position",
    "orientation",
    "gaze",
    "locomotion",
    "gesture",
    "expression",
    "speech_motion",
    "contact",
    "interaction",
    "tracking",
]
CoordinateSpace = Literal["body", "world", "renderer", "none"]
TrackingHealth = Literal["ok", "degraded", "lost", "unavailable"]
InferenceKind = Literal[
    "action_outcome",
    "reachability",
    "gaze_state",
    "locomotion_blocked",
    "interaction_result",
    "tracking_interpretation",
]


class EmbodimentContractError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class SemanticBodyIntent(StrictModel):
    """High-level semantics only; no renderer/joint/blendshape controls."""

    schema: Literal["kaliv-consciousness-core/semantic-body-intent/v1"]
    intent_id: Annotated[str, Field(pattern=r"^bintent-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    affect_labels: Annotated[list[str], Field(max_length=16)]
    intent: BoundedText
    expressive_intensity: UnitInterval
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    production_activation: Literal[False]


class PerformedBodyStateRef(StrictModel):
    """Reference to BodyRig-authoritative performed state."""

    schema: Literal["kaliv-consciousness-core/performed-body-state-ref/v1"]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    body_revision: Annotated[str, Field(pattern=r"^body-r[0-9]{4,}$")]
    body_id_ref: NonEmptyRef
    bodycue_ref: NonEmptyRef
    motor_state_ref: NonEmptyRef
    motor_sequence: Annotated[int, Field(ge=0, strict=True)]
    source_ref: NonEmptyRef
    production_activation: Literal[False]


ObservationScalar = str | float | int | bool


class EmbodimentObservation(StrictModel):
    schema: Literal["kaliv-consciousness-core/embodiment-observation/v1"]
    observation_id: Annotated[str, Field(pattern=r"^eobs-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    body_revision: Annotated[str, Field(pattern=r"^body-r[0-9]{4,}$")]
    motor_state_ref: NonEmptyRef
    renderer_ref: NonEmptyRef
    observation_kind: ObservationKind
    coordinate_space: CoordinateSpace
    observed_values: dict[str, ObservationScalar]
    confidence: UnitInterval
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def bound_values(self) -> "EmbodimentObservation":
        if len(self.observed_values) > 32:
            raise ValueError("embodiment observation has too many values")
        for key, value in self.observed_values.items():
            if (
                not isinstance(key, str)
                or not key
                or key != key.strip()
                or len(key) > 64
            ):
                raise ValueError("embodiment observation key is invalid")
            if isinstance(value, str):
                if len(value) > 256:
                    raise ValueError("embodiment observation string is too long")
            elif type(value) is float and not math.isfinite(value):
                raise ValueError("embodiment observation float must be finite")
            elif type(value) not in {bool, int, float}:
                raise ValueError("embodiment observation scalar type is invalid")
        return self


class EmbodimentState(StrictModel):
    schema: Literal["kaliv-consciousness-core/embodiment-state/v1"]
    state_id: Annotated[str, Field(pattern=r"^estate-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    body_revision: Annotated[str, Field(pattern=r"^body-r[0-9]{4,}$")]
    performed_motor_state_ref: NonEmptyRef
    performed_motor_sequence: Annotated[int, Field(ge=0, strict=True)]
    observation_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    last_observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    tracking_health: TrackingHealth
    observation_confidence: UnitInterval
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=64)]
    production_activation: Literal[False]


class InferredEmbodimentState(StrictModel):
    """Explicit inference; never masquerades as raw renderer observation."""

    schema: Literal["kaliv-consciousness-core/inferred-embodiment-state/v1"]
    inference_id: Annotated[str, Field(pattern=r"^einf-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    body_revision: Annotated[str, Field(pattern=r"^body-r[0-9]{4,}$")]
    inference_kind: InferenceKind
    proposition: BoundedText
    confidence: UnitInterval
    evidence_observation_refs: Annotated[
        list[NonEmptyRef],
        Field(min_length=1, max_length=32),
    ]
    production_activation: Literal[False]


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_embodiment_state(
    performed: PerformedBodyStateRef | Mapping[str, Any],
    observations: list[EmbodimentObservation | Mapping[str, Any]],
) -> EmbodimentState:
    """Bind observations to the exact BodyRig-performed state and reject drift."""
    try:
        perf = (
            performed
            if isinstance(performed, PerformedBodyStateRef)
            else PerformedBodyStateRef.model_validate(performed)
        )
        parsed = [
            item
            if isinstance(item, EmbodimentObservation)
            else EmbodimentObservation.model_validate(item)
            for item in observations
        ]
    except ValidationError as exc:
        raise EmbodimentContractError("invalid embodiment state input") from exc

    seen_ids: set[str] = set()
    seen_sequences: set[int] = set()
    for item in parsed:
        if item.observation_id in seen_ids:
            raise EmbodimentContractError("duplicate embodiment observation id")
        if item.observed_sequence in seen_sequences:
            raise EmbodimentContractError("duplicate embodiment observation sequence")
        seen_ids.add(item.observation_id)
        seen_sequences.add(item.observed_sequence)

        if item.cycle_id != perf.cycle_id:
            raise EmbodimentContractError("observation cognitive cycle mismatch")
        if item.person_id != perf.person_id:
            raise EmbodimentContractError("observation belongs to another person")
        if item.person_revision != perf.person_revision:
            raise EmbodimentContractError("observation Person Revision mismatch")
        if item.body_revision != perf.body_revision:
            raise EmbodimentContractError("observation body revision mismatch")
        if item.motor_state_ref != perf.motor_state_ref:
            raise EmbodimentContractError("observation Motor State mismatch")
        if item.observed_sequence < perf.motor_sequence:
            raise EmbodimentContractError("stale observation predates performed Motor State")

    ordered = sorted(parsed, key=lambda x: x.observed_sequence)
    last_sequence = ordered[-1].observed_sequence if ordered else perf.motor_sequence
    confidence = min((x.confidence for x in ordered), default=0.0)

    if not ordered:
        health: TrackingHealth = "unavailable"
    elif any(
        x.observation_kind == "tracking"
        and str(x.observed_values.get("status", "")).casefold() == "lost"
        for x in ordered
    ):
        health = "lost"
    elif confidence < 0.5:
        health = "degraded"
    else:
        health = "ok"

    source_refs: list[str] = [perf.source_ref]
    for item in ordered:
        source_refs.extend(item.source_refs)
    unique_sources = list(dict.fromkeys(source_refs))[:64]

    seed = {
        "motor_state_ref": perf.motor_state_ref,
        "motor_sequence": perf.motor_sequence,
        "observations": [
            {
                "id": item.observation_id,
                "sequence": item.observed_sequence,
            }
            for item in ordered
        ],
    }
    return EmbodimentState(
        schema="kaliv-consciousness-core/embodiment-state/v1",
        state_id="estate-" + _digest(seed)[:32],
        cycle_id=perf.cycle_id,
        person_id=perf.person_id,
        person_revision=perf.person_revision,
        body_revision=perf.body_revision,
        performed_motor_state_ref=perf.motor_state_ref,
        performed_motor_sequence=perf.motor_sequence,
        observation_refs=[
            f"embodiment-observation:{item.observation_id}"
            for item in ordered
        ],
        last_observed_sequence=last_sequence,
        tracking_health=health,
        observation_confidence=confidence,
        source_refs=unique_sources,
        production_activation=False,
    )


def infer_embodiment_state(
    state: EmbodimentState | Mapping[str, Any],
    *,
    inference_kind: InferenceKind,
    proposition: str,
    confidence: float,
) -> InferredEmbodimentState:
    """Create an explicit inference that preserves observation provenance."""
    try:
        current = (
            state
            if isinstance(state, EmbodimentState)
            else EmbodimentState.model_validate(state)
        )
        probe = InferredEmbodimentState(
            schema="kaliv-consciousness-core/inferred-embodiment-state/v1",
            inference_id="einf-" + "0" * 32,
            cycle_id=current.cycle_id,
            person_id=current.person_id,
            person_revision=current.person_revision,
            body_revision=current.body_revision,
            inference_kind=inference_kind,
            proposition=proposition,
            confidence=confidence,
            evidence_observation_refs=current.observation_refs,
            production_activation=False,
        )
    except ValidationError as exc:
        raise EmbodimentContractError("invalid embodiment inference") from exc

    if not current.observation_refs:
        raise EmbodimentContractError(
            "embodiment inference requires at least one raw observation"
        )
    seed = {
        "state_id": current.state_id,
        "kind": inference_kind,
        "proposition": proposition,
        "evidence": current.observation_refs,
    }
    return probe.model_copy(
        update={"inference_id": "einf-" + _digest(seed)[:32]}
    )


class MockEmbodimentObserver:
    """Deterministic C8-A observer; no BodyRig or renderer mutation authority."""

    def observe(
        self,
        intent: SemanticBodyIntent,
        performed: PerformedBodyStateRef,
        *,
        renderer_ref: str = "mock-renderer:c8-a",
    ) -> list[EmbodimentObservation]:
        if intent.cycle_id != performed.cycle_id:
            raise EmbodimentContractError("intent/performed cognitive cycle mismatch")
        if intent.person_id != performed.person_id:
            raise EmbodimentContractError("intent/performed person mismatch")
        if intent.person_revision != performed.person_revision:
            raise EmbodimentContractError("intent/performed Person Revision mismatch")

        seed = {
            "intent_id": intent.intent_id,
            "motor_state_ref": performed.motor_state_ref,
            "sequence": performed.motor_sequence,
        }
        observation_id = "eobs-" + _digest(seed)[:32]
        return [
            EmbodimentObservation(
                schema="kaliv-consciousness-core/embodiment-observation/v1",
                observation_id=observation_id,
                cycle_id=intent.cycle_id,
                person_id=performed.person_id,
                person_revision=performed.person_revision,
                body_revision=performed.body_revision,
                motor_state_ref=performed.motor_state_ref,
                renderer_ref=renderer_ref,
                observation_kind="tracking",
                coordinate_space="renderer",
                observed_values={
                    "status": "ok",
                    "performed": True,
                    "intent_ref": intent.intent_id,
                },
                confidence=1.0,
                source_refs=[
                    performed.source_ref,
                    f"semantic-body-intent:{intent.intent_id}",
                    renderer_ref,
                ],
                observed_sequence=performed.motor_sequence,
                production_activation=False,
            )
        ]
