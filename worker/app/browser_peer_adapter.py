"""Dormant CDP-event bridge for claim-bound browser peer transfers.

The adapter does not call Chrome DevTools Protocol, open sockets, start a browser
or activate a route. It translates one paused read-only CDP request into the
existing common peer-authorization and peer-transfer state machines. A separate,
injected transport controller must prove that the selected public address is
pinned *before* the caller may continue the paused request.

Completion consumes Network.responseReceived-style evidence, requires the actual
remote address and port to match the pinned peer, and terminalizes the measured
byte meter. CDP request/response correlation is explicit; raw URL path/query,
research purpose, summary and content never appear in serialized permits.
"""
from __future__ import annotations

import ipaddress
import re
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from .research_claim_evidence import DataSharingClaimEvidence
from .research_contract import ResearchContractError, canonicalize_url
from .research_data_sharing import ResearchSharingIntent
from .research_peer_authorization import (
    ResearchPeerAuthorization,
    ResearchPeerAuthorizationBridge,
    ResearchPeerAuthorizationDenied,
)
from .research_peer_transfer import (
    ResearchPeerBinding,
    ResearchPeerTransfer,
    ResearchPeerTransferContractError,
    ResearchPeerTransferDenied,
    ResearchPeerTransferLedger,
)
from .research_sharing_boundary import ResearchSharingLease
from .research_sharing_execution import ResearchExternalBlocked

BROWSER_PEER_ADAPTER_SCHEMA = "kaliv-browser-peer-adapter/v1"
_PIN_SCHEMA = "kaliv-browser-peer-pin/v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PIN_ID = re.compile(r"^bpp_[a-z0-9._-]{1,96}$")
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_READ_METHODS = frozenset({"GET", "HEAD"})
_FORBIDDEN_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "proxy-authenticate",
    }
)
_PERMIT_TOKEN = object()


class BrowserPeerAdapterContractError(ValueError):
    """A CDP event, transport pin or adapter input is malformed."""


class BrowserPeerAdapterDenied(PermissionError):
    """The request could not cross the peer-bound browser boundary."""


def _request_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise BrowserPeerAdapterContractError(f"{name} is invalid")
    return value


