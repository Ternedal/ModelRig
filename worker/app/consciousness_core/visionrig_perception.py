"""C31-A VisionRig -> Consciousness Core perception bridge.

VisionRig owns visual perception. ModelRig owns semantic projection and Core
admission. This module contains no polling loop, scheduler, persistence, tool
execution, body/voice action or production activation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .cycle import RuntimeWorldState
from .self_state import PersistentSelfState
from .supervisor import CognitionEvent, SupervisorState, queue_cognition_event
from .world_reducer import (
    WorldEvidenceEvent,
    WorldTransitionReceipt,
    reduce_world_evidence,
    world_evidence_event_ref,
)


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmpty = Annotated[str, Field(min_length=1, max_length=512)]


class VisionRigBridgeError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class VisionRigBoundingBox(StrictModel):
    x: UnitInterval
    y: UnitInterval
    width: UnitInterval
    height: UnitInterval


class VisionRigEntity(StrictModel):
    entity_id: Annotated[str, Field(min_length=1, max_length=128)]
    kind: Literal["person", "face", "object", "text", "hand", "body", "unknown"]
    label: Annotated[str, Field(min_length=1, max_length=512)]
    confidence: UnitInterval
    bbox: VisionRigBoundingBox | None
    track_id: Annotated[str, Field(max_length=128)] | None
    identity_hint: Annotated[str, Field(max_length=256)] | None


class VisionRigLandmark(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    x: UnitInterval
    y: UnitInterval
    z: Annotated[
        float,
        Field(ge=-1.0, le=1.0, strict=True, allow_inf_nan=False),
    ] | None
    confidence: UnitInterval


class VisionRigLandmarkObservation(StrictModel):
    observation_id: Annotated[str, Field(min_length=1, max_length=128)]
    group: Literal["pose", "left_hand", "right_hand", "face"]
    subject_entity_id: Annotated[str, Field(max_length=128)] | None
    landmarks: Annotated[list[VisionRigLandmark], Field(min_length=1)]


class VisionRigDepthObservation(StrictModel):
    subject_entity_id: Annotated[str, Field(min_length=1, max_length=128)]
    relative_depth: UnitInterval
    confidence: UnitInterval | None
    method: Annotated[str, Field(min_length=1, max_length=128)]


class VisionRigSource(StrictModel):
    source_id: Annotated[str, Field(min_length=1, max_length=128)]
    source_type: Literal["camera", "screen", "vr", "image", "video", "synthetic"]
    device: Annotated[str, Field(max_length=256)] | None


class VisionRigPerceptionEvent(StrictModel):
    schema_id: Literal["visionrig/perception-event/v2"]
    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    observed_at: NonEmpty
    source: VisionRigSource
    frame_sequence: Annotated[int, Field(ge=0, strict=True)]
    entities: Annotated[list[VisionRigEntity], Field(max_length=512)]
    relations: list[dict[str, Any]]
    landmarks: Annotated[list[VisionRigLandmarkObservation], Field(max_length=32)]
    depth: Annotated[list[VisionRigDepthObservation], Field(max_length=512)]
    scene_label: Annotated[str, Field(max_length=256)] | None
    scene_confidence: UnitInterval | None
    dropped_frames: Annotated[int, Field(ge=0, strict=True)]
    production_authority: Literal[False]


class VisionRigProjection(StrictModel):
    schema: Literal["kaliv-consciousness-core/visionrig-projection/v1"]
    visionrig_event_id: Annotated[str, Field(min_length=1, max_length=128)]
    source_ref: Annotated[str, Field(min_length=1, max_length=256)]
    world_evidence: Annotated[list[WorldEvidenceEvent], Field(max_length=16)]
    cognition_events: Annotated[list[CognitionEvent], Field(max_length=16)]
    deduplicated_items: Annotated[int, Field(ge=0, strict=True)]
    identity_hints_promoted: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def paired_projection(self) -> "VisionRigProjection":
        if len(self.world_evidence) != len(self.cognition_events):
            raise ValueError("VisionRig world/cognition projection must stay paired")
        return self


class VisionRigAdmissionResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/visionrig-admission-result/v1"]
    world: RuntimeWorldState
    state: PersistentSelfState
    supervisor_state: SupervisorState
    world_receipts: Annotated[list[WorldTransitionReceipt], Field(max_length=16)]
    queued_cognition_event_ids: Annotated[list[str], Field(max_length=16)]
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _region(box: VisionRigBoundingBox | None) -> str:
    if box is None:
        return "unspecified"
    cx = box.x + box.width / 2.0
    cy = box.y + box.height / 2.0
    horizontal = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    vertical = "upper" if cy < 1 / 3 else "lower" if cy > 2 / 3 else "middle"
    return f"{horizontal}-{vertical}"


def _safe_label(label: str, limit: int = 240) -> str:
    value = " ".join(label.split())
    return value[:limit]


def _entity_key(entity: VisionRigEntity) -> str:
    if entity.track_id:
        return f"{entity.kind}:track:{entity.track_id}"
    return (
        f"{entity.kind}:untracked:"
        + _digest(
            {
                "label": entity.label,
                "region": _region(entity.bbox),
            }
        )[:24]
    )


def _entity_signature(entity: VisionRigEntity) -> str:
    return _digest(
        {
            "kind": entity.kind,
            "label": entity.label,
            "region": _region(entity.bbox),
        }
    )


def _entity_proposition(entity: VisionRigEntity) -> str:
    region = _region(entity.bbox)
    label = _safe_label(entity.label)
    if entity.kind == "person":
        return f"Vision inference: a person is visible in the {region} region."
    if entity.kind == "text":
        return f'Vision OCR inference: visible text in the {region} region reads "{label}".'
    if entity.kind == "face":
        return f"Vision inference: a face is visible in the {region} region."
    if entity.kind == "hand":
        return f"Vision inference: a hand is visible in the {region} region."
    if entity.kind == "body":
        return f"Vision inference: a body is visible in the {region} region."
    return f'Vision inference: a visible object labelled "{label}" is in the {region} region.'


def _base_salience(entity: VisionRigEntity) -> float:
    return {
        "person": 0.90,
        "face": 0.82,
        "text": 0.75,
        "hand": 0.68,
        "body": 0.68,
        "object": 0.58,
        "unknown": 0.45,
    }[entity.kind]


def _bounded_salience(entity: VisionRigEntity) -> float:
    return float(max(0.0, min(1.0, _base_salience(entity) * entity.confidence)))


class VisionRigPerceptionProjector:
    """Stateful short-term deduplicator and semantic projector.

    State is process-local and non-authoritative. It suppresses unchanged tracked
    observations; it never promotes VisionRig identity_hint into Core identity.
    """

    def __init__(self, *, max_items_per_event: int = 16) -> None:
        if not 1 <= max_items_per_event <= 16:
            raise ValueError("max_items_per_event must be between 1 and 16")
        self._max_items = max_items_per_event
        self._last_sequence: dict[str, int] = {}
        self._fingerprints: dict[tuple[str, str], str] = {}

    def project(
        self,
        event: VisionRigPerceptionEvent | Mapping[str, Any],
    ) -> VisionRigProjection:
        try:
            value = (
                event
                if isinstance(event, VisionRigPerceptionEvent)
                else VisionRigPerceptionEvent.model_validate(event)
            )
        except ValidationError as exc:
            raise VisionRigBridgeError("invalid VisionRig PerceptionEvent/v2") from exc

        source_id = value.source.source_id
        prior_sequence = self._last_sequence.get(source_id)
        if prior_sequence is not None and value.frame_sequence < prior_sequence:
            raise VisionRigBridgeError("VisionRig source sequence moved backwards")
        self._last_sequence[source_id] = max(
            value.frame_sequence,
            prior_sequence if prior_sequence is not None else value.frame_sequence,
        )

        source_ref = f"visionrig:event:{value.event_id}"
        candidates: list[tuple[float, str, VisionRigEntity]] = []
        deduplicated = 0

        for entity in value.entities:
            key = _entity_key(entity)
            signature = _entity_signature(entity)
            state_key = (source_id, key)
            if self._fingerprints.get(state_key) == signature:
                deduplicated += 1
                continue
            self._fingerprints[state_key] = signature
            candidates.append((_bounded_salience(entity), key, entity))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[: self._max_items]
        deduplicated += max(0, len(candidates) - len(selected))

        evidence: list[WorldEvidenceEvent] = []
        cognition: list[CognitionEvent] = []
        for salience, semantic_key, entity in selected:
            proposition = _entity_proposition(entity)
            seed = {
                "visionrig_event_id": value.event_id,
                "semantic_key": semantic_key,
                "proposition": proposition,
            }
            evidence_event = WorldEvidenceEvent(
                schema="kaliv-consciousness-core/world-evidence-event/v1",
                event_id="wevt-" + _digest(seed)[:32],
                subject_ref=f"visionrig-subject:{source_id}:{semantic_key}"[:256],
                proposition=proposition,
                confidence=float(entity.confidence),
                epistemic_status="inferred",
                source_refs=[
                    source_ref,
                    f"visionrig:source:{source_id}",
                ],
                observed_sequence=value.frame_sequence,
                production_activation=False,
            )
            evidence.append(evidence_event)
            evidence_ref = world_evidence_event_ref(evidence_event)
            cognition.append(
                CognitionEvent(
                    schema="kaliv-consciousness-core/cognition-event/v1",
                    event_id="cevt-" + _digest(
                        {
                            "world_evidence_ref": evidence_ref,
                            "visionrig_event_id": value.event_id,
                        }
                    )[:32],
                    kind="world_change",
                    source_ref=evidence_ref,
                    summary=proposition,
                    salience=salience,
                    observed_sequence=value.frame_sequence,
                    production_activation=False,
                )
            )

        return VisionRigProjection(
            schema="kaliv-consciousness-core/visionrig-projection/v1",
            visionrig_event_id=value.event_id,
            source_ref=source_ref,
            world_evidence=evidence,
            cognition_events=cognition,
            deduplicated_items=deduplicated,
            identity_hints_promoted=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )


def admit_visionrig_projection(
    *,
    state: PersistentSelfState | Mapping[str, Any],
    world: RuntimeWorldState | Mapping[str, Any],
    supervisor_state: SupervisorState | Mapping[str, Any],
    projection: VisionRigProjection | Mapping[str, Any],
) -> VisionRigAdmissionResult:
    try:
        current_state = (
            state
            if isinstance(state, PersistentSelfState)
            else PersistentSelfState.model_validate(state)
        )
        current_world = (
            world
            if isinstance(world, RuntimeWorldState)
            else RuntimeWorldState.model_validate(world)
        )
        current_supervisor = (
            supervisor_state
            if isinstance(supervisor_state, SupervisorState)
            else SupervisorState.model_validate(supervisor_state)
        )
        projected = (
            projection
            if isinstance(projection, VisionRigProjection)
            else VisionRigProjection.model_validate(projection)
        )
    except ValidationError as exc:
        raise VisionRigBridgeError("invalid VisionRig admission input") from exc

    receipts: list[WorldTransitionReceipt] = []
    for evidence in projected.world_evidence:
        transition = reduce_world_evidence(
            state=current_state,
            world=current_world,
            evidence=evidence,
        )
        current_state = transition.state
        current_world = transition.world
        receipts.append(transition.receipt)

    queued_ids: list[str] = []
    for event in projected.cognition_events:
        current_supervisor = queue_cognition_event(current_supervisor, event)
        queued_ids.append(event.event_id)

    return VisionRigAdmissionResult(
        schema="kaliv-consciousness-core/visionrig-admission-result/v1",
        world=current_world,
        state=current_state,
        supervisor_state=current_supervisor,
        world_receipts=receipts,
        queued_cognition_event_ids=queued_ids,
        model_calls=0,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
