"""Stable, bounded and hash-bound paging for Agent 4 campaign lists.

The query owns no storage and keeps no server-side session. Every page is derived
from caller-supplied canonical records and their verified display summaries. A
cursor binds status filters, position, last identity, total count and the
SHA-256 of the complete ordered snapshot. If a campaign record or any displayed
timeline/evidence summary changes between pages, the next read fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .domain import CampaignRecord, CampaignStatus, CampaignValidationError, JsonValue

CAMPAIGN_LIST_CURSOR_SCHEMA = "modelrig-agent4/campaign-list-query-cursor/v1"
MAX_CAMPAIGN_LIST_PAGE_SIZE = 1_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CampaignListQueryError(RuntimeError):
    """Raised when a campaign-list snapshot or cursor cannot be trusted."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def normalize_statuses(
    values: CampaignStatus | str | Iterable[CampaignStatus | str] | None,
) -> tuple[CampaignStatus, ...]:
    if values is None:
        return ()
    if isinstance(values, (CampaignStatus, str)):
        candidates: tuple[CampaignStatus | str, ...] = (values,)
    else:
        try:
            candidates = tuple(values)
        except TypeError as exc:
            raise CampaignValidationError("statuses must be iterable") from exc
    normalized: set[CampaignStatus] = set()
    try:
        for value in candidates:
            normalized.add(CampaignStatus(value))
    except (TypeError, ValueError) as exc:
        raise CampaignValidationError("statuses contain an unsupported value") from exc
    return tuple(sorted(normalized, key=lambda item: item.value))


def _require_limit(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_CAMPAIGN_LIST_PAGE_SIZE
    ):
        raise CampaignValidationError(
            "limit must be an integer between 1 and "
            f"{MAX_CAMPAIGN_LIST_PAGE_SIZE}"
        )
    return value