def _timestamp(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BrowserPeerAdapterContractError(
            f"{name} must be a non-negative integer timestamp"
        )
    return value


def _public_address(value: Any) -> str:
    if not isinstance(value, str):
        raise BrowserPeerAdapterContractError("remoteIPAddress must be a string")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise BrowserPeerAdapterContractError(
            "remoteIPAddress is invalid"
        ) from exc
    if not address.is_global:
        raise BrowserPeerAdapterDenied("browser reported a non-public remote peer")
    return address.compressed


def _port(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise BrowserPeerAdapterContractError(f"{name} is invalid")
    return value


def _error_code(value: str) -> str:
    if not isinstance(value, str) or not _ERROR_CODE.fullmatch(value):
        raise BrowserPeerAdapterContractError("error_code is invalid")
    return value


def _canonical_url(value: Any) -> str:
    if not isinstance(value, str):
        raise BrowserPeerAdapterContractError("request URL must be a string")
    try:
        return canonicalize_url(value)
    except ResearchContractError as exc:
        raise BrowserPeerAdapterDenied("request URL is outside the web contract") from exc


def _headers(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BrowserPeerAdapterContractError("request headers must be an object")
    normalized: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        if not isinstance(raw_name, str) or not isinstance(raw_value, str):
            raise BrowserPeerAdapterContractError(
                "request headers must contain string names and values"
            )
        name = raw_name.strip().lower()
        if not name:
            raise BrowserPeerAdapterContractError("request header name is empty")
        normalized[name] = raw_value
    if _FORBIDDEN_HEADERS.intersection(normalized):
        raise BrowserPeerAdapterDenied(
            "credential-bearing browser headers are forbidden"
        )
    return normalized


@dataclass(frozen=True)
class BrowserPeerPinReceipt:
    """Proof from an injected transport controller that one peer is pinned."""

    pin_id: str
    binding_id: str
    cdp_request_id: str
    network_request_id: str
    host: str
    port: int
    selected_address: str
    expires_at: int
    transport_enforced: bool = True
    production_activation: bool = False
    schema: str = _PIN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _PIN_SCHEMA:
            raise BrowserPeerAdapterContractError("unsupported pin receipt schema")
        if not isinstance(self.pin_id, str) or not _PIN_ID.fullmatch(self.pin_id):
            raise BrowserPeerAdapterContractError("pin_id is invalid")
        if not isinstance(self.binding_id, str) or not self.binding_id.startswith("rpt_"):
            raise BrowserPeerAdapterContractError("binding_id is invalid")
        _request_id(self.cdp_request_id, "cdp_request_id")
        _request_id(self.network_request_id, "network_request_id")
        if not isinstance(self.host, str) or not self.host:
            raise BrowserPeerAdapterContractError("pin host is invalid")
        _port(self.port, "pin port")
        try:
            normalized = _public_address(self.selected_address)
        except BrowserPeerAdapterDenied as exc:
            raise BrowserPeerAdapterContractError(
                "pin selected_address is not public"
            ) from exc
        if normalized != self.selected_address:
            raise BrowserPeerAdapterContractError(
                "pin selected_address must be canonical"
            )
        _timestamp(self.expires_at, "pin expires_at")
        if self.transport_enforced is not True:
            raise BrowserPeerAdapterContractError(
                "pin receipt must prove transport enforcement"
            )
        if self.production_activation is not False:
            raise BrowserPeerAdapterContractError(
                "pin receipt cannot activate production"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "pin_id": self.pin_id,
            "binding_id": self.binding_id,
            "cdp_request_id": self.cdp_request_id,
            "network_request_id": self.network_request_id,
            "host": self.host,
            "port": self.port,
            "selected_address": self.selected_address,
            "expires_at": self.expires_at,
            "transport_enforced": self.transport_enforced,
            "production_activation": self.production_activation,
        }


class BrowserPeerTransport(Protocol):
    """Future runtime seam that must pin transport before CDP continuation."""

    def pin(
        self,
        binding: ResearchPeerBinding,
        *,
        cdp_request_id: str,
        network_request_id: str,
    ) -> BrowserPeerPinReceipt:
        ...

    def release(self, receipt: BrowserPeerPinReceipt) -> None:
        ...


class BrowserPeerPermit:
    """One claimed request permit with a transport-bound byte meter."""

    def __init__(
        self,
        *,
        request_id: str,
        network_id: str,
        canonical_url: str,
        authorization: ResearchPeerAuthorization,
        binding: ResearchPeerBinding,
        transfer: ResearchPeerTransfer,
        pin: BrowserPeerPinReceipt,
        token: object,
    ) -> None:
        if token is not _PERMIT_TOKEN:
            raise BrowserPeerAdapterContractError(
                "browser peer permits must be created by BrowserPeerAdapter"
            )
        self.request_id = request_id
        self.network_id = network_id
        self.authorization = authorization
        self.binding = binding
        self.pin = pin
        self._canonical_url = canonical_url
        self._transfer = transfer
        self._lock = threading.Lock()
        self._terminal = False

    @property
    def selected_address(self) -> str:
        return self.binding.selected_address

    @property
    def bytes_sent(self) -> int:
        return self._transfer.bytes_sent

    def record_sent(self, count: int) -> int:
        with self._lock:
            if self._terminal:
                raise BrowserPeerAdapterDenied("browser peer permit is terminal")
            return self._transfer.record_sent(count)

    def _mark_terminal(self) -> None:
        with self._lock:
            if self._terminal:
                raise BrowserPeerAdapterDenied("browser peer permit is terminal")
            self._terminal = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BROWSER_PEER_ADAPTER_SCHEMA,
            "cdp_request_id": self.request_id,
            "network_request_id": self.network_id,
            "authorization_id": self.authorization.authorization_id,
            "binding_id": self.binding.binding_id,
            "url_sha256": self.binding.url_sha256,
            "selected_address": self.selected_address,
            "port": self.binding.port,
            "max_bytes": self.binding.max_bytes,
            "pin": self.pin.to_dict(),
            "production_activation": False,
        }


class BrowserPeerAdapter:
    """Translate paused CDP requests into transport-enforced peer permits."""

    def __init__(
        self,
        bridge: ResearchPeerAuthorizationBridge,
        ledger: ResearchPeerTransferLedger,
        transport: BrowserPeerTransport,
    ) -> None:
        if not isinstance(bridge, ResearchPeerAuthorizationBridge):
            raise BrowserPeerAdapterContractError(
                "adapter requires ResearchPeerAuthorizationBridge"
            )
        if not isinstance(ledger, ResearchPeerTransferLedger):
            raise BrowserPeerAdapterContractError(
                "adapter requires ResearchPeerTransferLedger"
            )
        if not callable(getattr(transport, "pin", None)) or not callable(
            getattr(transport, "release", None)
        ):
            raise BrowserPeerAdapterContractError(
                "transport must provide pin and release"
            )
        self._bridge = bridge
        self._ledger = ledger
        self._transport = transport

    @staticmethod
    def _paused_request(event: Any) -> tuple[str, str, str]:
        if not isinstance(event, dict):
            raise BrowserPeerAdapterContractError(
                "Fetch.requestPaused event must be an object"
            )
        request_id = _request_id(event.get("requestId"), "requestId")
        network_id = _request_id(event.get("networkId"), "networkId")
        request = event.get("request")
        if not isinstance(request, dict):
            raise BrowserPeerAdapterContractError("paused request is missing")
        method = request.get("method")
        if not isinstance(method, str) or method.upper() not in _READ_METHODS:
            raise BrowserPeerAdapterDenied("only GET and HEAD browser requests are allowed")
        if request.get("hasPostData") is True or request.get("postData") not in {
            None,
            "",
        }:
            raise BrowserPeerAdapterDenied("browser request body is forbidden")
        _headers(request.get("headers"))
        return request_id, network_id, _canonical_url(request.get("url"))

    @staticmethod
    def _pin_matches(
        pin: BrowserPeerPinReceipt,
        binding: ResearchPeerBinding,
        request_id: str,
        network_id: str,
    ) -> bool:
        return (
            isinstance(pin, BrowserPeerPinReceipt)
            and pin.binding_id == binding.binding_id
            and pin.cdp_request_id == request_id
            and pin.network_request_id == network_id
            and pin.host == binding.host
            and pin.port == binding.port
            and pin.selected_address == binding.selected_address
            and pin.expires_at == binding.expires_at
            and pin.transport_enforced is True
            and pin.production_activation is False
        )

    def _terminal_block(
        self,
        permit: BrowserPeerPermit,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        error_code: str,
        now: int,
        peer_address: str | None = None,
        release: bool = True,
    ) -> None:
        code = _error_code(error_code)
        if release:
            try:
                self._transport.release(permit.pin)
            except Exception:
                code = "transport_release_failed"
        try:
            self._ledger.complete(
                permit._transfer,
                permit.authorization,
                evidence,
                lease,
                intent,
                permit._canonical_url,
                outcome="blocked",
                peer_address=peer_address,
                error_code=code,
                now=now,
            )
        except ResearchPeerTransferDenied:
            pass
        permit._mark_terminal()
        raise BrowserPeerAdapterDenied(code)

    def prepare_request(
        self,
        event: Any,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        now: int,
        ttl_seconds: int = 30,
    ) -> BrowserPeerPermit:
        timestamp = _timestamp(now, "now")
        request_id, network_id, canonical_url = self._paused_request(event)
        try:
            authorization = self._bridge.prepare(
                evidence,
                lease,
                intent,
                canonical_url,
                now=timestamp,
            )
            binding = self._ledger.issue(
                authorization,
                evidence,
                lease,
                intent,
                canonical_url,
                now=timestamp,
                ttl_seconds=ttl_seconds,
            )
            transfer = self._ledger.claim(
                binding,
                authorization,
                evidence,
                lease,
                intent,
                canonical_url,
                now=timestamp,
            )
        except (
            ResearchPeerAuthorizationDenied,
            ResearchPeerTransferDenied,
        ) as exc:
            raise BrowserPeerAdapterDenied(
                "common peer authorization could not be claimed"
            ) from exc
        except ResearchPeerTransferContractError as exc:
            raise BrowserPeerAdapterContractError(
                "peer-transfer contract rejected the request"
            ) from exc

        try:
            pin = self._transport.pin(
                binding,
                cdp_request_id=request_id,
                network_request_id=network_id,
            )
        except Exception as exc:
            permit = BrowserPeerPermit(
                request_id=request_id,
                network_id=network_id,
                canonical_url=canonical_url,
                authorization=authorization,
                binding=binding,
                transfer=transfer,
                pin=BrowserPeerPinReceipt(
                    pin_id="bpp_failed",
                    binding_id=binding.binding_id,
                    cdp_request_id=request_id,
                    network_request_id=network_id,
                    host=binding.host,
                    port=binding.port,
                    selected_address=binding.selected_address,
                    expires_at=binding.expires_at,
                ),
                token=_PERMIT_TOKEN,
            )
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="transport_pin_failed",
                now=timestamp,
                release=False,
            )
            raise AssertionError("unreachable") from exc

        if not self._pin_matches(pin, binding, request_id, network_id):
            permit = BrowserPeerPermit(
                request_id=request_id,
                network_id=network_id,
                canonical_url=canonical_url,
                authorization=authorization,
                binding=binding,
                transfer=transfer,
                pin=pin,
                token=_PERMIT_TOKEN,
            )
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="transport_pin_mismatch",
                now=timestamp,
            )
        return BrowserPeerPermit(
            request_id=request_id,
            network_id=network_id,
            canonical_url=canonical_url,
            authorization=authorization,
            binding=binding,
            transfer=transfer,
            pin=pin,
            token=_PERMIT_TOKEN,
        )

    def complete_response(
        self,
        permit: BrowserPeerPermit,
        event: Any,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        now: int,
    ) -> None:
        if not isinstance(permit, BrowserPeerPermit):
            raise BrowserPeerAdapterContractError(
                "permit must be a BrowserPeerPermit"
            )
        timestamp = _timestamp(now, "now")
        if not isinstance(event, dict):
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="response_evidence_invalid",
                now=timestamp,
            )
        try:
            network_id = _request_id(event.get("requestId"), "response requestId")
            response = event.get("response")
            if not isinstance(response, dict):
                raise BrowserPeerAdapterContractError("response evidence is missing")
            response_url = _canonical_url(response.get("url"))
            remote_address = _public_address(response.get("remoteIPAddress"))
            remote_port = _port(response.get("remotePort"), "remotePort")
            cached = any(
                response.get(name) is True
                for name in (
                    "fromDiskCache",
                    "fromServiceWorker",
                    "fromPrefetchCache",
                )
            )
        except (BrowserPeerAdapterContractError, BrowserPeerAdapterDenied):
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="response_evidence_invalid",
                now=timestamp,
            )
            raise AssertionError("unreachable")
        if network_id != permit.network_id:
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="response_request_mismatch",
                now=timestamp,
                peer_address=remote_address,
            )
        if response_url != permit._canonical_url:
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="response_url_mismatch",
                now=timestamp,
                peer_address=remote_address,
            )
        if cached:
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="response_peer_unobservable",
                now=timestamp,
            )
        if remote_port != permit.binding.port:
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="response_port_mismatch",
                now=timestamp,
                peer_address=remote_address,
            )
        try:
            self._transport.release(permit.pin)
        except Exception:
            self._terminal_block(
                permit,
                evidence,
                lease,
                intent,
                error_code="transport_release_failed",
                now=timestamp,
                peer_address=remote_address,
                release=False,
            )
        try:
            self._ledger.complete(
                permit._transfer,
                permit.authorization,
                evidence,
                lease,
                intent,
                permit._canonical_url,
                outcome="connected",
                peer_address=remote_address,
                now=timestamp,
            )
        except ResearchPeerTransferDenied as exc:
            permit._mark_terminal()
            raise BrowserPeerAdapterDenied(
                "connected peer did not satisfy the claimed binding"
            ) from exc
        permit._mark_terminal()

    def abort_request(
        self,
        permit: BrowserPeerPermit,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        *,
        error_code: str,
        now: int,
    ) -> None:
        if not isinstance(permit, BrowserPeerPermit):
            raise BrowserPeerAdapterContractError(
                "permit must be a BrowserPeerPermit"
            )
        self._terminal_block(
            permit,
            evidence,
            lease,
            intent,
            error_code=error_code,
            now=_timestamp(now, "now"),
        )


__all__ = [
    "BROWSER_PEER_ADAPTER_SCHEMA",
    "BrowserPeerAdapter",
    "BrowserPeerAdapterContractError",
    "BrowserPeerAdapterDenied",
    "BrowserPeerPermit",
    "BrowserPeerPinReceipt",
    "BrowserPeerTransport",
    "ResearchExternalBlocked",
]
