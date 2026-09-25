"""C31-B explicit loopback VisionRig journal transport.

One call performs one bounded fetch and admission pass. There is no background
polling, timer, scheduler or automatic model call.
"""
from __future__ import annotations

import ipaddress
from typing import Annotated, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .session_lifecycle import ProductionCognitiveSession, WorldEvidenceAdmissionResult
from .visionrig_perception import (
    VisionRigBridgeError,
    VisionRigPerceptionEvent,
    VisionRigPerceptionProjector,
)


class VisionRigTransportError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class VisionRigJournalEntry(StrictModel):
    cursor: Annotated[int, Field(ge=1, strict=True)]
    event: VisionRigPerceptionEvent


class VisionRigEventBatch(StrictModel):
    schema_id: Literal["visionrig/event-batch/v1"]
    entries: Annotated[list[VisionRigJournalEntry], Field(max_length=16)]
    next_cursor: Annotated[int, Field(ge=0, strict=True)]
    oldest_available_cursor: Annotated[int | None, Field(ge=1, strict=True)]
    newest_available_cursor: Annotated[int | None, Field(ge=1, strict=True)]
    gap: bool


class VisionRigPollResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/visionrig-poll-result/v1"]
    previous_cursor: Annotated[int, Field(ge=0, strict=True)]
    next_cursor: Annotated[int, Field(ge=0, strict=True)]
    events_seen: Annotated[int, Field(ge=0, le=4, strict=True)]
    projections_emitted: Annotated[int, Field(ge=0, le=4, strict=True)]
    admissions: Annotated[list[WorldEvidenceAdmissionResult], Field(max_length=64)]
    model_calls: Literal[0]
    internal_thread_created: Literal[False]
    internal_timer_created: Literal[False]
    automatic_repeat: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


def _loopback_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise VisionRigTransportError("VisionRig URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise VisionRigTransportError("VisionRig URL must not contain credentials")
    host = parsed.hostname
    if host is None:
        raise VisionRigTransportError("VisionRig URL has no hostname")
    loopback = host.lower() == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if not loopback:
        raise VisionRigTransportError("VisionRig transport is loopback-only")
    if parsed.query or parsed.fragment:
        raise VisionRigTransportError("VisionRig base URL may not contain query/fragment")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


class VisionRigClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8110",
        *,
        timeout_seconds: float = 2.0,
        client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("timeout_seconds must be >0 and <=30")
        self._base_url = _loopback_base_url(base_url)
        self._timeout = timeout_seconds
        self._client = client

    def fetch_events(
        self,
        *,
        after_cursor: int,
        limit: int = 4,
    ) -> VisionRigEventBatch:
        if after_cursor < 0:
            raise ValueError("after_cursor must be >= 0")
        if not 1 <= limit <= 4:
            raise ValueError("limit must be between 1 and 4")
        url = self._base_url + "/api/v1/perception/events"
        params = {"after_cursor": after_cursor, "limit": limit}
        try:
            if self._client is None:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.get(url, params=params)
            else:
                response = self._client.get(url, params=params, timeout=self._timeout)
            response.raise_for_status()
            return VisionRigEventBatch.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise VisionRigTransportError("invalid VisionRig journal response") from exc


def poll_visionrig_once(
    *,
    session: ProductionCognitiveSession,
    projector: VisionRigPerceptionProjector,
    client: VisionRigClient,
    after_cursor: int,
) -> VisionRigPollResult:
    """Fetch at most four visual events and admit them through session authority."""
    if not isinstance(session, ProductionCognitiveSession):
        raise TypeError("session must be ProductionCognitiveSession")
    if not isinstance(projector, VisionRigPerceptionProjector):
        raise TypeError("projector must be VisionRigPerceptionProjector")
    if not isinstance(client, VisionRigClient):
        raise TypeError("client must be VisionRigClient")
    if after_cursor < 0:
        raise ValueError("after_cursor must be >= 0")

    batch = client.fetch_events(after_cursor=after_cursor, limit=4)
    if batch.gap:
        raise VisionRigTransportError(
            "VisionRig journal gap detected; explicit resynchronization is required"
        )

    checkpoint = projector.checkpoint()
    admissions: list[WorldEvidenceAdmissionResult] = []
    projected_count = 0
    try:
        for entry in batch.entries:
            projection = projector.project(entry.event)
            if projection.evidence_plans:
                projected_count += 1
            for plan in projection.evidence_plans:
                admissions.append(
                    session.submit_world_evidence(
                        plan.evidence,
                        attention_salience=plan.attention_salience,
                    )
                )
    except Exception:
        # Session admissions may already have occurred. Restoring only the
        # non-authoritative dedup cache guarantees a retry re-emits the exact
        # evidence; ProductionCognitiveSession then handles those replays
        # idempotently before continuing.
        projector.restore(checkpoint)
        raise

    return VisionRigPollResult(
        schema="kaliv-consciousness-core/visionrig-poll-result/v1",
        previous_cursor=after_cursor,
        next_cursor=batch.next_cursor,
        events_seen=len(batch.entries),
        projections_emitted=projected_count,
        admissions=admissions,
        model_calls=0,
        internal_thread_created=False,
        internal_timer_created=False,
        automatic_repeat=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
