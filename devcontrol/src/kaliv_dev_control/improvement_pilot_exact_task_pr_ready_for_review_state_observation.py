"""ADR-DC-062 fresh read-only PR state observation before ready-for-review.

Consumes one exact live ADR-DC-061 ready-for-review reservation, performs a fresh
credential-free read of the exact pull request through the already hardened
ADR-DC-059 reader, and proves the signed draft state has not changed. No GitHub
mutation authority is granted here.
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

from . import improvement_pilot_exact_task_pr_ready_for_review_reservation as reservation_boundary
from .improvement_pilot_exact_task_pr_ready_for_review_reservation import (
    PILOT_EXACT_TASK_PR_READY_RESERVATION_AUTHORITY,
    PilotExactTaskPrReadyReservationReceipt,
)
from . import improvement_pilot_exact_task_pr_review_handoff_requirements as requirements_boundary

PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-state-observation/v1"
)
PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_AUTHORITY = (
    "observed-one-dc-l16-exact-pr-ready-for-review-state-only"
)
PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_MAX_RESERVATION_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")


class PilotExactTaskPrReadyStateObservationError(ValueError):
    """The reserved PR state is stale, drifted, unauthenticated, or unsafe."""


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
        raise PilotExactTaskPrReadyStateObservationError(
            "ready-state observation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReadyStateObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReadyStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReadyStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReadyStateObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_reservation(
    value: Any,
) -> tuple[PilotExactTaskPrReadyReservationReceipt, Any, Any, Any]:
    if type(value) is not PilotExactTaskPrReadyReservationReceipt:
        raise PilotExactTaskPrReadyStateObservationError(
            "exact ADR-DC-061 ready reservation is required"
        )
    try:
        replayed = PilotExactTaskPrReadyReservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyStateObservationError(
            "ADR-DC-061 reservation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReadyStateObservationError(
            "ADR-DC-061 reservation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_READY_RESERVATION_AUTHORITY
        or value.reservation_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.human_ready_for_review_authorization_freshly_verified is not True
        or value.ready_for_review_authorization_consumed is not True
        or value.ready_for_review_slot_reserved is not True
        or value.fresh_pr_state_revalidation_before_ready_required is not True
        or value.reviewer_mutation_separate_authority_required is not True
        or value.label_mutation_separate_authority_required is not True
        or value.merge_separate_authority_required is not True
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.ready_for_review_authorized is not False
        or value.ready_for_review_performed is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
    ):
        raise PilotExactTaskPrReadyStateObservationError(
            "ready-state observation requires one live inert ADR-DC-061 reservation"
        )

    inputs = reservation_boundary._get_live_pr_ready_reservation_inputs(value)
    requirements = None if inputs is None else inputs.get(
        "review_handoff_requirements"
    )
    if (
        requirements is None
        or getattr(requirements, "requirements_authenticated", None) is not True
        or requirements.sha256 != value.review_handoff_requirements_sha256
        or requirements.pr_create_transaction_sha256
        != value.pr_create_transaction_sha256
        or requirements.predicted_commit_sha != value.predicted_commit_sha
        or requirements.review_handoff_plan_sha256
        != value.review_handoff_plan_sha256
        or requirements.pr_mutation_nonce_sha256
        != value.pr_mutation_nonce_sha256
        or requirements.repository != value.repository
        or requirements.pull_request_number != value.pull_request_number
        or requirements.pull_request_api_url != value.pull_request_api_url
        or requirements.pull_request_html_url != value.pull_request_html_url
        or requirements.base_branch != value.base_branch
        or requirements.head_branch != value.head_branch
    ):
        raise PilotExactTaskPrReadyStateObservationError(
            "ADR-DC-061 lost exact live ADR-DC-059 handoff provenance"
        )
    handoff_inputs = (
        requirements_boundary._get_live_pr_review_handoff_requirements_inputs(
            requirements
        )
    )
    transaction = None if handoff_inputs is None else handoff_inputs.get(
        "pr_create_transaction"
    )
    if transaction is None:
        raise PilotExactTaskPrReadyStateObservationError(
            "ADR-DC-059 live PR-create transaction is unavailable"
        )
    try:
        exact_transaction, _capability, pr_requirements = (
            requirements_boundary._require_live_transaction(transaction)
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyStateObservationError(
            "ADR-DC-058 live PR-create provenance is unavailable"
        ) from exc
    if (
        exact_transaction.sha256 != value.pr_create_transaction_sha256
        or exact_transaction.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskPrReadyStateObservationError(
            "ready reservation is not bound to exact PR-create transaction"
        )
    return value, requirements, exact_transaction, pr_requirements


def _require_observation_window(
    reservation: PilotExactTaskPrReadyReservationReceipt,
    *,
    observed_at_utc: str,
) -> None:
    observed = _utc(observed_at_utc, name="observed_at_utc")
    reserved = _utc(reservation.reserved_at_utc, name="reserved_at_utc")
    if observed < reserved:
        raise PilotExactTaskPrReadyStateObservationError(
            "fresh PR observation predates ready reservation"
        )
    if (
        observed - reserved
    ).total_seconds() > PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_MAX_RESERVATION_AGE_SECONDS:
        raise PilotExactTaskPrReadyStateObservationError(
            "ready reservation is too old for fresh PR observation"
        )


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReadyReservationReceipt],
        weakref.ReferenceType[Any],
    ],
] = {}


def _mark_pr_ready_state_observation_authenticated(
    observation: Any,
    reservation: PilotExactTaskPrReadyReservationReceipt,
    requirements: Any,
) -> None:
    key = id(observation)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        observation.sha256,
        weakref.ref(observation, cleanup),
        weakref.ref(reservation),
        weakref.ref(requirements),
    )


def _get_live_pr_ready_state_observation_inputs(
    observation: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(observation))
    if entry is None:
        return None
    pid, digest, observation_ref, reservation_ref, requirements_ref = entry
    reservation = reservation_ref()
    requirements = requirements_ref()
    if (
        pid != os.getpid()
        or observation_ref() is not observation
        or reservation is None
        or requirements is None
        or reservation.reservation_authenticated is not True
        or requirements.requirements_authenticated is not True
        or reservation.sha256 != observation.ready_for_review_reservation_sha256
        or requirements.sha256 != observation.review_handoff_requirements_sha256
        or observation.sha256 != digest
    ):
        return None
    return MappingProxyType(
        {
            "ready_for_review_reservation": reservation,
            "review_handoff_requirements": requirements,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReadyStateObservation:
    ready_for_review_reservation_sha256: str
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    review_handoff_plan_sha256: str
    ready_for_review_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    base_branch: str
    head_branch: str
    request_url_sha256: str
    response_body_sha256: str
    response_etag_sha256: str
    signed_observed_updated_at_utc: str
    fresh_observed_updated_at_utc: str
    observed_at_utc: str
    ready_for_review_authorization_consumed: bool = True
    ready_for_review_slot_reserved: bool = True
    credential_free_read_verified: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    pull_request_open_verified: bool = True
    draft_state_verified: bool = True
    exact_head_sha_verified: bool = True
    exact_base_verified: bool = True
    exact_metadata_verified: bool = True
    signed_updated_at_still_current: bool = True
    ready_for_review_transaction_required: bool = True
    reviewer_mutation_separate_authority_required: bool = True
    label_mutation_separate_authority_required: bool = True
    merge_separate_authority_required: bool = True
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    ready_for_review_authorized: bool = False
    ready_for_review_performed: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_AUTHORITY
        ):
            raise PilotExactTaskPrReadyStateObservationError(
                "ready-state observation schema/authority is unsupported"
            )
        for name in (
            "ready_for_review_reservation_sha256",
            "review_handoff_requirements_sha256",
            "pr_create_transaction_sha256",
            "review_handoff_plan_sha256",
            "ready_for_review_nonce_sha256",
            "request_url_sha256",
            "response_body_sha256",
            "response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        signed = _utc(
            self.signed_observed_updated_at_utc,
            name="signed_observed_updated_at_utc",
        )
        fresh = _utc(
            self.fresh_observed_updated_at_utc,
            name="fresh_observed_updated_at_utc",
        )
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if signed != fresh or observed < fresh:
            raise PilotExactTaskPrReadyStateObservationError(
                "fresh PR state no longer matches signed updated_at"
            )
        if (
            self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or self.request_url_sha256
            != hashlib.sha256(self.pull_request_api_url.encode("utf-8")).hexdigest()
        ):
            raise PilotExactTaskPrReadyStateObservationError(
                "ready-state observation target binding is invalid"
            )
        required_true = (
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_reserved",
            "credential_free_read_verified",
            "redirects_forbidden",
            "response_bounded",
            "pull_request_open_verified",
            "draft_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
            "signed_updated_at_still_current",
            "ready_for_review_transaction_required",
            "reviewer_mutation_separate_authority_required",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        )
        forced_false = (
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorized",
            "ready_for_review_performed",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReadyStateObservationError(
                "ready-state observation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReadyStateObservationError(
                "ready-state observation cannot grant GitHub mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_ready_state_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReadyStateObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReadyStateObservationError(
                "ready-state observation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReadyStateObservationError(
                "ready-state observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_ready_for_review_state(
    *,
    ready_for_review_reservation: PilotExactTaskPrReadyReservationReceipt,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> PilotExactTaskPrReadyStateObservation:
    reservation, requirements, transaction, pr_requirements = (
        _require_live_reservation(ready_for_review_reservation)
    )
    observed_at = now_provider()
    _require_observation_window(reservation, observed_at_utc=observed_at)
    try:
        evidence = requirements_boundary._validate_reader_evidence(
            reader(
                pr_create_transaction=transaction,
                pr_mutation_requirements=pr_requirements,
            ),
            transaction=transaction,
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyStateObservationError(
            "fresh exact draft PR read failed"
        ) from exc
    if (
        evidence["request_url_sha256"]
        != hashlib.sha256(reservation.pull_request_api_url.encode("utf-8")).hexdigest()
        or evidence["observed_updated_at_utc"]
        != requirements.observed_updated_at_utc
    ):
        raise PilotExactTaskPrReadyStateObservationError(
            "fresh PR state differs from the human-signed handoff state"
        )
    result = PilotExactTaskPrReadyStateObservation(
        ready_for_review_reservation_sha256=reservation.sha256,
        review_handoff_requirements_sha256=requirements.sha256,
        pr_create_transaction_sha256=transaction.sha256,
        predicted_commit_sha=reservation.predicted_commit_sha,
        review_handoff_plan_sha256=reservation.review_handoff_plan_sha256,
        ready_for_review_nonce_sha256=reservation.ready_for_review_nonce_sha256,
        repository=reservation.repository,
        pull_request_number=reservation.pull_request_number,
        pull_request_api_url=reservation.pull_request_api_url,
        pull_request_html_url=reservation.pull_request_html_url,
        base_branch=reservation.base_branch,
        head_branch=reservation.head_branch,
        request_url_sha256=evidence["request_url_sha256"],
        response_body_sha256=evidence["response_body_sha256"],
        response_etag_sha256=evidence["response_etag_sha256"],
        signed_observed_updated_at_utc=requirements.observed_updated_at_utc,
        fresh_observed_updated_at_utc=evidence["observed_updated_at_utc"],
        observed_at_utc=observed_at,
    )
    _mark_pr_ready_state_observation_authenticated(
        result,
        reservation,
        requirements,
    )
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrReadyStateObservationError(
            "fresh ready-state observation lost live provenance"
        )
    return result


def observe_pilot_exact_task_pr_ready_for_review_state(
    ready_for_review_reservation: PilotExactTaskPrReadyReservationReceipt,
) -> PilotExactTaskPrReadyStateObservation:
    """Freshly verify the exact draft remains unchanged; perform no mutation."""
    return _observe_verified_pilot_exact_task_pr_ready_for_review_state(
        ready_for_review_reservation=ready_for_review_reservation,
        reader=requirements_boundary._read_exact_draft_pr_state,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_READY_STATE_OBSERVATION_MAX_RESERVATION_AGE_SECONDS",
    "PilotExactTaskPrReadyStateObservationError",
    "PilotExactTaskPrReadyStateObservation",
    "observe_pilot_exact_task_pr_ready_for_review_state",
]
