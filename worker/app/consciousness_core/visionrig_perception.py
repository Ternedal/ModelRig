"""C31-A VisionRig -> Consciousness Core semantic projection.

VisionRig owns visual perception. ModelRig owns semantic projection. This module
does not mutate Core state; ProductionCognitiveSession remains admission
authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .world_reducer import WorldEvidenceEvent


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


class VisionRigRelation(StrictModel):
    subject_id: Annotated[str, Field(min_length=1, max_length=128)]
    predicate: Literal[
        "left_of", "right_of", "above", "below", "near", "inside",
        "looking_at", "holding", "moving_towards", "moving_away"
    ]
    object_id: Annotated[str, Field(min_length=1, max_length=128)]
    confidence: UnitInterval


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
    relations: Annotated[list[VisionRigRelation], Field(max_length=1024)]
    landmarks: Annotated[list[VisionRigLandmarkObservation], Field(max_length=32)]
    depth: Annotated[list[VisionRigDepthObservation], Field(max_length=512)]
    scene_label: Annotated[str, Field(max_length=256)] | None
    scene_confidence: UnitInterval | None
    dropped_frames: Annotated[int, Field(ge=0, strict=True)]
    production_authority: Literal[False]


class VisionRigEvidencePlan(StrictModel):
    evidence: WorldEvidenceEvent
    attention_salience: UnitInterval


class VisionRigProjection(StrictModel):
    schema: Literal["kaliv-consciousness-core/visionrig-projection/v2"]
    visionrig_event_id: Annotated[str, Field(min_length=1, max_length=128)]
    source_ref: Annotated[str, Field(min_length=1, max_length=256)]
    evidence_plans: Annotated[list[VisionRigEvidencePlan], Field(max_length=16)]
    deduplicated_items: Annotated[int, Field(ge=0, strict=True)]
    identity_hints_promoted: Literal[False]
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
    return " ".join(label.split())[:limit]


def _entity_key(entity: VisionRigEntity) -> str:
    if entity.track_id:
        return f"{entity.kind}:track:{entity.track_id}"
    return (
        f"{entity.kind}:untracked:"
        + _digest({"label": entity.label, "region": _region(entity.bbox)})[:24]
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


def _salience(entity: VisionRigEntity) -> float:
    base = {
        "person": 0.90,
        "face": 0.82,
        "text": 0.75,
        "hand": 0.68,
        "body": 0.68,
        "object": 0.58,
        "unknown": 0.45,
    }[entity.kind]
    return float(max(0.0, min(1.0, base * entity.confidence)))


class VisionRigPerceptionProjector:
    """Short-term deduplication plus evidence projection.

    The cache is an optimization only. Call checkpoint()/restore() around a
    multi-event admission transaction if downstream admission can fail.
    """

    def __init__(self, *, max_items_per_event: int = 16) -> None:
        if not 1 <= max_items_per_event <= 16:
            raise ValueError("max_items_per_event must be between 1 and 16")
        self._max_items = max_items_per_event
        self._last_sequence: dict[str, int] = {}
        self._fingerprints: dict[tuple[str, str], str] = {}

    def checkpoint(self) -> tuple[dict[str, int], dict[tuple[str, str], str]]:
        return copy.deepcopy(self._last_sequence), copy.deepcopy(self._fingerprints)

    def restore(
        self,
        checkpoint: tuple[dict[str, int], dict[tuple[str, str], str]],
    ) -> None:
        sequences, fingerprints = checkpoint
        self._last_sequence = copy.deepcopy(sequences)
        self._fingerprints = copy.deepcopy(fingerprints)

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
            candidates.append((_salience(entity), key, entity))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[: self._max_items]
        deduplicated += max(0, len(candidates) - len(selected))

        plans: list[VisionRigEvidencePlan] = []
        for salience, semantic_key, entity in selected:
            proposition = _entity_proposition(entity)
            evidence = WorldEvidenceEvent(
                schema="kaliv-consciousness-core/world-evidence-event/v1",
                event_id="wevt-" + _digest(
                    {
                        "visionrig_event_id": value.event_id,
                        "semantic_key": semantic_key,
                        "proposition": proposition,
                    }
                )[:32],
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
            plans.append(
                VisionRigEvidencePlan(
                    evidence=evidence,
                    attention_salience=salience,
                )
            )

        return VisionRigProjection(
            schema="kaliv-consciousness-core/visionrig-projection/v2",
            visionrig_event_id=value.event_id,
            source_ref=source_ref,
            evidence_plans=plans,
            deduplicated_items=deduplicated,
            identity_hints_promoted=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
