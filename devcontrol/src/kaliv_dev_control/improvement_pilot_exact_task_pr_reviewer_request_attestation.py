"""Hardened public facade for ADR-DC-076 post-reviewer-request attestation."""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import _improvement_pilot_exact_task_pr_reviewer_request_attestation_impl as _implementation
from . import improvement_pilot_exact_task_pr_reviewer_write_transaction as transaction_boundary
from .improvement_pilot_exact_task_pr_reviewer_write_transaction import (
    PilotExactTaskPrReviewerWriteTransaction,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCOPE = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCOPE
)
PilotExactTaskPrReviewerRequestAttestationError = (
    _implementation.PilotExactTaskPrReviewerRequestAttestationError
)
PilotExactTaskPrReviewerRequestAttestation = (
    _implementation.PilotExactTaskPrReviewerRequestAttestation
)

_require_live_transaction = _implementation._require_live_transaction
_get_live_pr_reviewer_request_attestation_inputs = (
    _implementation._get_live_pr_reviewer_request_attestation_inputs
)


def _validate_observation(
    value: Any,
    *,
    transaction: PilotExactTaskPrReviewerWriteTransaction,
) -> Mapping[str, Any]:
    expected = {
        "response_body_sha256",
        "response_etag_sha256",
        "updated_at_utc",
        "requested_reviewer_count",
        "requested_team_count",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "post-request attestation evidence fields mismatch"
        )
    result = dict(value)
    _implementation._hex64(
        result.get("response_body_sha256"),
        name="response_body_sha256",
    )
    _implementation._hex64(
        result.get("response_etag_sha256"),
        name="response_etag_sha256",
    )
    if (
        result.get("updated_at_utc") != transaction.requested_updated_at_utc
        or result.get("requested_reviewer_count") != 1
        or result.get("requested_team_count") != 0
    ):
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "post-request attestation evidence does not match exact requested state"
        )
    _implementation._utc(
        result["updated_at_utc"],
        name="attested requested_updated_at_utc",
    )
    return MappingProxyType(result)


def _observe_once(
    *,
    transaction: PilotExactTaskPrReviewerWriteTransaction,
    capability: Any,
    requirements: Any,
    reader: Callable[..., Mapping[str, Any]],
) -> Mapping[str, Any]:
    try:
        evidence = reader(
            capability=capability,
            requirements=requirements,
            expected_updated_at_utc=transaction.requested_updated_at_utc,
        )
        return _validate_observation(evidence, transaction=transaction)
    except PilotExactTaskPrReviewerRequestAttestationError:
        raise
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "exact post-reviewer-request observation failed"
        ) from exc


def _attest_verified_pilot_exact_task_pr_reviewer_request(
    *,
    reviewer_write_transaction: PilotExactTaskPrReviewerWriteTransaction,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReviewerRequestAttestation:
    transaction, capability, requirements = _require_live_transaction(
        reviewer_write_transaction
    )
    first_at = now_provider()
    first = _observe_once(
        transaction=transaction,
        capability=capability,
        requirements=requirements,
        reader=reader,
    )
    second_at = now_provider()
    if _implementation._utc(
        second_at,
        name="second_observed_at_utc",
    ) < _implementation._utc(
        first_at,
        name="first_observed_at_utc",
    ):
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "clock moved backwards during post-request attestation"
        )
    second = _observe_once(
        transaction=transaction,
        capability=capability,
        requirements=requirements,
        reader=reader,
    )
    if dict(first) != dict(second):
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "post-reviewer-request state changed between observations"
        )

    result = PilotExactTaskPrReviewerRequestAttestation(
        reviewer_write_transaction_sha256=transaction.sha256,
        transaction_start_sha256=transaction.transaction_start_sha256,
        reviewer_write_credential_capability_sha256=transaction.reviewer_write_credential_capability_sha256,
        reviewer_request_preflight_sha256=transaction.reviewer_request_preflight_sha256,
        reviewer_requestability_precondition_sha256=transaction.reviewer_requestability_precondition_sha256,
        reviewer_request_reservation_sha256=transaction.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=transaction.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=transaction.reviewer_handoff_requirements_sha256,
        reviewer_request_nonce_sha256=transaction.reviewer_request_nonce_sha256,
        repository=transaction.repository,
        pull_request_number=transaction.pull_request_number,
        pull_request_api_url=transaction.pull_request_api_url,
        pull_request_html_url=transaction.pull_request_html_url,
        pull_request_node_id_sha256=transaction.pull_request_node_id_sha256,
        base_branch=transaction.base_branch,
        head_branch=transaction.head_branch,
        predicted_commit_sha=transaction.predicted_commit_sha,
        reviewer_login=transaction.reviewer_login,
        reviewer_user_id=transaction.reviewer_user_id,
        reviewer_user_node_id_sha256=transaction.reviewer_user_node_id_sha256,
        pull_request_author_login=transaction.pull_request_author_login,
        pull_request_author_user_id=transaction.pull_request_author_user_id,
        requested_updated_at_utc=transaction.requested_updated_at_utc,
        source_post_request_response_body_sha256=transaction.post_request_response_body_sha256,
        source_post_request_response_etag_sha256=transaction.post_request_response_etag_sha256,
        first_response_body_sha256=str(first["response_body_sha256"]),
        first_response_etag_sha256=str(first["response_etag_sha256"]),
        second_response_body_sha256=str(second["response_body_sha256"]),
        second_response_etag_sha256=str(second["response_etag_sha256"]),
        first_observed_at_utc=first_at,
        second_observed_at_utc=second_at,
    )
    _implementation._mark_authenticated(result, transaction)
    if result.attestation_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "reviewer-request attestation lost live ADR-DC-075 provenance"
        )
    return result


def attest_pilot_exact_task_pr_reviewer_request(
    reviewer_write_transaction: PilotExactTaskPrReviewerWriteTransaction,
) -> PilotExactTaskPrReviewerRequestAttestation:
    """Freshly attest exact post-request state twice; never mutate GitHub."""
    return _attest_verified_pilot_exact_task_pr_reviewer_request(
        reviewer_write_transaction=reviewer_write_transaction,
        reader=transaction_boundary._read_post_request_pr,
        now_provider=_implementation._now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCOPE",
    "PilotExactTaskPrReviewerRequestAttestationError",
    "PilotExactTaskPrReviewerRequestAttestation",
    "attest_pilot_exact_task_pr_reviewer_request",
]
