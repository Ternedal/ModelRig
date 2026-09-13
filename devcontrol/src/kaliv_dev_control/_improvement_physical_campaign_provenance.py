"""Reuse the hardened reservation provenance boundary for DC-L15 campaign admission.

Campaign admission has the same create-once authority shape as the parent
reservation: a final receipt and a permanent replay marker become live authority
only when they were published by the current authenticated transaction.  Keep one
implementation of that security property.  This adapter maps the campaign
module's hook names onto the reservation provenance installers, then maps the
wrapped hooks back.

The descriptor installer binds the exact original O_CREAT|O_EXCL publications to
live object identity/PID/digest.  The directory-history installer adds POSIX
ledger + ancestor rename history.  Install this adapter before the production
campaign facade is wrapped so production cannot cache the older path+bytes-only
transaction.
"""
from __future__ import annotations

import functools
from types import SimpleNamespace
from typing import Any

from ._improvement_physical_reservation_directory_provenance import (
    install_directory_history_provenance,
)
from ._improvement_physical_reservation_provenance import (
    install_descriptor_bound_provenance,
)


class PhysicalCampaignProvenanceError(ValueError):
    """Campaign provenance could not be installed safely."""


def install_physical_campaign_provenance(implementation: Any) -> None:
    """Install original-publication + directory-history provenance on admission."""

    if implementation is None:
        raise PhysicalCampaignProvenanceError(
            "campaign admission implementation is unavailable"
        )
    if getattr(implementation, "_physical_campaign_provenance_installed", False):
        return

    required = (
        "create_once_file",
        "_mark_admission_transaction_authenticated",
        "_is_admission_transaction_authenticated",
        "_issue_physical_campaign_admission_once",
    )
    if any(not hasattr(implementation, name) for name in required):
        raise PhysicalCampaignProvenanceError(
            "campaign admission implementation lacks provenance hooks"
        )

    original_issue = implementation._issue_physical_campaign_admission_once
    adapter = SimpleNamespace(
        create_once_file=implementation.create_once_file,
        _mark_transaction_authenticated=(
            implementation._mark_admission_transaction_authenticated
        ),
        _is_transaction_authenticated=(
            implementation._is_admission_transaction_authenticated
        ),
        _consume_physical_qualification_request_once=original_issue,
    )

    # Order matters: directory history wraps the already descriptor-bound
    # publication/registry and the already descriptor-scoped transaction.
    install_descriptor_bound_provenance(adapter)
    install_directory_history_provenance(adapter)

    # Both hardened parent installers intentionally use generic *args/**kwargs
    # transaction wrappers. Preserve the campaign seam's callable metadata after
    # composition so production-contract introspection still sees the explicit
    # verifier and authority inputs. This changes introspection only; execution
    # still traverses both hardened wrappers.
    functools.update_wrapper(
        adapter._consume_physical_qualification_request_once,
        original_issue,
    )

    implementation.create_once_file = adapter.create_once_file
    implementation._mark_admission_transaction_authenticated = (
        adapter._mark_transaction_authenticated
    )
    implementation._is_admission_transaction_authenticated = (
        adapter._is_transaction_authenticated
    )
    implementation._issue_physical_campaign_admission_once = (
        adapter._consume_physical_qualification_request_once
    )
    implementation._physical_campaign_provenance_installed = True


__all__: list[str] = []
