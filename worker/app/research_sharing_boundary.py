"""Dormant research execution boundary for common data-sharing v1.

The boundary performs no network I/O and is not imported by BrowserHost, ToolGate,
or an API route. It makes migration explicit: ``observe`` can inspect policy drift
but can never authorize bytes, while ``enforce`` requires a claimable common
receipt around the real external-processing boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from .data_sharing import (
    DEFAULT_POLICY,
    DataSharingContractError,
    DataSharingDenied,
    DataSharingLedger,
    DataSharingPolicy,
    DataSharingReceipt,
    Decision,
    Outcome,
)
from .research_data_sharing import ResearchSharingIntent

BOUNDARY_SCHEMA = "kaliv-research-sharing-boundary/v1"
BoundaryMode = Literal["observe", "enforce"]
_MODES = {"observe", "enforce"}
_DECISIONS = {"automatic", "confirmation_required", "forbidden"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ResearchSharingBoundaryContractError(DataSharingContractError):
    """The caller supplied an invalid migration mode, lease, or lifecycle input."""


class ResearchSharingBoundaryDenied(DataSharingDenied):
    """The requested lease cannot authorize this exact research operation."""


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def policy_digest(policy: DataSharingPolicy) -> str:
    if not isinstance(policy, DataSharingPolicy):
        raise ResearchSharingBoundaryContractError("policy must be a DataSharingPolicy")
    return hashlib.sha256(_canonical(policy.to_dict())).hexdigest()


def _require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ResearchSharingBoundaryContractError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class ResearchSharingLease:
    """Hash-bound migration lease; only an enforced lease may authorize bytes."""

    mode: BoundaryMode
    plan_digest: str
    request_digest: str
    policy_sha256: str
    decision: Decision
    receipt: DataSharingReceipt | None
    schema: str = BOUNDARY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != BOUNDARY_SCHEMA:
            raise ResearchSharingBoundaryContractError("unsupported boundary schema")
        if self.mode not in _MODES:
            raise ResearchSharingBoundaryContractError("boundary mode is invalid")
        if self.decision not in _DECISIONS:
            raise ResearchSharingBoundaryContractError("boundary decision is invalid")
        _require_digest(self.plan_digest, "plan_digest")
        _require_digest(self.request_digest, "request_digest")
        _require_digest(self.policy_sha256, "policy_sha256")
        if self.mode == "observe" and self.receipt is not None:
            raise ResearchSharingBoundaryContractError("observe leases cannot contain receipts")
        if self.mode == "enforce":
            if self.decision == "forbidden":
                raise ResearchSharingBoundaryContractError("forbidden requests cannot have enforced leases")
            if not isinstance(self.receipt, DataSharingReceipt):
                raise ResearchSharingBoundaryContractError("enforced leases require a receipt")
            if self.receipt.request_digest != self.request_digest:
                raise ResearchSharingBoundaryContractError("receipt does not match lease request")

    @property
    def may_send(self) -> bool:
        return self.mode == "enforce" and self.receipt is not None

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "mode": self.mode,
            "plan_digest": self.plan_digest,
            "request_digest": self.request_digest,
            "policy_sha256": self.policy_sha256,
            "decision": self.decision,
            "may_send": self.may_send,
            "receipt": self.receipt.to_dict() if self.receipt is not None else None,
        }


class ResearchSharingBoundary:
    """Prepare, claim, and finish common receipts for one research egress intent.

    ``observe`` is deliberately non-authorizing and side-effect free. ``enforce``
    delegates the permission/receipt lifecycle to ``DataSharingLedger``. The
    caller remains responsible for measuring the real number of externally sent
    bytes and reporting the terminal outcome; this module never guesses it.
    """

    def __init__(
        self,
        ledger: DataSharingLedger,
        *,
        mode: BoundaryMode,
        policy: DataSharingPolicy = DEFAULT_POLICY,
    ) -> None:
        if not isinstance(ledger, DataSharingLedger):
            raise ResearchSharingBoundaryContractError("ledger must be a DataSharingLedger")
        if mode not in _MODES:
            raise ResearchSharingBoundaryContractError("boundary mode is invalid")
        if not isinstance(policy, DataSharingPolicy):
            raise ResearchSharingBoundaryContractError("policy must be a DataSharingPolicy")
        self.ledger = ledger
        self.mode = mode
        self.policy = policy
        self.policy_sha256 = policy_digest(policy)

    @staticmethod
    def _intent(intent: ResearchSharingIntent) -> ResearchSharingIntent:
        if not isinstance(intent, ResearchSharingIntent):
            raise ResearchSharingBoundaryContractError("intent must be a ResearchSharingIntent")
        return intent

    def inspect(self, intent: ResearchSharingIntent) -> dict:
        intent = self._intent(intent)
        preview = intent.preview(self.policy)
        return {
            "schema": BOUNDARY_SCHEMA,
            "mode": self.mode,
            "policy_sha256": self.policy_sha256,
            "may_send": False,
            "migration": preview,
        }

    def prepare(
        self,
        intent: ResearchSharingIntent,
        *,
        permission_id: str | None = None,
        now: int | None = None,
        receipt_ttl_seconds: int = 60,
    ) -> ResearchSharingLease:
        intent = self._intent(intent)
        request = intent.to_request()
        decision = self.policy.decision(request)
        if self.mode == "observe":
            if permission_id is not None:
                raise ResearchSharingBoundaryContractError(
                    "observe mode cannot accept or consume a permission"
                )
            return ResearchSharingLease(
                mode="observe",
                plan_digest=intent.plan.digest,
                request_digest=request.digest,
                policy_sha256=self.policy_sha256,
                decision=decision,
                receipt=None,
            )
        receipt = self.ledger.authorize(
            request,
            policy=self.policy,
            permission_id=permission_id,
            now=now,
            receipt_ttl_seconds=receipt_ttl_seconds,
        )
        return ResearchSharingLease(
            mode="enforce",
            plan_digest=intent.plan.digest,
            request_digest=request.digest,
            policy_sha256=self.policy_sha256,
            decision=decision,
            receipt=receipt,
        )

    def _bound(
        self,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
    ) -> tuple[DataSharingReceipt, object]:
        if not isinstance(lease, ResearchSharingLease):
            raise ResearchSharingBoundaryContractError("lease must be a ResearchSharingLease")
        intent = self._intent(intent)
        request = intent.to_request()
        if self.mode != "enforce" or lease.mode != "enforce":
            raise ResearchSharingBoundaryDenied("observe mode cannot authorize external processing")
        if lease.policy_sha256 != self.policy_sha256:
            raise ResearchSharingBoundaryDenied("lease was created under a different policy")
        if lease.plan_digest != intent.plan.digest or lease.request_digest != request.digest:
            raise ResearchSharingBoundaryDenied("lease does not match the exact research intent")
        if lease.receipt is None or lease.receipt.request_digest != request.digest:
            raise ResearchSharingBoundaryDenied("lease has no exact common receipt")
        return lease.receipt, request

    def claim(
        self,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        now: int | None = None,
    ) -> None:
        receipt, request = self._bound(lease, intent)
        self.ledger.claim(receipt, request, now=now)

    def complete(
        self,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        outcome: Outcome,
        bytes_sent: int,
        error_code: str | None = None,
        now: int | None = None,
    ) -> None:
        receipt, request = self._bound(lease, intent)
        self.ledger.complete(
            receipt,
            request,
            outcome=outcome,
            bytes_sent=bytes_sent,
            error_code=error_code,
            now=now,
        )

    def record_local_fallback(
        self,
        intent: ResearchSharingIntent,
        *,
        reason_code: str,
        now: int | None = None,
    ) -> None:
        intent = self._intent(intent)
        if self.mode != "enforce":
            raise ResearchSharingBoundaryDenied("observe mode is side-effect free")
        self.ledger.record_local_fallback(
            intent.to_request(),
            reason_code=reason_code,
            now=now,
        )
