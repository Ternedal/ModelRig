"""Public ADR-DC-010 campaign-admission facade.

Importing the top-level ``kaliv_dev_control`` package must remain side-effect free
with respect to the optional RSI/DC-L15 authority chain.  The hardened campaign
provenance and production wrappers are therefore installed only when this
specific facade is imported.

The underlying implementation remains available only through the underscored
module for deterministic adversarial tests.  Production callers receive the
self-installed public facade below.
"""
from __future__ import annotations

from . import _improvement_physical_campaign_admission_impl as _implementation
from ._improvement_physical_campaign_production_boundary import (
    install_physical_campaign_production_boundary,
)
from ._improvement_physical_campaign_provenance import (
    install_physical_campaign_provenance,
)

# Order is security-significant: provenance must wrap the private transaction
# before the production facade caches it.
install_physical_campaign_provenance(_implementation)
install_physical_campaign_production_boundary(_implementation)

RUNNER_AUTHORIZATION_SCHEMA = _implementation.RUNNER_AUTHORIZATION_SCHEMA
RUNNER_AUTHORIZATION_AUTHORITY = _implementation.RUNNER_AUTHORIZATION_AUTHORITY
RUNNER_AUTHORIZATION_SCOPE = _implementation.RUNNER_AUTHORIZATION_SCOPE
RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID = (
    _implementation.RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID
)
CAMPAIGN_ADMISSION_SCHEMA = _implementation.CAMPAIGN_ADMISSION_SCHEMA
CAMPAIGN_ADMISSION_AUTHORITY = _implementation.CAMPAIGN_ADMISSION_AUTHORITY
CAMPAIGN_LEDGER_SCOPE = _implementation.CAMPAIGN_LEDGER_SCOPE
HOST_SCOPE_SCHEMA = _implementation.HOST_SCOPE_SCHEMA

PhysicalCampaignAdmissionError = _implementation.PhysicalCampaignAdmissionError
PhysicalCampaignRunnerAuthorization = _implementation.PhysicalCampaignRunnerAuthorization
PhysicalCampaignAdmission = _implementation.PhysicalCampaignAdmission
reservation_host_scope_sha256 = _implementation.reservation_host_scope_sha256
build_physical_campaign_runner_authorization = (
    _implementation.build_physical_campaign_runner_authorization
)
issue_physical_campaign_admission_once = (
    _implementation.issue_physical_campaign_admission_once
)


def __getattr__(name: str):
    """Delegate private deterministic test seams without widening public exports."""

    return getattr(_implementation, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_implementation)))


__all__ = [
    "RUNNER_AUTHORIZATION_SCHEMA",
    "RUNNER_AUTHORIZATION_AUTHORITY",
    "RUNNER_AUTHORIZATION_SCOPE",
    "RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID",
    "CAMPAIGN_ADMISSION_SCHEMA",
    "CAMPAIGN_ADMISSION_AUTHORITY",
    "CAMPAIGN_LEDGER_SCOPE",
    "HOST_SCOPE_SCHEMA",
    "PhysicalCampaignAdmissionError",
    "PhysicalCampaignRunnerAuthorization",
    "PhysicalCampaignAdmission",
    "reservation_host_scope_sha256",
    "build_physical_campaign_runner_authorization",
    "issue_physical_campaign_admission_once",
]

del install_physical_campaign_provenance
del install_physical_campaign_production_boundary
