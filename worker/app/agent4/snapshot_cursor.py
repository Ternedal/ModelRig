"""Root-bound cursor envelope for immutable Agent 4 operator snapshots (A4-25d)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, TypeAlias

from .campaign_list_query import CampaignListQueryCursor
from .domain import CampaignValidationError, JsonValue
from .timeline_evidence_query import CampaignEvidenceQueryCursor
from .timeline_query import CampaignTimelineQueryCursor

SNAPSHOT_BOUND_CURSOR_SCHEMA = "modelrig-agent4/snapshot-bound-cursor/v1"
_SNAPSHOT_ID = re.compile(r"^[0-9a-f]{64}$")

SnapshotInnerCursor: TypeAlias = (
    CampaignListQueryCursor
    | CampaignTimelineQueryCursor
    | CampaignEvidenceQueryCursor
)
SnapshotInnerCursorType: TypeAlias = (
    type[CampaignListQueryCursor]
    | type[CampaignTimelineQueryCursor]
    | type[CampaignEvidenceQueryCursor]
)


class OperatorSnapshotCursorError(RuntimeError):
    """Raised when a cursor cannot be bound to the selected immutable root."""


def require_operator_snapshot_id(value: object) -> str:
    if not isinstance(value, str) or not _SNAPSHOT_ID.fullmatch(value):
        raise CampaignValidationError(
            "snapshot_id must be 64 lowercase hexadecimal characters"
        )
    return value


@dataclass(frozen=True, slots=True)
class OperatorSnapshotCursor:
    """One existing hash-bound cursor additionally pinned to a root snapshot id."""

    snapshot_id: str
    cursor: SnapshotInnerCursor

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_id",
            require_operator_snapshot_id(self.snapshot_id),
        )
        if not isinstance(
            self.cursor,
            (
                CampaignListQueryCursor,
                CampaignTimelineQueryCursor,
                CampaignEvidenceQueryCursor,
            ),
        ):
            raise CampaignValidationError(
                "snapshot-bound cursor contains an unsupported inner cursor"
            )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": SNAPSHOT_BOUND_CURSOR_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "cursor": self.cursor.to_dict(),
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        cursor_type: SnapshotInnerCursorType,
    ) -> "OperatorSnapshotCursor":
        if not isinstance(value, Mapping):
            raise CampaignValidationError("snapshot-bound cursor must be an object")
        if value.get("schema") != SNAPSHOT_BOUND_CURSOR_SCHEMA:
            raise CampaignValidationError(
                "snapshot-bound cursor schema is not supported"
            )
        snapshot_id = value.get("snapshot_id")
        raw_cursor = value.get("cursor")
        if not isinstance(snapshot_id, str):
            raise CampaignValidationError(
                "snapshot-bound cursor snapshot_id must be text"
            )
        if not isinstance(raw_cursor, Mapping):
            raise CampaignValidationError(
                "snapshot-bound cursor must contain an inner cursor object"
            )
        return cls(
            snapshot_id=snapshot_id,
            cursor=cursor_type.from_dict(raw_cursor),
        )

    def require_snapshot(self, snapshot_id: str) -> SnapshotInnerCursor:
        selected = require_operator_snapshot_id(snapshot_id)
        if self.snapshot_id != selected:
            raise OperatorSnapshotCursorError(
                "snapshot-bound cursor refers to a different immutable root"
            )
        return self.cursor
