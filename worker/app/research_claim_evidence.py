"""Dormant verifiable in-flight evidence for the common data-sharing ledger.

The base v1 receipt proves authorization. This module adds an atomic claim result
that proves the exact receipt is currently in flight. It performs no network I/O,
registers no route or tool, and is intended for later peer-binding composition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .data_sharing import (
    RECEIPT_SCHEMA,
    DataSharingContractError,
    DataSharingDenied,
    DataSharingLedger,
    DataSharingReceipt,
    DataSharingRequest,
)
from .research_data_sharing import ResearchSharingIntent
from .research_sharing_boundary import (
    ResearchSharingBoundary,
    ResearchSharingBoundaryContractError,
    ResearchSharingLease,
)

CLAIM_EVIDENCE_SCHEMA = "kaliv-data-sharing-claim/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_ID = re.compile(r"^dsr_[a-z0-9._-]{1,96}$")
_PERMISSION_ID = re.compile(r"^dsp_[a-z0-9._-]{1,96}$")


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataSharingContractError(f"{name} must be a non-negative integer")
    return value


def _validate_receipt(receipt: DataSharingReceipt) -> None:
    if not isinstance(receipt, DataSharingReceipt):
        raise DataSharingContractError("receipt must be a DataSharingReceipt")
    if receipt.schema != RECEIPT_SCHEMA:
        raise DataSharingContractError("unsupported receipt schema")
    if not isinstance(receipt.receipt_id, str) or not _RECEIPT_ID.fullmatch(
        receipt.receipt_id
    ):
        raise DataSharingContractError("receipt_id has an invalid format")
    if not isinstance(receipt.request_digest, str) or not _SHA256.fullmatch(
        receipt.request_digest
    ):
        raise DataSharingContractError(
            "receipt request_digest must be a lowercase SHA-256 digest"
        )
    if receipt.authorization not in {"automatic", "permission"}:
        raise DataSharingContractError("receipt authorization is invalid")
    if receipt.authorization == "automatic" and receipt.permission_id is not None:
        raise DataSharingContractError(
            "automatic receipt cannot include permission_id"
        )
    if receipt.authorization == "permission":
        if not isinstance(receipt.permission_id, str) or not _PERMISSION_ID.fullmatch(
            receipt.permission_id
        ):
            raise DataSharingContractError(
                "permission receipt requires a valid permission_id"
            )
    _timestamp(receipt.authorized_at, "authorized_at")
    _timestamp(receipt.expires_at, "expires_at")
    if receipt.expires_at <= receipt.authorized_at:
        raise DataSharingContractError("receipt expiry must follow authorization")
    if (
        isinstance(receipt.max_bytes, bool)
        or not isinstance(receipt.max_bytes, int)
        or not 1 <= receipt.max_bytes <= 10_000_000
    ):
        raise DataSharingContractError("receipt max_bytes is invalid")


def _receipt_matches(row, receipt: DataSharingReceipt, request: DataSharingRequest) -> bool:
    return (
        row["receipt_id"] == receipt.receipt_id
        and row["request_digest"] == receipt.request_digest == request.digest
        and row["permission_id"] == receipt.permission_id
        and row["authorization"] == receipt.authorization
        and row["max_bytes"] == receipt.max_bytes
        and row["authorized_at"] == receipt.authorized_at
        and row["expires_at"] == receipt.expires_at
    )


@dataclass(frozen=True)
class DataSharingClaimEvidence:
    """Exact, database-verifiable proof that one receipt is currently in flight."""

    receipt_id: str
    request_digest: str
    max_bytes: int
    claimed_at: int
    expires_at: int
    schema: str = CLAIM_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CLAIM_EVIDENCE_SCHEMA:
            raise DataSharingContractError("unsupported claim evidence schema")
        if not isinstance(self.receipt_id, str) or not _RECEIPT_ID.fullmatch(
            self.receipt_id
        ):
            raise DataSharingContractError("claim receipt_id has an invalid format")
        if not isinstance(self.request_digest, str) or not _SHA256.fullmatch(
            self.request_digest
        ):
            raise DataSharingContractError(
                "claim request_digest must be a lowercase SHA-256 digest"
            )
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or not 1 <= self.max_bytes <= 10_000_000
        ):
            raise DataSharingContractError("claim max_bytes is invalid")
        _timestamp(self.claimed_at, "claimed_at")
        _timestamp(self.expires_at, "expires_at")
        if self.expires_at <= self.claimed_at:
            raise DataSharingContractError("claim expiry must follow claim time")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "max_bytes": self.max_bytes,
            "claimed_at": _iso(self.claimed_at),
            "expires_at": _iso(self.expires_at),
        }


class VerifiableDataSharingLedger(DataSharingLedger):
    """Common ledger variant whose atomic claim returns verifiable evidence."""

    def claim(
        self,
        receipt: DataSharingReceipt,
        request: DataSharingRequest,
        *,
        now: int | None = None,
    ) -> DataSharingClaimEvidence:
        timestamp = self._now(now)
        _validate_receipt(receipt)
        if not isinstance(request, DataSharingRequest):
            raise DataSharingContractError("request must be a DataSharingRequest")
        if receipt.request_digest != request.digest:
            raise DataSharingDenied("receipt does not match exact request")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT * FROM sharing_receipts WHERE receipt_id=?",
                    (receipt.receipt_id,),
                ).fetchone()
                if row is None or not _receipt_matches(row, receipt, request):
                    raise DataSharingDenied(
                        "receipt does not match the authoritative ledger row"
                    )
                if row["status"] != "authorized":
                    raise DataSharingDenied("receipt is not claimable")
                if row["expires_at"] <= timestamp:
                    self._db.execute(
                        "UPDATE sharing_receipts SET status='expired' WHERE receipt_id=?",
                        (receipt.receipt_id,),
                    )
                    raise DataSharingDenied("receipt expired")
                changed = self._db.execute(
                    "UPDATE sharing_receipts SET status='in_flight', claimed_at=? "
                    "WHERE receipt_id=? AND status='authorized'",
                    (timestamp, receipt.receipt_id),
                ).rowcount
                if changed != 1:
                    raise DataSharingDenied("receipt was already claimed")
                self._event(
                    request,
                    now=timestamp,
                    event_type="claimed",
                    permission_id=row["permission_id"],
                    receipt_id=row["receipt_id"],
                )
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        return DataSharingClaimEvidence(
            receipt_id=row["receipt_id"],
            request_digest=row["request_digest"],
            max_bytes=row["max_bytes"],
            claimed_at=timestamp,
            expires_at=row["expires_at"],
        )

    def verify_claim(
        self,
        evidence: DataSharingClaimEvidence,
        receipt: DataSharingReceipt,
        request: DataSharingRequest,
        *,
        now: int | None = None,
    ) -> None:
        timestamp = self._now(now)
        if not isinstance(evidence, DataSharingClaimEvidence):
            raise DataSharingContractError(
                "evidence must be DataSharingClaimEvidence"
            )
        _validate_receipt(receipt)
        if not isinstance(request, DataSharingRequest):
            raise DataSharingContractError("request must be a DataSharingRequest")
        if (
            evidence.receipt_id != receipt.receipt_id
            or evidence.request_digest != request.digest
            or receipt.request_digest != request.digest
            or evidence.max_bytes != receipt.max_bytes
            or evidence.expires_at != receipt.expires_at
        ):
            raise DataSharingDenied("claim evidence does not match the exact request")
        if evidence.expires_at <= timestamp:
            raise DataSharingDenied("claim evidence expired")
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM sharing_receipts WHERE receipt_id=?",
                (evidence.receipt_id,),
            ).fetchone()
        if row is None:
            raise DataSharingDenied("claim evidence references an unknown receipt")
        if (
            not _receipt_matches(row, receipt, request)
            or row["status"] != "in_flight"
            or row["claimed_at"] != evidence.claimed_at
            or row["max_bytes"] != evidence.max_bytes
            or row["expires_at"] != evidence.expires_at
        ):
            raise DataSharingDenied("claim evidence is not currently in flight")


class VerifiableResearchSharingBoundary(ResearchSharingBoundary):
    """Research boundary exposing the atomic common claim evidence."""

    def __init__(self, ledger: VerifiableDataSharingLedger, **kwargs) -> None:
        if not isinstance(ledger, VerifiableDataSharingLedger):
            raise ResearchSharingBoundaryContractError(
                "verifiable boundary requires VerifiableDataSharingLedger"
            )
        super().__init__(ledger, **kwargs)

    @property
    def verifiable_ledger(self) -> VerifiableDataSharingLedger:
        ledger = self.ledger
        assert isinstance(ledger, VerifiableDataSharingLedger)
        return ledger

    def claim(
        self,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        now: int | None = None,
    ) -> DataSharingClaimEvidence:
        receipt, request = self._bound(lease, intent)
        return self.verifiable_ledger.claim(receipt, request, now=now)

    def verify_claim(
        self,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        now: int | None = None,
    ) -> None:
        receipt, request = self._bound(lease, intent)
        self.verifiable_ledger.verify_claim(
            evidence,
            receipt,
            request,
            now=now,
        )
