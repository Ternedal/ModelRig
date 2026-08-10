"""Narrow production composition for the Agent 4 GET-only operator surface.

Unlike the full caller-driven Agent 4 runtime, this module never constructs a
queue, resource lease manager, checkpoint/failure service or handoff scheduler.
It opens the canonical persisted read stores behind facades whose mutation
methods fail before touching storage.  The resulting context is sufficient for
the existing operator router and intentionally insufficient for lifecycle work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .composition import (
    Agent4RuntimePaths,
    _WRITER_ROOTS,
    _WRITER_ROOTS_LOCK,
    _canonical_root,
)
from .domain import CampaignRecord, CampaignValidationError
from .operator import Agent4OperatorReadService
from .operator_evidence import Agent4OperatorEvidenceReadService
from .repository import JsonCampaignRepository
from .service import CampaignNotFoundError, CampaignSchedulerService
from .timeline import JsonCampaignTimelineStore
from .timeline_evidence import JsonCampaignEvidenceRecordStore
from .timeline_evidence_query import CampaignEvidenceQueryService
from .timeline_query import CampaignTimelineQueryService


class _ReadOnlyBoundary:
    @staticmethod
    def _reject(operation: str) -> NoReturn:
        raise CampaignValidationError(
            f"Agent 4 read-only production context forbids {operation}"
        )


class ReadOnlyCampaignSchedulerFacade(CampaignSchedulerService, _ReadOnlyBoundary):
    """Campaign lookup facade with every lifecycle entrypoint denied.

    ``Agent4OperatorReadService`` historically accepts ``CampaignSchedulerService``
    because the full canonical runtime supplies one.  Production read mode keeps
    that compatibility without constructing or retaining a mutation-capable
    scheduler: only ``get`` and ``list`` delegate to the persisted repository.
    """

    def __init__(self, repository: JsonCampaignRepository) -> None:
        if not isinstance(repository, JsonCampaignRepository):
            raise CampaignValidationError(
                "read-only campaign facade requires JsonCampaignRepository"
            )
        # Deliberately do not call CampaignSchedulerService.__init__.  None of
        # its lifecycle collaborators (executor, queue, events, projections) are
        # constructed or retained by this facade.
        self.__repository = repository

    @property
    def queued_count(self) -> int:
        return 0

    def recover(self) -> NoReturn:
        self._reject("recovery")

    def submit(self, spec: Any) -> NoReturn:
        del spec
        self._reject("campaign submit")

    def dispatch_ready(self) -> NoReturn:
        self._reject("campaign dispatch")

    def request_pause(self, campaign_id: str) -> NoReturn:
        del campaign_id
        self._reject("campaign pause")

    def mark_paused(self, campaign_id: str) -> NoReturn:
        del campaign_id
        self._reject("campaign pause transition")

    def resume(self, campaign_id: str) -> NoReturn:
        del campaign_id
        self._reject("campaign resume")

    def request_cancel(self, campaign_id: str) -> NoReturn:
        del campaign_id
        self._reject("campaign cancel")

    def mark_cancelled(self, campaign_id: str) -> NoReturn:
        del campaign_id
        self._reject("campaign cancel transition")

    def complete(
        self,
        campaign_id: str,
        *,
        succeeded: bool,
        error: str | None = None,
    ) -> NoReturn:
        del campaign_id, succeeded, error
        self._reject("campaign completion")

    def get(self, campaign_id: str) -> CampaignRecord:
        record = self.__repository.get(campaign_id)
        if record is None:
            raise CampaignNotFoundError(f"campaign {campaign_id!r} was not found")
        return record

    def list(self) -> tuple[CampaignRecord, ...]:
        return self.__repository.list()


class ReadOnlyCampaignTimelineStore(_ReadOnlyBoundary):
    """Verified timeline reads with append denied before store mutation."""

    def __init__(self, store: JsonCampaignTimelineStore) -> None:
        self.__store = store

    def append(self, event: Any, *, evidence: Any = ()) -> NoReturn:
        del event, evidence
        self._reject("timeline append")

    def list(self, campaign_id: str):
        return self.__store.list(campaign_id)

    def latest(self, campaign_id: str):
        return self.__store.latest(campaign_id)

    def verify(self, campaign_id: str):
        return self.__store.verify(campaign_id)

    def replay(self, campaign_id: str, handler: Any) -> int:
        return self.__store.replay(campaign_id, handler)


class ReadOnlyCampaignEvidenceRecordStore(_ReadOnlyBoundary):
    """Verified evidence reads with append denied before store mutation."""

    def __init__(self, store: JsonCampaignEvidenceRecordStore) -> None:
        self.__store = store

    def append(self, record: Any) -> NoReturn:
        del record
        self._reject("evidence append")

    def get(self, campaign_id: str, evidence_id: str):
        return self.__store.get(campaign_id, evidence_id)

    def list(self, campaign_id: str):
        return self.__store.list(campaign_id)

    def latest(self, campaign_id: str):
        return self.__store.latest(campaign_id)

    def verify(self, campaign_id: str):
        return self.__store.verify(campaign_id)


@dataclass(frozen=True, slots=True)
class Agent4OperatorReadContext(_ReadOnlyBoundary):
    """The complete authority intentionally exposed by production read mode."""

    paths: Agent4RuntimePaths
    scheduler: ReadOnlyCampaignSchedulerFacade
    timeline: ReadOnlyCampaignTimelineStore
    evidence_records: ReadOnlyCampaignEvidenceRecordStore
    query: CampaignTimelineQueryService
    evidence_query: CampaignEvidenceQueryService
    operator: Agent4OperatorReadService
    evidence_operator: Agent4OperatorEvidenceReadService

    def recover(self) -> NoReturn:
        self._reject("recovery")

    def reconcile_projections(self) -> NoReturn:
        self._reject("projection reconciliation")


def _claim_canonical_root(root: Path, owner: ReadOnlyCampaignSchedulerFacade) -> None:
    """Share the full-runtime single-owner registry without creating a writer runtime."""

    canonical_root = _canonical_root(root)
    with _WRITER_ROOTS_LOCK:
        if _WRITER_ROOTS.get(canonical_root) is not None:
            raise CampaignValidationError(
                "an Agent 4 writer context already owns this canonical dataroot"
            )
        _WRITER_ROOTS[canonical_root] = owner


def compose_agent4_operator_read_context(root: Path | str) -> Agent4OperatorReadContext:
    """Compose only the canonical services required by the GET operator API."""

    paths = Agent4RuntimePaths.under(root)
    repository = JsonCampaignRepository(paths.campaigns)
    scheduler = ReadOnlyCampaignSchedulerFacade(repository)

    timeline = ReadOnlyCampaignTimelineStore(JsonCampaignTimelineStore(paths.timeline))
    evidence_records = ReadOnlyCampaignEvidenceRecordStore(
        JsonCampaignEvidenceRecordStore(paths.evidence)
    )
    query = CampaignTimelineQueryService(timeline)
    evidence_query = CampaignEvidenceQueryService(evidence_records)
    operator = Agent4OperatorReadService(
        scheduler=scheduler,
        timeline=timeline,
        query=query,
    )
    evidence_operator = Agent4OperatorEvidenceReadService(
        scheduler=scheduler,
        records=evidence_records,
        query=evidence_query,
    )

    # Claim only after every side-effect-free collaborator has validated.  The
    # shared weak registry also makes a later full writer composition for this
    # root fail closed in the same process, and vice versa.
    _claim_canonical_root(paths.root, scheduler)

    return Agent4OperatorReadContext(
        paths=paths,
        scheduler=scheduler,
        timeline=timeline,
        evidence_records=evidence_records,
        query=query,
        evidence_query=evidence_query,
        operator=operator,
        evidence_operator=evidence_operator,
    )
