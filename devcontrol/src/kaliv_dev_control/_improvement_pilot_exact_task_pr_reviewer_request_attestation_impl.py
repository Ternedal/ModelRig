"""ADR-DC-076 read-only exact post-reviewer-request attestation.

Consumes one live completed ADR-DC-075 reviewer-write transaction and performs two
credential-free exact pull-request observations. Both observations must prove
that the exact pinned individual reviewer remains requested, no team reviewer
exists, and all immutable PR identity/state remains unchanged. This boundary
performs no mutation and grants no review or merge authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_reviewer_write_transaction as transaction_boundary
from .improvement_pilot_exact_task_pr_reviewer_write_transaction import (
    PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY,
    PilotExactTaskPrReviewerWriteTransaction,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-attestation/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY = (
    "attested-one-dc-l16-exact-post-reviewer-request-state-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCOPE = (
    "credential-free-stable-post-reviewer-request-state-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class PilotExactTaskPrReviewerRequestAttestationError(ValueError):
    """Post-reviewer-request state is drifted, ambiguous, or lacks live provenance."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "reviewer-request attestation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerRequestAttestationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerRequestAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestAttestationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_transaction(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerWriteTransaction, Any, Any]:
    if type(value) is not PilotExactTaskPrReviewerWriteTransaction:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "exact live ADR-DC-075 reviewer-write transaction is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerWriteTransaction.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "ADR-DC-075 transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "ADR-DC-075 transaction identity mismatch"
        )

    required_true = (
        "host_transaction_start_committed",
        "reviewer_request_authorization_consumed",
        "reviewer_request_slot_consumed",
        "reviewer_requestability_revalidated",
        "fresh_pr_state_revalidated_before_reviewer_request",
        "no_prior_requested_reviewers_reverified",
        "reviewer_not_pr_author_reverified",
        "write_broker_freshly_verified",
        "credential_broker_invoked_without_secret_exposure",
        "exact_individual_reviewer_request_performed",
        "reviewer_request_performed",
        "post_reviewer_request_readback_verified",
        "exact_reviewer_set_verified",
        "team_reviewers_absent_verified",
    )
    forced_false = (
        "credential_material_in_artifact",
        "credential_material_in_process_arguments",
        "credential_material_in_environment",
        "nonce_reusable",
        "reviewer_mutation_authorized",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _LOGIN.fullmatch(value.reviewer_login) is None
    ):
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "attestation requires one live completed inert ADR-DC-075 transaction"
        )

    live = transaction_boundary._get_live_pr_reviewer_write_transaction_inputs(value)
    capability = None if live is None else live.get("reviewer_write_credential_capability")
    if (
        capability is None
        or getattr(capability, "capability_authenticated", None) is not True
        or capability.sha256 != value.reviewer_write_credential_capability_sha256
    ):
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "ADR-DC-075 lost live ADR-DC-074 capability provenance"
        )
    try:
        (
            checked_capability,
            _preflight,
            _precondition,
            _reservation,
            _target,
            requirements,
            _descriptor,
        ) = transaction_boundary._require_live_capability(capability)
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "post-request attestation lost live upstream reviewer provenance"
        ) from exc

    if (
        checked_capability is not capability
        or value.reviewer_request_nonce_sha256 != capability.reviewer_request_nonce_sha256
        or value.pull_request_number != capability.pull_request_number
        or value.predicted_commit_sha != capability.predicted_commit_sha
        or value.reviewer_login != capability.reviewer_login
        or value.reviewer_user_id != capability.reviewer_user_id
        or value.reviewer_user_node_id_sha256 != capability.reviewer_user_node_id_sha256
        or value.pull_request_author_login != capability.pull_request_author_login
        or value.pull_request_author_user_id != capability.pull_request_author_user_id
    ):
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "ADR-DC-075 exact PR/reviewer provenance mismatch"
        )
    return value, capability, requirements


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
        return transaction_boundary._validate_readback(
            evidence,
            expected_updated_at_utc=transaction.requested_updated_at_utc,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "exact post-reviewer-request observation failed"
        ) from exc


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerWriteTransaction],
    ],
] = {}


def _mark_authenticated(
    attestation: Any,
    transaction: PilotExactTaskPrReviewerWriteTransaction,
) -> None:
    key = id(attestation)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        attestation.sha256,
        weakref.ref(attestation, cleanup),
        weakref.ref(transaction),
    )


