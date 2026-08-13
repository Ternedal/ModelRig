"""Dormant pinned network transport for T-037 Google/Notion read connectors.

This is the first concrete provider network adapter behind
``ReadConnectorProviderTransport``. It deliberately remains unregistered and
cannot activate a connector by itself.

Security properties:

* provider host is re-derived from connector identity and cannot be caller-chosen;
* every DNS answer must be globally routable before any socket is opened;
* one deterministic numeric address is selected and passed to the pinned socket
  transport while TLS SNI/certificate verification keeps the original host;
* the connected peer must equal the selected DNS address;
* request method/query/headers/body come only from the immutable reviewed
  ``ProviderRequestPlan``;
* bearer material enters only the trusted pinned transport seam and is never
  stored in returned evidence or exceptions;
* redirects are never followed; one execute call performs one HTTP exchange;
* response bytes remain bounded by the request plan and are returned to the
  already-qualified provider response validator via ``ProviderTransportResponse``.

No OAuth, credential storage, runtime/API registration or production
activation is implemented here. ``PRODUCTION_ACTIVATION`` remains false.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Sequence

from .pinned_http_transport import PinnedHttpTransport
from .read_connector_provider_execution import (
    ProviderExecutionError,
    ProviderTransportResponse,
    exact_request_sha256,
)
from .read_connector_provider_request import ProviderRequestPlan
from .web_fetch import TransportResponse, WebFetchError, default_resolver

PRODUCTION_ACTIVATION = False
_PROVIDER_PORT = 443
_EXPECTED_HOST = {
    "google_calendar": "www.googleapis.com",
    "google_drive": "www.googleapis.com",
    "gmail": "gmail.googleapis.com",
    "notion": "api.notion.com",
}
_MAX_TIMEOUT_SECONDS = 120.0


class ProviderNetworkTransportError(ProviderExecutionError):
    """Provider networking failed without exposing secret/provider body data."""


class ReadConnectorPinnedProviderTransport:
    """Concrete one-shot DNS + pinned-socket adapter for reviewed provider plans."""

    def __init__(self, *, resolver=default_resolver, transport: PinnedHttpTransport | None = None) -> None:
        self._resolver = resolver
        self._transport = transport or PinnedHttpTransport()

    def execute(
        self,
        plan: ProviderRequestPlan,
        *,
        bearer_token: str,
        request_sha256: str,
        timeout_seconds: float,
    ) -> ProviderTransportResponse:
        if not isinstance(plan, ProviderRequestPlan):
            raise ProviderNetworkTransportError("provider network transport requires ProviderRequestPlan")
        if plan.production_activation is not False:
            raise ProviderNetworkTransportError("provider network transport must remain dormant")
        expected_host = _EXPECTED_HOST.get(plan.connector)
        if expected_host is None or plan.host != expected_host:
            raise ProviderNetworkTransportError("provider host does not match connector identity")
        if plan.follow_redirects is not False:
            raise ProviderNetworkTransportError("provider network transport cannot follow redirects")
        expected_digest = exact_request_sha256(plan)
        if request_sha256 != expected_digest:
            raise ProviderNetworkTransportError("provider request digest does not match immutable plan")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ProviderNetworkTransportError("provider network timeout must be numeric")
        timeout = float(timeout_seconds)
        if not 0 < timeout <= _MAX_TIMEOUT_SECONDS:
            raise ProviderNetworkTransportError("provider network timeout must be within 0..120 seconds")

        addresses = self._resolve_public_addresses(plan.host)
        selected = addresses[0]
        headers = dict(plan.headers)
        body = None if plan.body_json is None else plan.body_json.encode("utf-8")

        try:
            response = self._transport.request_with_trusted_bearer_request(
                plan.url,
                method=plan.method,
                body=body,
                connect_address=selected,
                headers=headers,
                bearer_token=bearer_token,
                timeout_seconds=timeout,
                max_wire_bytes=plan.max_response_bytes,
            )
        except WebFetchError:
            raise ProviderNetworkTransportError("provider pinned transport failed") from None
        except Exception:
            raise ProviderNetworkTransportError("provider pinned transport failed") from None

        if not isinstance(response, TransportResponse):
            raise ProviderNetworkTransportError("provider pinned transport returned invalid response")
        try:
            connected = ipaddress.ip_address(response.connected_address).compressed
        except ValueError:
            raise ProviderNetworkTransportError("provider transport returned invalid peer evidence") from None
        if connected != selected:
            raise ProviderNetworkTransportError("provider transport peer did not match pinned DNS address")
        encoding = response.headers.get("content-encoding", "").strip().casefold()
        if encoding not in {"", "identity"}:
            raise ProviderNetworkTransportError("provider response content encoding is unsupported")
        content_type = response.headers.get("content-type", "")

        return ProviderTransportResponse(
            request_sha256=request_sha256,
            method=plan.method,
            host=plan.host,
            status_code=response.status,
            content_type=content_type,
            body=response.body,
        )

    def _resolve_public_addresses(self, host: str) -> tuple[str, ...]:
        try:
            raw: Sequence[str] = self._resolver(host, _PROVIDER_PORT)
        except WebFetchError:
            raise ProviderNetworkTransportError("provider DNS resolution failed") from None
        except Exception:
            raise ProviderNetworkTransportError("provider DNS resolution failed") from None
        if not raw:
            raise ProviderNetworkTransportError("provider DNS resolution returned no addresses")

        values: list[str] = []
        for item in raw:
            try:
                parsed = ipaddress.ip_address(item)
            except ValueError:
                raise ProviderNetworkTransportError("provider DNS returned an invalid address") from None
            if not parsed.is_global:
                raise ProviderNetworkTransportError("provider DNS returned a non-public address")
            normalized = parsed.compressed
            if normalized not in values:
                values.append(normalized)
        values.sort(
            key=lambda value: (
                ipaddress.ip_address(value).version,
                ipaddress.ip_address(value).packed,
            )
        )
        return tuple(values)
