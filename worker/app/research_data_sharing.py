"""Dormant adapter from legacy research egress plans to data-sharing v1.

The adapter performs no network I/O and is not imported by the active research
path. It makes the migration boundary explicit and testable before activation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .data_sharing import DEFAULT_POLICY, DataSharingPolicy, DataSharingRequest, Decision
from .research_egress import EgressPlan

ADAPTER_SCHEMA = "kaliv-research-data-sharing-adapter/v1"


def _scope_digest(domains: tuple[str, ...]) -> str:
    raw = json.dumps(list(domains), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def legacy_research_decision(plan: EgressPlan) -> Decision:
    """Describe the old ledger rule without authorizing anything."""
    if plan.sensitivity == "secret":
        return "forbidden"
    if plan.sensitivity == "private":
        return "confirmation_required"
    return "automatic"


@dataclass(frozen=True)
class ResearchSharingIntent:
    """Exact migration input for one legacy research egress plan."""

    plan: EgressPlan
    summary: str
    provider: str = "browser-use"
    purpose_code: str = "web_research"
    schema: str = ADAPTER_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ADAPTER_SCHEMA:
            raise ValueError("unsupported research data-sharing adapter schema")
        # DataSharingRequest owns strict validation and normalization of the
        # provider, summary and purpose code. Build once here so invalid intents
        # fail at construction rather than later at the network boundary.
        self.to_request()

    @property
    def domain_scope_sha256(self) -> str:
        return _scope_digest(self.plan.allowed_domains)

    @property
    def scoped_destination(self) -> str:
        # The domain scope is security-relevant. Binding its full digest into the
        # stable destination prevents a permission from being replayed with a
        # wider or simply different allowlist.
        return f"{self.plan.destination}:domains:{self.domain_scope_sha256}"

    def to_request(self) -> DataSharingRequest:
        return DataSharingRequest(
            surface="research",
            destination_type="public_web",
            provider=self.provider,
            destination=self.scoped_destination,
            data_category=self.plan.sensitivity,
            purpose_code=self.purpose_code,
            purpose=self.plan.purpose,
            summary=self.summary,
            content_sha256=self.plan.payload_sha256,
            max_bytes=self.plan.max_bytes,
        )

    def preview(self, policy: DataSharingPolicy = DEFAULT_POLICY) -> dict:
        request = self.to_request()
        return {
            "schema": self.schema,
            "legacy_plan_digest": self.plan.digest,
            "legacy_decision": legacy_research_decision(self.plan),
            "common_decision": policy.decision(request),
            "allowed_domains": list(self.plan.allowed_domains),
            "domain_scope_sha256": self.domain_scope_sha256,
            "request": request.preview(policy),
        }
