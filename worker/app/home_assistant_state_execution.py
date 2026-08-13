"""Dormant one-shot Home Assistant state-read composition for T-038.

No concrete networking or credential handling lives here. A host-owned
``HomeAssistantStateTransport`` receives one already-authorized immutable
request plan. The coordinator owns the safety-sensitive ordering:

1. claim the exact one-use T-032 sharing receipt;
2. rebuild the request plan, which re-authorizes the durable T-038 grant after
   the claim and immediately before the single transport call;
3. accept one request-bound transport result and no retry;
4. parse the bounded Home Assistant state response;
5. fulfill through T-038's post-source re-authorization/freshness/audit boundary;
6. finish the common sharing receipt on every post-claim terminal path.

The transport contract reports logical externally-sent request bytes. A future
concrete transport must convert every after-send I/O failure into the typed
result rather than raising, so T-032 accounting can remain truthful.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .home_assistant_state_contract import parse_home_assistant_state
from .home_assistant_state_request import (
    HomeAssistantStateRequestDenied,
    HomeAssistantStateRequestPlan,
    build_home_assistant_state_request,
)
from .home_rig_connector_contract import (
    HomeRigAuditLog,
    HomeRigContractError,
    HomeRigDenied,
    HomeRigGrantStore,
)
from .home_rig_read_boundary import HomeRigReadClaim, HomeRigReadReceipt, fulfill_read
from .home_rig_read_lease import (
    HomeRigReadLease,
    HomeRigReadLeaseDenied,
    HomeRigReadSharingBoundary,
)

EXECUTION_SCHEMA = "kaliv-home-assistant-state-execution/v1"
TRANSPORT_SCHEMA = "kaliv-home-assistant-state-transport-result/v1"
PRODUCTION_ACTIVATION = False
_MAX_SHARING_BYTES = 4096
_MAX_RESPONSE_BYTES = 128 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class HomeAssistantStateExecutionError(HomeRigContractError):
    pass


class HomeAssistantStateExecutionDenied(HomeRigDenied):
    pass


def _time(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HomeAssistantStateExecutionError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class HomeAssistantStateTransportResult:
    """Transient one-shot transport outcome; raw response body has no serializer."""

    request_plan_sha256: str
    entity_id: str
    request_bytes_sent: int
    received_at: int
    status_code: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    error_code: str | None = None
    schema: str = TRANSPORT_SCHEMA
    attempts: int = 1
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != TRANSPORT_SCHEMA:
            raise HomeAssistantStateExecutionError("unsupported transport result schema")
        if self.production_activation is not False or self.attempts != 1:
            raise HomeAssistantStateExecutionError("transport result must remain dormant and one-shot")
        if not isinstance(self.request_plan_sha256, str) or not _SHA256.fullmatch(
            self.request_plan_sha256
        ):
            raise HomeAssistantStateExecutionError("transport request digest is invalid")
        if not isinstance(self.entity_id, str) or not self.entity_id:
            raise HomeAssistantStateExecutionError("transport entity identity is invalid")
        if (
            isinstance(self.request_bytes_sent, bool)
            or not isinstance(self.request_bytes_sent, int)
            or not 0 <= self.request_bytes_sent <= _MAX_SHARING_BYTES
        ):
            raise HomeAssistantStateExecutionError("transport request byte count is invalid")
        _time(self.received_at, "received_at")
        if self.error_code is not None:
            if not isinstance(self.error_code, str) or not _ERROR_CODE.fullmatch(self.error_code):
                raise HomeAssistantStateExecutionError("transport error code is invalid")
            if self.status_code is not None or self.content_type is not None or self.body is not None:
                raise HomeAssistantStateExecutionError(
                    "failed transport result cannot also contain a provider response"
                )
            return
        if (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 100 <= self.status_code <= 599
        ):
            raise HomeAssistantStateExecutionError("transport HTTP status is invalid")
        if not isinstance(self.content_type, str) or not self.content_type.strip():
            raise HomeAssistantStateExecutionError("transport content type is invalid")
        if not isinstance(self.body, bytes) or len(self.body) > _MAX_RESPONSE_BYTES:
            raise HomeAssistantStateExecutionError("transport response body is invalid")

    @property
    def succeeded(self) -> bool:
        return self.error_code is None


class HomeAssistantStateTransport(Protocol):
    """Host-owned transport seam; implementations perform at most one request.

    Provider/I/O failures after any request bytes may have been sent MUST be
    returned as ``HomeAssistantStateTransportResult(error_code=..., request_bytes_sent=...)``.
    Unexpected raised exceptions are contract failures and are assumed to occur
    before externally-sent bytes; concrete transports must have their own test
    proving that guarantee before activation.
    """

    def execute(self, plan: HomeAssistantStateRequestPlan) -> HomeAssistantStateTransportResult:
        ...


@dataclass(frozen=True)
class HomeAssistantStateExecutionResult:
    request_plan_sha256: str
    received_at: int
    read_receipt: HomeRigReadReceipt
    schema: str = EXECUTION_SCHEMA
    attempts: int = 1
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != EXECUTION_SCHEMA:
            raise HomeAssistantStateExecutionError("unsupported execution result schema")
        if self.production_activation is not False or self.attempts != 1:
            raise HomeAssistantStateExecutionError("execution result must remain dormant and one-shot")
        if not isinstance(self.request_plan_sha256, str) or not _SHA256.fullmatch(
            self.request_plan_sha256
        ):
            raise HomeAssistantStateExecutionError("execution request digest is invalid")
        _time(self.received_at, "received_at")
        if not isinstance(self.read_receipt, HomeRigReadReceipt):
            raise HomeAssistantStateExecutionError("execution requires T-038 read receipt")

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "request_plan_sha256": self.request_plan_sha256,
            "received_at": self.received_at,
            "attempts": 1,
            "read_receipt": self.read_receipt.to_dict(),
            "production_activation": False,
        }


class HomeAssistantStateExecutor:
    """One-shot composition from exact permission to normalized T-038 state."""

    def __init__(
        self,
        *,
        grants: HomeRigGrantStore,
        sharing: HomeRigReadSharingBoundary,
        audit: HomeRigAuditLog,
        transport: HomeAssistantStateTransport,
    ) -> None:
        if not isinstance(grants, HomeRigGrantStore):
            raise HomeAssistantStateExecutionError("executor requires HomeRigGrantStore")
        if not isinstance(sharing, HomeRigReadSharingBoundary):
            raise HomeAssistantStateExecutionError("executor requires HomeRigReadSharingBoundary")
        if not isinstance(audit, HomeRigAuditLog):
            raise HomeAssistantStateExecutionError("executor requires HomeRigAuditLog")
        if sharing.grants is not grants:
            raise HomeAssistantStateExecutionError("sharing boundary must use executor grant store")
        if not hasattr(transport, "execute") or not callable(transport.execute):
            raise HomeAssistantStateExecutionError("executor transport must implement execute")
        self._grants = grants
        self._sharing = sharing
        self._audit = audit
        self._transport = transport

    def _finish(
        self,
        lease: HomeRigReadLease,
        claim: HomeRigReadClaim,
        *,
        outcome: str,
        bytes_sent: int,
        error_code: str | None,
        now: int,
    ) -> None:
        try:
            self._sharing.complete(
                lease,
                claim,
                outcome=outcome,  # type: ignore[arg-type]
                bytes_sent=bytes_sent,
                error_code=error_code,
                now=now,
            )
        except HomeRigReadLeaseDenied as exc:
            raise HomeAssistantStateExecutionError(
                "sharing receipt could not reach terminal state"
            ) from exc

    def execute(
        self,
        lease: HomeRigReadLease,
        claim: HomeRigReadClaim,
        *,
        now: int,
        max_freshness_seconds: int = 120,
    ) -> HomeAssistantStateExecutionResult:
        if not isinstance(lease, HomeRigReadLease):
            raise HomeAssistantStateExecutionError("execution requires HomeRigReadLease")
        if not isinstance(claim, HomeRigReadClaim):
            raise HomeAssistantStateExecutionError("execution requires HomeRigReadClaim")
        started_at = _time(now, "execution time")

        # First consume the one-use external-processing authority. This call
        # itself re-authorizes grant/scope/policy and fails before transport.
        try:
            self._sharing.claim(lease, claim, now=started_at)
        except HomeRigReadLeaseDenied as exc:
            raise HomeAssistantStateExecutionDenied("provider read is not authorized") from exc

        # Re-authorize AGAIN after receipt claim and adjacent to the transport
        # call. If the operator revoked during the tiny claim->plan interval,
        # terminalize the already-claimed receipt without contacting provider.
        try:
            plan = build_home_assistant_state_request(
                self._grants,
                lease,
                claim,
                now=started_at,
            )
        except (HomeAssistantStateRequestDenied, HomeRigDenied) as exc:
            self._finish(
                lease,
                claim,
                outcome="blocked",
                bytes_sent=0,
                error_code="authority_changed",
                now=started_at,
            )
            raise HomeAssistantStateExecutionDenied("authority changed before provider read") from exc
        except HomeRigContractError as exc:
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=0,
                error_code="request_contract",
                now=started_at,
            )
            raise HomeAssistantStateExecutionError("provider request contract failed") from exc

        try:
            exchange = self._transport.execute(plan)
        except Exception as exc:
            # Transport implementations are required to return typed failures
            # once bytes can have left the process. An unexpected exception is
            # therefore a pre-send contract crash and is accounted as zero.
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=0,
                error_code="transport_contract",
                now=started_at,
            )
            raise HomeAssistantStateExecutionError("provider transport execution failed") from exc

        if not isinstance(exchange, HomeAssistantStateTransportResult):
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=0,
                error_code="transport_contract",
                now=started_at,
            )
            raise HomeAssistantStateExecutionError("provider transport returned invalid result")
        terminal_at = max(started_at, exchange.received_at)
        sent = exchange.request_bytes_sent

        if exchange.request_plan_sha256 != plan.digest or exchange.entity_id != plan.entity_id:
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=sent,
                error_code="transport_identity",
                now=terminal_at,
            )
            raise HomeAssistantStateExecutionError("provider transport identity drifted")
        if not exchange.succeeded:
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=sent,
                error_code=exchange.error_code,
                now=terminal_at,
            )
            raise HomeAssistantStateExecutionError("provider transport reported failure")
        if exchange.status_code != 200:
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=sent,
                error_code="provider_status",
                now=terminal_at,
            )
            raise HomeAssistantStateExecutionError("provider response status was not successful")
        content_type = (exchange.content_type or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=sent,
                error_code="content_type",
                now=terminal_at,
            )
            raise HomeAssistantStateExecutionError("provider response content type was invalid")

        try:
            evidence = parse_home_assistant_state(
                exchange.body or b"",
                expected_entity_id=plan.entity_id,
                received_at=exchange.received_at,
            )
        except HomeRigContractError as exc:
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=sent,
                error_code="invalid_response",
                now=terminal_at,
            )
            raise HomeAssistantStateExecutionError("provider response contract failed") from exc

        try:
            receipt = fulfill_read(
                self._grants,
                self._audit,
                claim,
                source_state=evidence.state,
                observed_at=evidence.observed_at,
                now=terminal_at,
                max_freshness_seconds=max_freshness_seconds,
            )
        except HomeRigDenied as exc:
            self._finish(
                lease,
                claim,
                outcome="blocked",
                bytes_sent=sent,
                error_code="revoked_in_flight",
                now=terminal_at,
            )
            raise HomeAssistantStateExecutionDenied("authority changed during provider read") from exc
        except HomeRigContractError as exc:
            self._finish(
                lease,
                claim,
                outcome="failed",
                bytes_sent=sent,
                error_code="source_contract",
                now=terminal_at,
            )
            raise HomeAssistantStateExecutionError("source fulfillment failed") from exc

        self._finish(
            lease,
            claim,
            outcome="completed",
            bytes_sent=sent,
            error_code=None,
            now=terminal_at,
        )
        return HomeAssistantStateExecutionResult(
            request_plan_sha256=plan.digest,
            received_at=terminal_at,
            read_receipt=receipt,
        )
