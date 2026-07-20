"""Dormant bridge from verified common claim evidence to one URL-scoped peer authorization.

This module performs no DNS, socket, CDP, browser or provider I/O. It proves only
that an exact, currently in-flight common receipt authorizes one canonical URL
inside the research plan's existing domain scope. DNS and connected-peer proof
remain a later, separate state machine.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .data_sharing import DataSharingContractError, DataSharingDenied
from .research_claim_evidence import (
    DataSharingClaimEvidence,
    VerifiableResearchSharingBoundary,
)
from .research_contract import ResearchContractError, canonicalize_url, host_allowed
from .research_data_sharing import ResearchSharingIntent
from .research_sharing_boundary import ResearchSharingLease

PEER_AUTHORIZATION_SCHEMA = "kaliv-research-peer-authorization/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


class ResearchPeerAuthorizationContractError(ValueError):
    """The caller supplied a malformed bridge input or authorization object."""


class ResearchPeerAuthorizationDenied(PermissionError):
    """The active claim or exact URL scope did not authorize peer preparation."""


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResearchPeerAuthorizationContractError(
            f"{name} must be a non-negative integer timestamp"
        )
    return value


def _target(intent: ResearchSharingIntent, raw_url: str) -> tuple[str, str, int]:
    if not isinstance(intent, ResearchSharingIntent):
        raise ResearchPeerAuthorizationContractError(
            "intent must be a ResearchSharingIntent"
        )
    if not isinstance(raw_url, str):
        raise ResearchPeerAuthorizationContractError("url must be a string")
    try:
        canonical = canonicalize_url(raw_url)
        if not host_allowed(canonical, intent.plan.allowed_domains):
            raise ResearchPeerAuthorizationDenied(
                "URL is outside the authorized research domain scope"
            )
        parsed = urlsplit(canonical)
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ResearchPeerAuthorizationDenied:
        raise
    except ResearchContractError as exc:
        raise ResearchPeerAuthorizationDenied(
            "URL is outside the public research contract"
        ) from exc
    except ValueError as exc:
        raise ResearchPeerAuthorizationContractError("URL has an invalid port") from exc
    if not host or not _HOST.fullmatch(host):
        raise ResearchPeerAuthorizationContractError("canonical URL host is invalid")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ResearchPeerAuthorizationContractError("canonical URL port is invalid")
    return canonical, host, port


@dataclass(frozen=True)
class ResearchPeerAuthorization:
    """Deterministic bridge object for one in-flight claim and canonical URL."""

    claim_receipt_id: str
    request_digest: str
    legacy_plan_digest: str
    domain_scope_sha256: str
    url_sha256: str
    host: str
    port: int
    max_bytes: int
    claimed_at: int
    expires_at: int
    schema: str = PEER_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PEER_AUTHORIZATION_SCHEMA:
            raise ResearchPeerAuthorizationContractError(
                "unsupported peer authorization schema"
            )
        if not isinstance(self.claim_receipt_id, str) or not self.claim_receipt_id.startswith(
            "dsr_"
        ):
            raise ResearchPeerAuthorizationContractError("claim_receipt_id is invalid")
        for name, value in (
            ("request_digest", self.request_digest),
            ("legacy_plan_digest", self.legacy_plan_digest),
            ("domain_scope_sha256", self.domain_scope_sha256),
            ("url_sha256", self.url_sha256),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ResearchPeerAuthorizationContractError(
                    f"{name} must be a lowercase SHA-256 digest"
                )
        if not isinstance(self.host, str) or not _HOST.fullmatch(self.host):
            raise ResearchPeerAuthorizationContractError("host is invalid")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ResearchPeerAuthorizationContractError("port is invalid")
        if (
            isinstance(self.max_bytes, bool)
            or not isinstance(self.max_bytes, int)
            or not 1 <= self.max_bytes <= 10_000_000
        ):
            raise ResearchPeerAuthorizationContractError("max_bytes is invalid")
        _timestamp(self.claimed_at, "claimed_at")
        _timestamp(self.expires_at, "expires_at")
        if self.expires_at <= self.claimed_at:
            raise ResearchPeerAuthorizationContractError(
                "authorization expiry must follow claim time"
            )

    def digest_payload(self) -> dict:
        return {
            "schema": self.schema,
            "claim_receipt_id": self.claim_receipt_id,
            "request_digest": self.request_digest,
            "legacy_plan_digest": self.legacy_plan_digest,
            "domain_scope_sha256": self.domain_scope_sha256,
            "url_sha256": self.url_sha256,
            "host": self.host,
            "port": self.port,
            "max_bytes": self.max_bytes,
            "claimed_at": self.claimed_at,
            "expires_at": self.expires_at,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.digest_payload())).hexdigest()

    @property
    def authorization_id(self) -> str:
        return f"rpa_{self.digest}"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "authorization_id": self.authorization_id,
            "claim_receipt_id": self.claim_receipt_id,
            "request_digest": self.request_digest,
            "legacy_plan_digest": self.legacy_plan_digest,
            "domain_scope_sha256": self.domain_scope_sha256,
            "url_sha256": self.url_sha256,
            "host": self.host,
            "port": self.port,
            "max_bytes": self.max_bytes,
            "claimed_at": _iso(self.claimed_at),
            "expires_at": _iso(self.expires_at),
        }


class ResearchPeerAuthorizationBridge:
    """Verify an active common claim and derive one exact URL authorization."""

    def __init__(self, boundary: VerifiableResearchSharingBoundary) -> None:
        if not isinstance(boundary, VerifiableResearchSharingBoundary):
            raise ResearchPeerAuthorizationContractError(
                "bridge requires VerifiableResearchSharingBoundary"
            )
        self._boundary = boundary

    def _expected(
        self,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        now: int | None,
    ) -> ResearchPeerAuthorization:
        if not isinstance(evidence, DataSharingClaimEvidence):
            raise ResearchPeerAuthorizationContractError(
                "evidence must be DataSharingClaimEvidence"
            )
        if not isinstance(lease, ResearchSharingLease):
            raise ResearchPeerAuthorizationContractError(
                "lease must be a ResearchSharingLease"
            )
        try:
            self._boundary.verify_claim(evidence, lease, intent, now=now)
        except DataSharingDenied as exc:
            raise ResearchPeerAuthorizationDenied(
                "claim evidence is not currently authorized for peer preparation"
            ) from exc
        canonical, host, port = _target(intent, url)
        request = intent.to_request()
        return ResearchPeerAuthorization(
            claim_receipt_id=evidence.receipt_id,
            request_digest=request.digest,
            legacy_plan_digest=intent.plan.digest,
            domain_scope_sha256=intent.domain_scope_sha256,
            url_sha256=_digest(canonical),
            host=host,
            port=port,
            max_bytes=evidence.max_bytes,
            claimed_at=evidence.claimed_at,
            expires_at=evidence.expires_at,
        )

    def prepare(
        self,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        now: int | None = None,
    ) -> ResearchPeerAuthorization:
        return self._expected(evidence, lease, intent, url, now=now)

    def verify(
        self,
        authorization: ResearchPeerAuthorization,
        evidence: DataSharingClaimEvidence,
        lease: ResearchSharingLease,
        intent: ResearchSharingIntent,
        url: str,
        *,
        now: int | None = None,
    ) -> None:
        if not isinstance(authorization, ResearchPeerAuthorization):
            raise ResearchPeerAuthorizationContractError(
                "authorization must be ResearchPeerAuthorization"
            )
        expected = self._expected(evidence, lease, intent, url, now=now)
        if authorization != expected:
            raise ResearchPeerAuthorizationDenied(
                "peer authorization does not match the active claim and exact URL"
            )
