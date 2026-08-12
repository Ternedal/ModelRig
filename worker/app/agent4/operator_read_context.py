"""Narrow production composition for the Agent 4 GET-only operator surface.

Unlike the full caller-driven Agent 4 runtime, this module never constructs a
queue, resource lease manager, checkpoint/failure service or handoff scheduler.
It opens the canonical persisted read stores behind facades whose mutation
methods fail before touching storage. The resulting context is sufficient for
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
from .service import CampaignNotFoundError
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


class ReadOnlyCampaignReader:
    """Exactly the campaign get/list authority required by operator reads.

    This class deliberately does not inherit ``CampaignSchedulerService`` and
    therefore cannot accidentally acquire future lifecycle methods added to the
    scheduler. The repository is retained only to implement the two read calls.
    """

    def __init__(self, repository: JsonCampaignRepository) -> None:
        if not isinstance(repository, JsonCampaignRepository):
            raise CampaignValidationError(
                "read-only campaign reader requires JsonCampaignRepository"
            )
        self.__repository = repository

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
class Agent4OperatorReadContext:
    """The complete authority intentionally exposed by production read mode."""

    paths: Agent4RuntimePaths
    scheduler: ReadOnlyCampaignReader
    timeline: ReadOnlyCampaignTimelineStore
    evidence_records: ReadOnlyCampaignEvidenceRecordStore
    query: CampaignTimelineQueryService
    evidence_query: CampaignEvidenceQueryService
    operator: Agent4OperatorReadService
    evidence_operator: Agent4OperatorEvidenceReadService


def _claim_canonical_root(root: Path, owner: ReadOnlyCampaignReader) -> None:
    """Share the full-runtime single-owner registry without creating a writer runtime."""

    canonical_root = _canonical_root(root)
    with _WRITER_ROOTS_LOCK:
        if _WRITER_ROOTS.get(canonical_root) is not None:
            raise CampaignValidationError(
                "an Agent 4 context already owns this canonical dataroot"
            )
        _WRITER_ROOTS[canonical_root] = owner


def compose_agent4_operator_read_context(root: Path | str) -> Agent4OperatorReadContext:
    """Compose only the canonical services required by the GET operator API."""

    paths = Agent4RuntimePaths.under(root)
    repository = JsonCampaignRepository(paths.campaigns)
    scheduler = ReadOnlyCampaignReader(repository)

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

    # Claim only after every side-effect-free collaborator has validated. The
    # shared weak registry makes a later full writer composition for this root
    # fail closed in the same process, and vice versa.
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
