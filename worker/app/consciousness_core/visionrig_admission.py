"""Default-off loopback VisionRig v3 -> Consciousness Core world-evidence adapter.

The adapter accepts only VisionRig PerceptionEvent/v3 payloads, projects a
bounded semantic summary, labels it as inferred evidence, and reuses C20-B for
atomic world update + attention admission. It never calls the ThoughtEngine.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from ..netguard import is_loopback
from .session_lifecycle import (
    CognitiveSessionLifecycleError,
    ProductionCognitiveSession,
)
from .supervisor import SupervisorContractError
from .world_reducer import WorldEvidenceEvent, WorldReducerError


CONSCIOUSNESS_VISIONRIG_FLAG = "KALIV_CONSCIOUSNESS_VISIONRIG_ENABLED"
CONSCIOUSNESS_VISIONRIG_PREFIX = "/experimental/consciousness"
MAX_VISIONRIG_BODY_BYTES = 256 * 1024
_MOUNTED_STATE = "consciousness_visionrig_mounted"

LoopbackPolicy = Callable[[Request], bool]
UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
PositiveFinite = Annotated[
    float,
    Field(gt=0.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]

EntityKind = Literal[
    "person",
    "face",
    "object",
    "text",
    "hand",
    "body",
    "unknown",
]
RelationPredicate = Literal[
    "left_of",
    "right_of",
    "above",
    "below",
    "near",
    "inside",
    "looking_at",
    "holding",
    "moving_towards",
    "moving_away",
    "in_front_of",
    "behind",
]


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
    entity_id: StrictStr = Field(min_length=1, max_length=128)
    kind: EntityKind
    label: StrictStr = Field(min_length=1, max_length=512)
    confidence: UnitInterval
    bbox: VisionRigBoundingBox | None = None
    track_id: StrictStr | None = Field(default=None, max_length=128)
    identity_hint: StrictStr | None = Field(default=None, max_length=256)


class VisionRigRelation(StrictModel):
    subject_id: StrictStr = Field(min_length=1, max_length=128)
    predicate: RelationPredicate
    object_id: StrictStr = Field(min_length=1, max_length=128)
    confidence: UnitInterval


class VisionRigLandmark(StrictModel):
    name: StrictStr = Field(min_length=1, max_length=128)
    x: UnitInterval
    y: UnitInterval
    z: Annotated[
        float,
        Field(ge=-1.0, le=1.0, strict=True, allow_inf_nan=False),
    ] | None = None
    confidence: UnitInterval


class VisionRigLandmarkObservation(StrictModel):
    observation_id: StrictStr = Field(min_length=1, max_length=128)
    group: Literal["pose", "left_hand", "right_hand", "face"]
    subject_entity_id: StrictStr | None = Field(default=None, max_length=128)
    landmarks: Annotated[
        list[VisionRigLandmark],
        Field(min_length=1, max_length=1024),
    ]


class VisionRigDepthObservation(StrictModel):
    subject_entity_id: StrictStr = Field(min_length=1, max_length=128)
    relative_depth: UnitInterval
    distance_m: PositiveFinite | None = None
    confidence: UnitInterval | None = None
    method: StrictStr = Field(min_length=1, max_length=128)


class VisionRigSourceDescriptor(StrictModel):
    source_id: StrictStr = Field(min_length=1, max_length=128)
    source_type: Literal[
        "camera",
        "screen",
        "vr",
        "image",
        "video",
        "synthetic",
    ]
    device: StrictStr | None = Field(default=None, max_length=256)


class VisionRigPerceptionEventV3(StrictModel):
    schema_id: Literal["visionrig/perception-event/v3"]
    event_id: StrictStr = Field(min_length=1, max_length=128)
    observed_at: datetime
    source: VisionRigSourceDescriptor
    frame_sequence: Annotated[int, Field(ge=0, strict=True)]
    entities: Annotated[list[VisionRigEntity], Field(max_length=128)] = []
    relations: Annotated[list[VisionRigRelation], Field(max_length=512)] = []
    landmarks: Annotated[
        list[VisionRigLandmarkObservation],
        Field(max_length=32),
    ] = []
    depth: Annotated[
        list[VisionRigDepthObservation],
        Field(max_length=128),
    ] = []
    scene_label: StrictStr | None = Field(default=None, max_length=256)
    scene_confidence: UnitInterval | None = None
    dropped_frames: Annotated[int, Field(ge=0, strict=True)] = 0
    production_authority: Literal[False]


class VisionRigAdmissionProjection(StrictModel):
    visionrig_event_ref: NonEmptyRef
    evidence: WorldEvidenceEvent
    attention_salience: UnitInterval
    confidence: UnitInterval
    production_activation: Literal[False]


class VisionRigAdmissionReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/visionrig-admission/v1"]
    visionrig_event_ref: NonEmptyRef
    evidence_ref: NonEmptyRef
    cognition_event_id: StrictStr | None
    world_changed: bool
    replayed: bool
    cognition_event_queued: bool
    epistemic_status: Literal["inferred"]
    confidence: UnitInterval
    attention_salience: UnitInterval
    observed_sequence: Annotated[int, Field(ge=0, strict=True)]
    model_calls: Literal[0]
    self_state_store_write_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def consciousness_visionrig_enabled() -> bool:
    """Only exact string 1 enables the VisionRig admission surface."""
    return os.getenv(CONSCIOUSNESS_VISIONRIG_FLAG, "0") == "1"


def _canonical_json(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def visionrig_event_ref(event: VisionRigPerceptionEventV3) -> str:
    return "visionrig-event:" + hashlib.sha256(_canonical_json(event)).hexdigest()


def _evidence_event_id(event: VisionRigPerceptionEventV3) -> str:
    seed = (
        "visionrig-v3|"
        + event.source.source_id
        + "|"
        + event.event_id
    ).encode("utf-8")
    return "wevt-" + hashlib.sha256(seed).hexdigest()[:32]


def _source_subject_ref(event: VisionRigPerceptionEventV3) -> str:
    payload = (
        event.source.source_type
        + "|"
        + event.source.source_id
        + "|"
        + (event.source.device or "")
    ).encode("utf-8")
    return "sensor:visionrig:" + hashlib.sha256(payload).hexdigest()[:32]


def _aggregate_confidence(event: VisionRigPerceptionEventV3) -> float:
    values: list[float] = []
    values.extend(float(item.confidence) for item in event.entities)
    values.extend(float(item.confidence) for item in event.relations)
    values.extend(
        float(item.confidence)
        for item in event.depth
        if item.confidence is not None
    )
    if event.scene_confidence is not None:
        values.append(float(event.scene_confidence))
    if not values:
        return 0.5
    return max(0.0, min(1.0, sum(values) / len(values)))


def _attention_salience(event: VisionRigPerceptionEventV3) -> float:
    value = 0.15
    if event.entities:
        value += 0.10
    if any(item.kind == "person" for item in event.entities):
        value += 0.25
    if any(
        item.predicate
        in {"looking_at", "holding", "moving_towards", "moving_away"}
        for item in event.relations
    ):
        value += 0.20
    metric = [
        float(item.distance_m)
        for item in event.depth
        if item.distance_m is not None
    ]
    if metric and min(metric) <= 1.5:
        value += 0.15
    confidence_values = [
        float(item.confidence)
        for item in event.entities
    ]
    if event.scene_confidence is not None:
        confidence_values.append(float(event.scene_confidence))
    if confidence_values:
        value += 0.15 * max(confidence_values)
    return max(0.0, min(0.95, value))


def _safe_label(value: str) -> str:
    compact = " ".join(value.split())
    return compact[:64]


def _semantic_summary(event: VisionRigPerceptionEventV3) -> str:
    kind_counts = Counter(item.kind for item in event.entities)
    kinds = ",".join(
        f"{kind}:{count}"
        for kind, count in sorted(kind_counts.items())
    ) or "none"

    labels = [
        _safe_label(item.label)
        for item in sorted(
            event.entities,
            key=lambda item: (-item.confidence, item.entity_id),
        )
        if item.kind != "text"
    ]
    labels = list(dict.fromkeys(labels))[:6]
    label_text = ",".join(labels) if labels else "none"

    predicate_counts = Counter(item.predicate for item in event.relations)
    relations = ",".join(
        f"{predicate}:{count}"
        for predicate, count in sorted(predicate_counts.items())
    ) or "none"

    metric = [
        float(item.distance_m)
        for item in event.depth
        if item.distance_m is not None
    ]
    metric_text = (
        f"nearest={min(metric):.2f}m,count={len(metric)}"
        if metric
        else "none"
    )
    scene_label = (
        _safe_label(event.scene_label)
        if event.scene_label is not None
        else "none"
    )
    scene_confidence = (
        f"{float(event.scene_confidence):.3f}"
        if event.scene_confidence is not None
        else "none"
    )

    # Deliberately omit OCR text, identity_hint and raw landmarks. Those need
    # separately reviewed semantics before they may become cognitive context.
    return (
        "VisionRig inferred visual state; "
        f"entity_kinds={kinds}; "
        f"top_labels={label_text}; "
        f"scene_label={scene_label}; "
        f"scene_confidence={scene_confidence}; "
        f"metric_depth={metric_text}; "
        f"relations={relations}; "
        f"ocr_items={sum(1 for item in event.entities if item.kind == 'text')}; "
        f"landmark_groups={len(event.landmarks)}; "
        f"dropped_frames={event.dropped_frames}"
    )[:2048]


def project_visionrig_event(
    event: VisionRigPerceptionEventV3,
) -> VisionRigAdmissionProjection:
    if not isinstance(event, VisionRigPerceptionEventV3):
        raise TypeError("event must be VisionRigPerceptionEventV3")
    event_ref = visionrig_event_ref(event)
    confidence = _aggregate_confidence(event)
    salience = _attention_salience(event)
    evidence = WorldEvidenceEvent(
        schema="kaliv-consciousness-core/world-evidence-event/v1",
        event_id=_evidence_event_id(event),
        subject_ref=_source_subject_ref(event),
        proposition=_semantic_summary(event),
        confidence=confidence,
        epistemic_status="inferred",
        source_refs=[event_ref],
        observed_sequence=event.frame_sequence,
        production_activation=False,
    )
    return VisionRigAdmissionProjection(
        visionrig_event_ref=event_ref,
        evidence=evidence,
        attention_salience=salience,
        confidence=confidence,
        production_activation=False,
    )


def _loopback_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_loopback(request: Request, allowed: LoopbackPolicy) -> None:
    try:
        admitted = bool(allowed(request))
    except Exception:
        admitted = False
    if not admitted:
        raise HTTPException(
            status_code=403,
            detail="Consciousness VisionRig admission is loopback-only",
        )


def _invalid_body() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail="invalid VisionRig perception event",
    )


async def _read_event(request: Request) -> VisionRigPerceptionEventV3:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail="VisionRig perception event requires application/json",
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_body() from None
        if declared < 0 or declared > MAX_VISIONRIG_BODY_BYTES:
            raise _invalid_body()

    raw = bytearray()
    try:
        async for chunk in request.stream():
            if len(raw) + len(chunk) > MAX_VISIONRIG_BODY_BYTES:
                raise _invalid_body()
            raw.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _invalid_body() from None

    if not raw:
        raise _invalid_body()

    try:
        return VisionRigPerceptionEventV3.model_validate_json(bytes(raw))
    except ValidationError:
        raise _invalid_body() from None


def build_consciousness_visionrig_router(
    *,
    loopback_allowed: LoopbackPolicy = _loopback_allowed,
) -> APIRouter:
    if not callable(loopback_allowed):
        raise TypeError("loopback policy must be callable")

    router = APIRouter(
        prefix=CONSCIOUSNESS_VISIONRIG_PREFIX,
        tags=["experimental-consciousness"],
    )

    sequence_lock = asyncio.Lock()
    last_source_event: dict[str, tuple[int, str]] = {}

    @router.post("/visionrig-event")
    async def admit_visionrig_event(request: Request) -> dict[str, object]:
        # Check locality before body parsing. Remote input never gets parsed by
        # the private sensor-to-cognition boundary.
        _require_loopback(request, loopback_allowed)
        event = await _read_event(request)

        session = getattr(request.app.state, "consciousness_session", None)
        if not isinstance(session, ProductionCognitiveSession):
            raise HTTPException(
                status_code=503,
                detail="consciousness session unavailable",
            )

        projection = project_visionrig_event(event)
        source_id = event.source.source_id
        async with sequence_lock:
            prior = last_source_event.get(source_id)
            if prior is not None:
                prior_sequence, prior_event_ref = prior
                if event.frame_sequence < prior_sequence:
                    raise HTTPException(
                        status_code=409,
                        detail="VisionRig perception sequence moved backwards",
                    )
                if (
                    event.frame_sequence == prior_sequence
                    and projection.visionrig_event_ref != prior_event_ref
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="VisionRig perception sequence was reused",
                    )

            try:
                result = session.submit_world_evidence(
                    projection.evidence,
                    attention_salience=projection.attention_salience,
                )
            except (
                WorldReducerError,
                SupervisorContractError,
                CognitiveSessionLifecycleError,
            ) as exc:
                raise HTTPException(
                    status_code=409,
                    detail="VisionRig perception admission conflict",
                ) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail="VisionRig perception admission unavailable",
                ) from exc

            if prior is None or event.frame_sequence > prior[0]:
                last_source_event[source_id] = (
                    event.frame_sequence,
                    projection.visionrig_event_ref,
                )

        cognition = result.cognition_event
        receipt = VisionRigAdmissionReceipt(
            schema="kaliv-consciousness-core/visionrig-admission/v1",
            visionrig_event_ref=projection.visionrig_event_ref,
            evidence_ref=result.evidence_ref,
            cognition_event_id=(
                cognition.event_id if cognition is not None else None
            ),
            world_changed=result.world_transition.world_changed,
            replayed=result.world_transition.idempotent_replay,
            cognition_event_queued=result.cognition_event_queued,
            epistemic_status="inferred",
            confidence=projection.confidence,
            attention_salience=projection.attention_salience,
            observed_sequence=result.observed_sequence,
            model_calls=0,
            self_state_store_write_applied=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
        return receipt.model_dump(mode="json")

    return router


def mount_consciousness_visionrig(
    app: FastAPI,
    *,
    loopback_allowed: LoopbackPolicy | None = None,
) -> bool:
    """Mount only after the independent exact VisionRig opt-in."""
    if not consciousness_visionrig_enabled():
        return False
    if getattr(app.state, _MOUNTED_STATE, False):
        return True

    kwargs = {}
    if loopback_allowed is not None:
        if not callable(loopback_allowed):
            raise TypeError("loopback policy must be callable")
        kwargs["loopback_allowed"] = loopback_allowed

    route_count = len(app.router.routes)
    try:
        app.include_router(build_consciousness_visionrig_router(**kwargs))
        setattr(app.state, _MOUNTED_STATE, True)
        return True
    except Exception:
        if len(app.router.routes) > route_count:
            del app.router.routes[route_count:]
            app.openapi_schema = None
        setattr(app.state, _MOUNTED_STATE, False)
        raise
