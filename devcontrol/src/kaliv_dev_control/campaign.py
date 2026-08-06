"""Immutable, hash-chained state for one development campaign."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .contract import DevelopmentTask

CAMPAIGN_SCHEMA = "kaliv-development-campaign/v1"
EVENT_SCHEMA = "kaliv-development-campaign-event/v1"
_ZERO_HASH = "0" * 64
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_CAMPAIGN_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")


class CampaignError(ValueError):
    """Campaign state is malformed, tampered with, or transitioned illegally."""


class CampaignState(StrEnum):
    CREATED = "created"
    WORKSPACE_READY = "workspace_ready"
    PATCH_STAGED = "patch_staged"
    TESTED = "tested"
    REVIEWED = "reviewed"
    READY_FOR_DRAFT_PR = "ready_for_draft_pr"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TRANSITIONS: dict[CampaignState, frozenset[CampaignState]] = {
    CampaignState.CREATED: frozenset(
        {
            CampaignState.WORKSPACE_READY,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        }
    ),
    CampaignState.WORKSPACE_READY: frozenset(
        {
            CampaignState.PATCH_STAGED,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        }
    ),
    CampaignState.PATCH_STAGED: frozenset(
        {
            CampaignState.TESTED,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        }
    ),
    CampaignState.TESTED: frozenset(
        {
            CampaignState.REVIEWED,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        }
    ),
    CampaignState.REVIEWED: frozenset(
        {
            CampaignState.READY_FOR_DRAFT_PR,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        }
    ),
    CampaignState.READY_FOR_DRAFT_PR: frozenset(),
    CampaignState.FAILED: frozenset(),
    CampaignState.CANCELLED: frozenset(),
}


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _clean_detail(value: Any) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise CampaignError("event detail must be a canonical non-empty string")
    if "\x00" in value or len(value.encode("utf-8")) > 2_048:
        raise CampaignError("event detail is outside bounds")
    return value


def _valid_identifier(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class CampaignEvent:
    sequence: int
    state: CampaignState
    evidence_sha256: str
    detail: str
    previous_event_sha256: str
    event_sha256: str
    schema: str = EVENT_SCHEMA

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        state: CampaignState,
        evidence_sha256: str,
        detail: str,
        previous_event_sha256: str,
    ) -> "CampaignEvent":
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise CampaignError("event sequence must be a non-negative integer")
        if not isinstance(state, CampaignState):
            raise CampaignError("campaign event state is unsupported")
        if not isinstance(evidence_sha256, str) or _SHA64.fullmatch(evidence_sha256) is None:
            raise CampaignError("event evidence hash is invalid")
        if (
            not isinstance(previous_event_sha256, str)
            or _SHA64.fullmatch(previous_event_sha256) is None
        ):
            raise CampaignError("previous event hash is invalid")
        detail = _clean_detail(detail)
        payload = {
            "schema": EVENT_SCHEMA,
            "sequence": sequence,
            "state": state.value,
            "evidence_sha256": evidence_sha256,
            "detail": detail,
            "previous_event_sha256": previous_event_sha256,
        }
        event_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        return cls(
            sequence=sequence,
            state=state,
            evidence_sha256=evidence_sha256,
            detail=detail,
            previous_event_sha256=previous_event_sha256,
            event_sha256=event_hash,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "CampaignEvent":
        if not isinstance(value, Mapping):
            raise CampaignError("campaign event must be an object")
        allowed = {
            "schema",
            "sequence",
            "state",
            "evidence_sha256",
            "detail",
            "previous_event_sha256",
            "event_sha256",
        }
        if set(value) != allowed:
            raise CampaignError("campaign event fields mismatch")
        if value["schema"] != EVENT_SCHEMA:
            raise CampaignError("campaign event schema is unsupported")
        try:
            state = CampaignState(value["state"])
        except (TypeError, ValueError) as exc:
            raise CampaignError("campaign event state is unsupported") from exc
        event = cls.create(
            sequence=value["sequence"],
            state=state,
            evidence_sha256=value["evidence_sha256"],
            detail=value["detail"],
            previous_event_sha256=value["previous_event_sha256"],
        )
        if value["event_sha256"] != event.event_sha256:
            raise CampaignError("campaign event hash does not verify")
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sequence": self.sequence,
            "state": self.state.value,
            "evidence_sha256": self.evidence_sha256,
            "detail": self.detail,
            "previous_event_sha256": self.previous_event_sha256,
            "event_sha256": self.event_sha256,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentCampaign:
    campaign_id: str
    task_id: str
    task_sha256: str
    base_sha: str
    events: tuple[CampaignEvent, ...]
    schema: str = CAMPAIGN_SCHEMA

    @classmethod
    def create(
        cls,
        campaign_id: str,
        task: DevelopmentTask,
    ) -> "DevelopmentCampaign":
        if not _valid_identifier(campaign_id, _CAMPAIGN_ID):
            raise CampaignError("campaign id has invalid syntax")
        task_hash = hashlib.sha256(
            task.canonical_json().encode("utf-8")
        ).hexdigest()
        initial = CampaignEvent.create(
            sequence=0,
            state=CampaignState.CREATED,
            evidence_sha256=task_hash,
            detail="task contract accepted",
            previous_event_sha256=_ZERO_HASH,
        )
        return cls(
            campaign_id=campaign_id,
            task_id=task.task_id,
            task_sha256=task_hash,
            base_sha=task.base_sha,
            events=(initial,),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "DevelopmentCampaign":
        if not isinstance(value, Mapping):
            raise CampaignError("campaign must be an object")
        allowed = {
            "schema",
            "campaign_id",
            "task_id",
            "task_sha256",
            "base_sha",
            "events",
        }
        if set(value) != allowed:
            raise CampaignError("campaign fields mismatch")
        if value["schema"] != CAMPAIGN_SCHEMA:
            raise CampaignError("campaign schema is unsupported")
        if not _valid_identifier(value["campaign_id"], _CAMPAIGN_ID):
            raise CampaignError("campaign id has invalid syntax")
        if not _valid_identifier(value["task_id"], _TASK_ID):
            raise CampaignError("campaign task id has invalid syntax")
        if (
            not isinstance(value["task_sha256"], str)
            or _SHA64.fullmatch(value["task_sha256"]) is None
        ):
            raise CampaignError("campaign task hash is invalid")
        if (
            not isinstance(value["base_sha"], str)
            or _SHA40.fullmatch(value["base_sha"]) is None
        ):
            raise CampaignError("campaign base SHA is invalid")
        if not isinstance(value["events"], list) or not value["events"]:
            raise CampaignError("campaign events must be a non-empty array")
        campaign = cls(
            campaign_id=value["campaign_id"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            base_sha=value["base_sha"],
            events=tuple(CampaignEvent.from_mapping(item) for item in value["events"]),
        )
        campaign.verify()
        return campaign

    @property
    def state(self) -> CampaignState:
        return self.events[-1].state

    def advance(
        self,
        target: CampaignState,
        *,
        evidence_sha256: str,
        detail: str,
    ) -> "DevelopmentCampaign":
        if target not in _TRANSITIONS[self.state]:
            raise CampaignError(
                f"illegal campaign transition: {self.state.value} -> {target.value}"
            )
        event = CampaignEvent.create(
            sequence=len(self.events),
            state=target,
            evidence_sha256=evidence_sha256,
            detail=detail,
            previous_event_sha256=self.events[-1].event_sha256,
        )
        campaign = DevelopmentCampaign(
            campaign_id=self.campaign_id,
            task_id=self.task_id,
            task_sha256=self.task_sha256,
            base_sha=self.base_sha,
            events=(*self.events, event),
        )
        campaign.verify()
        return campaign

    def verify(self) -> None:
        if self.schema != CAMPAIGN_SCHEMA:
            raise CampaignError("campaign schema is unsupported")
        if not _valid_identifier(self.campaign_id, _CAMPAIGN_ID):
            raise CampaignError("campaign id has invalid syntax")
        if not _valid_identifier(self.task_id, _TASK_ID):
            raise CampaignError("campaign task id has invalid syntax")
        if not isinstance(self.task_sha256, str) or _SHA64.fullmatch(self.task_sha256) is None:
            raise CampaignError("campaign task hash is invalid")
        if not isinstance(self.base_sha, str) or _SHA40.fullmatch(self.base_sha) is None:
            raise CampaignError("campaign base SHA is invalid")
        if not isinstance(self.events, tuple) or not self.events:
            raise CampaignError("campaign contains no events")
        previous_hash = _ZERO_HASH
        previous_state: CampaignState | None = None
        for sequence, event in enumerate(self.events):
            if not isinstance(event, CampaignEvent):
                raise CampaignError("campaign event is invalid")
            if event.sequence != sequence:
                raise CampaignError("campaign event sequence is not contiguous")
            if event.previous_event_sha256 != previous_hash:
                raise CampaignError("campaign event chain is broken")
            verified = CampaignEvent.create(
                sequence=event.sequence,
                state=event.state,
                evidence_sha256=event.evidence_sha256,
                detail=event.detail,
                previous_event_sha256=event.previous_event_sha256,
            )
            if verified.event_sha256 != event.event_sha256:
                raise CampaignError("campaign event hash does not verify")
            if sequence == 0:
                if event.state is not CampaignState.CREATED:
                    raise CampaignError("campaign must begin in created state")
                if event.evidence_sha256 != self.task_sha256:
                    raise CampaignError("initial event is not bound to the task")
            elif previous_state is None or event.state not in _TRANSITIONS[previous_state]:
                raise CampaignError("campaign contains an illegal state transition")
            previous_hash = event.event_sha256
            previous_state = event.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "events": [event.to_dict() for event in self.events],
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())