def _get_live_pr_reviewer_request_attestation_inputs(
    attestation: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(attestation))
    if entry is None:
        return None
    pid, digest, attestation_ref, transaction_ref = entry
    transaction = transaction_ref()
    if (
        pid != os.getpid()
        or attestation_ref() is not attestation
        or transaction is None
        or transaction.transaction_authenticated is not True
        or transaction.sha256 != attestation.reviewer_write_transaction_sha256
        or attestation.sha256 != digest
    ):
        return None
    return MappingProxyType({"reviewer_write_transaction": transaction})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestAttestation:
    reviewer_write_transaction_sha256: str
    transaction_start_sha256: str
    reviewer_write_credential_capability_sha256: str
    reviewer_request_preflight_sha256: str
    reviewer_requestability_precondition_sha256: str
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    requested_updated_at_utc: str
    source_post_request_response_body_sha256: str
    source_post_request_response_etag_sha256: str
    first_response_body_sha256: str
    first_response_etag_sha256: str
    second_response_body_sha256: str
    second_response_etag_sha256: str
    first_observed_at_utc: str
    second_observed_at_utc: str
    reviewer_request_performed_verified: bool = True
    exact_requested_reviewer_verified: bool = True
    team_reviewers_absent_verified: bool = True
    exact_pr_state_verified: bool = True
    stable_double_observation_verified: bool = True
    credential_free_reads: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    review_state_attestation_required: bool = True
    nonce_reusable: bool = False
    reviewer_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY
            or self.observation_scope != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPrReviewerRequestAttestationError(
                "reviewer-request attestation schema/authority/scope is unsupported"
            )
        for name in (
            "reviewer_write_transaction_sha256",
            "transaction_start_sha256",
            "reviewer_write_credential_capability_sha256",
            "reviewer_request_preflight_sha256",
            "reviewer_requestability_precondition_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "source_post_request_response_body_sha256",
            "source_post_request_response_etag_sha256",
            "first_response_body_sha256",
            "first_response_etag_sha256",
            "second_response_body_sha256",
            "second_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        requested = _utc(self.requested_updated_at_utc, name="requested_updated_at_utc")
        if first < requested or second < first:
            raise PilotExactTaskPrReviewerRequestAttestationError(
                "reviewer-request attestation timing is invalid"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or _LOGIN.fullmatch(self.pull_request_author_login) is None
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
            or self.first_response_body_sha256 != self.second_response_body_sha256
            or self.first_response_etag_sha256 != self.second_response_etag_sha256
        ):
            raise PilotExactTaskPrReviewerRequestAttestationError(
                "reviewer-request attestation exact-state binding is invalid"
            )
        required_true = (
            "reviewer_request_performed_verified",
            "exact_requested_reviewer_verified",
            "team_reviewers_absent_verified",
            "exact_pr_state_verified",
            "stable_double_observation_verified",
            "credential_free_reads",
            "redirects_forbidden",
            "response_bounded",
            "review_state_attestation_required",
        )
        forced_false = (
            "nonce_reusable",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "merge_readiness_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerRequestAttestationError(
                "reviewer-request attestation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerRequestAttestationError(
                "reviewer-request attestation cannot grant mutation authority"
            )

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_pr_reviewer_request_attestation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerRequestAttestation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerRequestAttestationError(
                "reviewer-request attestation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerRequestAttestationError(
                "reviewer-request attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


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
    if _utc(second_at, name="second_observed_at_utc") < _utc(
        first_at, name="first_observed_at_utc"
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
    _mark_authenticated(result, transaction)
    if result.attestation_authenticated is not True:
        raise PilotExactTaskPrReviewerRequestAttestationError(
            "reviewer-request attestation lost live ADR-DC-075 provenance"
        )
    return result


def attest_pilot_exact_task_pr_reviewer_request(
    reviewer_write_transaction: PilotExactTaskPrReviewerWriteTransaction,
) -> PilotExactTaskPrReviewerRequestAttestation:
    """Freshly attest exact post-request PR state twice; never mutate GitHub."""
    return _attest_verified_pilot_exact_task_pr_reviewer_request(
        reviewer_write_transaction=reviewer_write_transaction,
        reader=transaction_boundary._read_post_request_pr,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_SCOPE",
    "PilotExactTaskPrReviewerRequestAttestationError",
    "PilotExactTaskPrReviewerRequestAttestation",
    "attest_pilot_exact_task_pr_reviewer_request",
]
