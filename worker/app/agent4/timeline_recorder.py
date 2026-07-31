"""Caller-driven durable event recording through the A4-06 timeline."""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Iterable, Mapping

from .contracts import CampaignTimelineStore
from .domain import CampaignEvent, CampaignEventKind, JsonValue, _require_text
from .timeline import CampaignEvidenceReference


class TimelineCampaignEventRecorder:
    """Create the next ordered event and append it durably to a timeline."""

    def __init__(self, timeline: CampaignTimelineStore) -> None:
        if not isinstance(timeline, CampaignTimelineStore):
            raise TypeError("timeline store must implement CampaignTimelineStore")
        self._timeline = timeline
        self._lock = RLock()

    def record(
        self,
        campaign_id: str,
        kind: CampaignEventKind,
        *,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> CampaignEvent:
        return self.record_with_evidence(
            campaign_id,
            kind,
            occurred_at=occurred_at,
            payload=payload,
        )

    def record_with_evidence(
        self,
        campaign_id: str,
        kind: CampaignEventKind,
        *,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue] | None = None,
        evidence: Iterable[CampaignEvidenceReference] = (),
    ) -> CampaignEvent:
        campaign_id = _require_text(campaign_id, "campaign_id")
        with self._lock:
            latest = self._timeline.latest(campaign_id)
            sequence = latest.event.sequence + 1 if latest is not None else 1
            event = CampaignEvent(
                event_id=f"{campaign_id}:{sequence}",
                campaign_id=campaign_id,
                kind=kind,
                sequence=sequence,
                occurred_at=occurred_at,
                payload=payload or {},
            )
            self._timeline.append(event, evidence=tuple(evidence))
            return event
