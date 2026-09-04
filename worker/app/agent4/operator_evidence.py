"""Dormant, transport-independent operator reads for A4 evidence records."""

from __future__ import annotations

from .domain import CampaignValidationError, _require_text
from .operator import Agent4CampaignReadSource
from .timeline_evidence import (
    CampaignEvidenceRecord,
    CampaignEvidenceRecordStore,
    CampaignEvidenceVerification,
)
from .timeline_evidence_query import (
    CampaignEvidenceQueryCursor,
    CampaignEvidenceQueryPage,
    CampaignEvidenceQueryService,
)


class CampaignEvidenceRecordNotFoundError(LookupError):
    """Raised when a campaign has no evidence record with the requested id."""


class Agent4OperatorEvidenceReadService:
    """Explicit bounded reads over one evidence store and query service."""

    def __init__(
        self,
        *,
        scheduler: Agent4CampaignReadSource,
        records: CampaignEvidenceRecordStore,
        query: CampaignEvidenceQueryService,
    ) -> None:
        if not isinstance(scheduler, Agent4CampaignReadSource):
            raise CampaignValidationError(
                "scheduler must implement the Agent 4 campaign read source"
            )
        if not isinstance(records, CampaignEvidenceRecordStore):
            raise CampaignValidationError(
                "records must implement CampaignEvidenceRecordStore"
            )
        if not isinstance(query, CampaignEvidenceQueryService):
            raise CampaignValidationError(
                "query must be a CampaignEvidenceQueryService"
            )
        if query.records is not records:
            raise CampaignValidationError(
                "query must use the same evidence record store"
            )
        self._scheduler = scheduler
        self._records = records
        self._query = query

    @property
    def scheduler(self) -> Agent4CampaignReadSource:
        return self._scheduler

    @property
    def records(self) -> CampaignEvidenceRecordStore:
        return self._records

    @property
    def query(self) -> CampaignEvidenceQueryService:
        return self._query

    def evidence(
        self,
        campaign_id: str,
        evidence_id: str,
    ) -> CampaignEvidenceRecord:
        """Return one directly addressed record after validating campaign identity."""

        campaign_id = _require_text(campaign_id, "campaign_id")
        evidence_id = _require_text(evidence_id, "evidence_id")
        self._scheduler.get(campaign_id)
        record = self._records.get(campaign_id, evidence_id)
        if record is None:
            raise CampaignEvidenceRecordNotFoundError(
                f"evidence record {evidence_id!r} was not found for "
                f"campaign {campaign_id!r}"
            )
        return record

    def verification(self, campaign_id: str) -> CampaignEvidenceVerification:
        """Return the fully verified evidence-chain summary for one campaign."""

        campaign_id = _require_text(campaign_id, "campaign_id")
        self._scheduler.get(campaign_id)
        return self._records.verify(campaign_id)

    def evidence_page(
        self,
        campaign_id: str,
        *,
        after: CampaignEvidenceQueryCursor | None = None,
        limit: int = 100,
        snapshot_head: CampaignEvidenceQueryCursor | None = None,
    ) -> CampaignEvidenceQueryPage:
        """Return one bounded stable page through hash-bound evidence cursors."""

        campaign_id = _require_text(campaign_id, "campaign_id")
        self._scheduler.get(campaign_id)
        return self._query.page(
            campaign_id,
            after=after,
            limit=limit,
            snapshot_head=snapshot_head,
        )