@dataclass(frozen=True, slots=True)
class CampaignListSnapshotSummary:
    """Canonical campaign-list fields rendered beside one campaign record."""

    timeline_entries: int
    event_entries: int
    evidence_entries: int
    latest_timeline_hash: str | None

    def __post_init__(self) -> None:
        for name in ("timeline_entries", "event_entries", "evidence_entries"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CampaignValidationError(
                    f"campaign-list summary {name} must be a non-negative integer"
                )
        digest = self.latest_timeline_hash
        if digest is None:
            return
        if digest.startswith("sha256:"):
            digest = digest[7:]
        if not _SHA256.fullmatch(digest):
            raise CampaignValidationError(
                "campaign-list summary latest_timeline_hash must be lowercase SHA-256"
            )
        object.__setattr__(self, "latest_timeline_hash", digest)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "timeline_entries": self.timeline_entries,
            "event_entries": self.event_entries,
            "evidence_entries": self.evidence_entries,
            "latest_timeline_hash": (
                f"sha256:{self.latest_timeline_hash}"
                if self.latest_timeline_hash is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class CampaignListQueryCursor:
    statuses: tuple[CampaignStatus, ...]
    position: int
    total: int
    last_campaign_id: str | None
    snapshot_sha256: str

    def __post_init__(self) -> None:
        normalized = normalize_statuses(self.statuses)
        if len(normalized) != len(tuple(self.statuses)):
            raise CampaignValidationError("campaign-list cursor statuses must be unique")
        object.__setattr__(self, "statuses", normalized)
        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or self.position < 0
        ):
            raise CampaignValidationError("campaign-list cursor position is invalid")
        if isinstance(self.total, bool) or not isinstance(self.total, int) or self.total < 0:
            raise CampaignValidationError("campaign-list cursor total is invalid")
        if self.position > self.total:
            raise CampaignValidationError("campaign-list cursor position exceeds total")
        last = self.last_campaign_id
        if self.position == 0:
            if last is not None:
                raise CampaignValidationError(
                    "campaign-list genesis cursor must not declare last_campaign_id"
                )
        elif not isinstance(last, str) or not last.strip() or last != last.strip():
            raise CampaignValidationError(
                "campaign-list cursor requires last_campaign_id after position zero"
            )
        digest = self.snapshot_sha256
        if digest.startswith("sha256:"):
            digest = digest[7:]
        if not _SHA256.fullmatch(digest):
            raise CampaignValidationError(
                "campaign-list cursor snapshot_sha256 must be lowercase SHA-256"
            )
        object.__setattr__(self, "snapshot_sha256", digest)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": CAMPAIGN_LIST_CURSOR_SCHEMA,
            "statuses": [status.value for status in self.statuses],
            "position": self.position,
            "total": self.total,
            "last_campaign_id": self.last_campaign_id,
            "snapshot_sha256": f"sha256:{self.snapshot_sha256}",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CampaignListQueryCursor":
        if not isinstance(value, Mapping):
            raise CampaignValidationError("campaign-list cursor must be an object")
        if value.get("schema") != CAMPAIGN_LIST_CURSOR_SCHEMA:
            raise CampaignValidationError("campaign-list cursor schema is unsupported")
        raw_statuses = value.get("statuses")
        if not isinstance(raw_statuses, list) or any(
            not isinstance(item, str) for item in raw_statuses
        ):
            raise CampaignValidationError("campaign-list cursor statuses must be a list")
        position = value.get("position")
        total = value.get("total")
        last = value.get("last_campaign_id")
        digest = value.get("snapshot_sha256")
        if isinstance(position, bool) or not isinstance(position, int):
            raise CampaignValidationError("campaign-list cursor position must be integer")
        if isinstance(total, bool) or not isinstance(total, int):
            raise CampaignValidationError("campaign-list cursor total must be integer")
        if last is not None and not isinstance(last, str):
            raise CampaignValidationError(
                "campaign-list cursor last_campaign_id must be text or null"
            )
        if not isinstance(digest, str):
            raise CampaignValidationError(
                "campaign-list cursor snapshot_sha256 must be text"
            )
        return cls(
            statuses=tuple(CampaignStatus(item) for item in raw_statuses),
            position=position,
            total=total,
            last_campaign_id=last,
            snapshot_sha256=digest,
        )


@dataclass(frozen=True, slots=True)
class CampaignListRecordPage:
    records: tuple[CampaignRecord, ...]
    start_cursor: CampaignListQueryCursor
    next_cursor: CampaignListQueryCursor
    head_cursor: CampaignListQueryCursor
    has_more: bool


def select_campaign_records(
    records: Sequence[CampaignRecord],
    statuses: CampaignStatus | str | Iterable[CampaignStatus | str] | None = None,
) -> tuple[tuple[CampaignStatus, ...], tuple[CampaignRecord, ...]]:
    """Return the canonical status filter and newest-first selected snapshot.

    This is deliberately reusable by the operator layer so expensive timeline /
    evidence verification can be limited to records that actually participate in
    the requested snapshot. Keeping filtering and ordering here prevents the
    operator and cursor layers from drifting apart.
    """

    normalized_statuses = normalize_statuses(statuses)
    accepted = frozenset(normalized_statuses)
    selected = (
        record
        for record in records
        if not accepted or record.state.status in accepted
    )
    ordered = tuple(
        sorted(
            selected,
            key=lambda record: (record.spec.created_at, record.spec.campaign_id),
            reverse=True,
        )
    )
    return normalized_statuses, ordered


def _snapshot_digest(
    records: tuple[CampaignRecord, ...],
    statuses: tuple[CampaignStatus, ...],
    summaries: Mapping[str, CampaignListSnapshotSummary],
) -> str:
    snapshot: list[dict[str, JsonValue]] = []
    for record in records:
        campaign_id = record.spec.campaign_id
        summary = summaries.get(campaign_id)
        if not isinstance(summary, CampaignListSnapshotSummary):
            raise CampaignValidationError(
                f"campaign-list summary is missing for {campaign_id!r}"
            )
        snapshot.append(
            {
                "record": record.to_dict(),
                "summary": summary.to_dict(),
            }
        )
    payload = {
        "schema": "modelrig-agent4/campaign-list-snapshot/v2",
        "statuses": [status.value for status in statuses],
        "campaigns": snapshot,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _cursor_at(
    records: tuple[CampaignRecord, ...],
    statuses: tuple[CampaignStatus, ...],
    snapshot_sha256: str,
    position: int,
) -> CampaignListQueryCursor:
    return CampaignListQueryCursor(
        statuses=statuses,
        position=position,
        total=len(records),
        last_campaign_id=(
            records[position - 1].spec.campaign_id if position > 0 else None
        ),
        snapshot_sha256=snapshot_sha256,
    )


def page_campaign_records(
    records: Sequence[CampaignRecord],
    *,
    summaries: Mapping[str, CampaignListSnapshotSummary],
    statuses: CampaignStatus | str | Iterable[CampaignStatus | str] | None = None,
    after: CampaignListQueryCursor | None = None,
    snapshot_head: CampaignListQueryCursor | None = None,
    limit: int = 100,
) -> CampaignListRecordPage:
    """Return one page or reject any selected record, summary, filter or cursor drift."""

    if not isinstance(summaries, Mapping):
        raise CampaignValidationError("campaign-list summaries must be a mapping")
    bounded_limit = _require_limit(limit)
    normalized_statuses, ordered = select_campaign_records(records, statuses)
    digest = _snapshot_digest(ordered, normalized_statuses, summaries)
    current_head = _cursor_at(
        ordered,
        normalized_statuses,
        digest,
        len(ordered),
    )

    if after is None:
        if snapshot_head is not None:
            raise CampaignListQueryError(
                "campaign-list snapshot_head requires an after cursor"
            )
        start = _cursor_at(ordered, normalized_statuses, digest, 0)
        bound_head = current_head
    else:
        if snapshot_head is None:
            raise CampaignListQueryError(
                "campaign-list after cursor requires snapshot_head"
            )
        for label, cursor in (("after", after), ("snapshot_head", snapshot_head)):
            if cursor.statuses != normalized_statuses:
                raise CampaignListQueryError(
                    f"campaign-list {label} cursor does not match status filter"
                )
            if cursor.snapshot_sha256 != digest or cursor.total != len(ordered):
                raise CampaignListQueryError(
                    f"campaign-list {label} cursor refers to a stale snapshot"
                )
            if cursor.position > len(ordered):
                raise CampaignListQueryError(
                    f"campaign-list {label} cursor exceeds snapshot"
                )
            expected_last = (
                ordered[cursor.position - 1].spec.campaign_id
                if cursor.position > 0
                else None
            )
            if cursor.last_campaign_id != expected_last:
                raise CampaignListQueryError(
                    f"campaign-list {label} cursor identity does not match snapshot"
                )
        if snapshot_head != current_head:
            raise CampaignListQueryError(
                "campaign-list snapshot_head does not match current snapshot head"
            )
        if after.position > snapshot_head.position:
            raise CampaignListQueryError(
                "campaign-list after cursor exceeds snapshot head"
            )
        start = after
        bound_head = snapshot_head

    end = min(start.position + bounded_limit, len(ordered))
    return CampaignListRecordPage(
        records=ordered[start.position:end],
        start_cursor=start,
        next_cursor=_cursor_at(ordered, normalized_statuses, digest, end),
        head_cursor=bound_head,
        has_more=end < len(ordered),
    )
