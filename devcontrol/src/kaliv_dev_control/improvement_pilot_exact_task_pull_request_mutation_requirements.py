"""ADR-DC-054 exact pull-request mutation requirements.

Consumes one live authenticated ADR-DC-053 remote-publication transaction and
freezes the requirements for a later, separately human-authorized draft pull
request creation. This boundary performs no GitHub API call and grants no
pull-request, merge, release, deploy, or production-activation authority.
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
from typing import Any, Mapping

from . import improvement_pilot_exact_task_remote_publication_credential_capability as capability_boundary
from . import improvement_pilot_exact_task_remote_publication_write_transaction as transaction_boundary
from .improvement_pilot_exact_task_remote_publication_write_transaction import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY,
    PilotExactTaskRemotePublicationWriteTransaction,
)

PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pull-request-mutation-requirements/v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_AUTHORITY = (
    "host-bound-one-dc-l16-exact-pull-request-mutation-requirements-only"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCOPE = (
    "exact-draft-pull-request-create-requirements-only-v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_BASE_REF = "main"
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_API_HOST = "api.github.com"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEAD_REF = re.compile(r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$")
_HEAD_BRANCH = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPullRequestMutationRequirementsError(ValueError):
    """The verified remote candidate cannot be bound to inert PR requirements."""


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
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "pull-request mutation requirements are not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPullRequestMutationRequirementsError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPullRequestMutationRequirementsError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_transaction(
    value: Any,
) -> tuple[
    PilotExactTaskRemotePublicationWriteTransaction,
    Any,
]:
    if type(value) is not PilotExactTaskRemotePublicationWriteTransaction:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "exact ADR-DC-053 remote-publication transaction is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationWriteTransaction.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "ADR-DC-053 transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "ADR-DC-053 transaction identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or value.remote_publication_authorization_consumed is not True
        or value.remote_write_slot_consumed is not True
        or value.create_only_compare_and_swap_performed is not True
        or value.remote_write_performed is not True
        or value.push_performed is not True
        or value.remote_ref_verified is not True
        or value.remote_publication_completed is not True
        or value.separate_pr_mutation_authorization_required is not True
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.canonical_remote_url != "https://github.com/Ternedal/ModelRig.git"
        or _HEAD_REF.fullmatch(value.destination_ref) is None
        or not value.destination_ref.endswith(value.remote_publication_nonce_sha256)
    ):
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "PR requirements require one completed inert ADR-DC-053 transaction"
        )

    inputs = transaction_boundary._get_live_remote_publication_write_transaction_inputs(
        value
    )
    if inputs is None:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "ADR-DC-053 live transaction provenance is unavailable"
        )
    capability = inputs.get("remote_publication_credential_capability")
    if (
        capability is None
        or getattr(capability, "sha256", None) != value.credential_capability_sha256
        or getattr(capability, "capability_authenticated", None) is not True
        or getattr(capability, "remote_write_reservation_sha256", None)
        != value.remote_write_reservation_sha256
        or getattr(capability, "target_attestation_sha256", None)
        != value.target_attestation_sha256
        or getattr(capability, "authorization_proof_sha256", None)
        != value.authorization_proof_sha256
        or getattr(capability, "local_commit_publication_requirements_sha256", None)
        != value.local_commit_publication_requirements_sha256
        or getattr(capability, "local_commit_write_transaction_sha256", None)
        != value.local_commit_write_transaction_sha256
        or getattr(capability, "remote_publication_nonce_sha256", None)
        != value.remote_publication_nonce_sha256
        or getattr(capability, "predicted_commit_sha", None)
        != value.predicted_commit_sha
        or getattr(capability, "destination_ref", None) != value.destination_ref
    ):
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "ADR-DC-053 transaction lost exact live credential provenance"
        )
    capability_inputs = (
        capability_boundary._get_live_remote_publication_credential_capability_inputs(
            capability
        )
    )
    reservation = (
        None
        if capability_inputs is None
        else capability_inputs.get("remote_publication_write_reservation")
    )
    if (
        reservation is None
        or getattr(reservation, "sha256", None)
        != value.remote_write_reservation_sha256
        or getattr(reservation, "reservation_authenticated", None) is not True
    ):
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "ADR-DC-053 live reservation provenance is unavailable"
        )
    return value, capability


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[PilotExactTaskRemotePublicationWriteTransaction],
        ],
    ] = {}

    def mark(
        requirements: Any,
        transaction: PilotExactTaskRemotePublicationWriteTransaction,
    ) -> None:
        key = id(requirements)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            requirements.sha256,
            weakref.ref(requirements, cleanup),
            weakref.ref(transaction),
        )

    def get(requirements: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(requirements))
        if entry is None:
            return None
        pid, digest, requirements_ref, transaction_ref = entry
        transaction = transaction_ref()
        if (
            pid != os.getpid()
            or requirements_ref() is not requirements
            or transaction is None
            or transaction.transaction_authenticated is not True
            or requirements.sha256 != digest
            or requirements.remote_publication_write_transaction_sha256
            != transaction.sha256
        ):
            return None
        return MappingProxyType(
            {"remote_publication_write_transaction": transaction}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_pull_request_mutation_requirements_authenticated,
    _get_live_pull_request_mutation_requirements_inputs,
) = _live_registry()


_REQUIRED_TRUE = (
    "remote_publication_transaction_authenticated",
    "remote_publication_completed",
    "remote_ref_verified",
    "pull_request_requirements_materialized",
    "draft_pull_request_required",
    "create_only_pull_request_required",
    "existing_open_pull_request_absent_required",
    "same_repository_head_required",
    "exact_base_ref_required",
    "exact_head_ref_required",
    "exact_head_sha_required",
    "separate_human_pr_mutation_authorization_required",
    "fresh_pull_request_state_observation_before_write_required",
    "one_shot_pr_mutation_reservation_required",
    "host_pinned_pr_credential_capability_required",
    "merge_separately_authorized_required",
)

_FORCED_FALSE = (
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "pull_request_create_authorized",
    "pull_request_update_authorized",
    "ready_for_review_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPullRequestMutationRequirements:
    remote_publication_write_transaction_sha256: str
    credential_capability_sha256: str
    remote_write_reservation_sha256: str
    target_attestation_sha256: str
    remote_publication_authorization_proof_sha256: str
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    repository: str
    api_host: str
    canonical_remote_url: str
    base_ref: str
    head_ref: str
    head_branch: str
    predicted_commit_sha: str
    remote_publication_verified_at_utc: str
    materialized_at_utc: str
    remote_publication_transaction_authenticated: bool = True
    remote_publication_completed: bool = True
    remote_ref_verified: bool = True
    pull_request_requirements_materialized: bool = True
    draft_pull_request_required: bool = True
    create_only_pull_request_required: bool = True
    existing_open_pull_request_absent_required: bool = True
    same_repository_head_required: bool = True
    exact_base_ref_required: bool = True
    exact_head_ref_required: bool = True
    exact_head_sha_required: bool = True
    separate_human_pr_mutation_authorization_required: bool = True
    fresh_pull_request_state_observation_before_write_required: bool = True
    one_shot_pr_mutation_reservation_required: bool = True
    host_pinned_pr_credential_capability_required: bool = True
    merge_separately_authorized_required: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_update_authorized: bool = False
    ready_for_review_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request requirements schema is unsupported"
            )
        if (
            self.requirements_scope
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCOPE
        ):
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request requirements scope is unsupported"
            )
        if (
            self.authority
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_AUTHORITY
        ):
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request requirements authority is unsupported"
            )
        for name in (
            "remote_publication_write_transaction_sha256",
            "credential_capability_sha256",
            "remote_write_reservation_sha256",
            "target_attestation_sha256",
            "remote_publication_authorization_proof_sha256",
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "remote_publication_nonce_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.repository != "Ternedal/ModelRig"
            or self.api_host
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_API_HOST
            or self.canonical_remote_url != "https://github.com/Ternedal/ModelRig.git"
            or self.base_ref
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_BASE_REF
            or _HEAD_REF.fullmatch(self.head_ref) is None
            or _HEAD_BRANCH.fullmatch(self.head_branch) is None
            or self.head_ref != f"refs/heads/{self.head_branch}"
            or not self.head_ref.endswith(self.remote_publication_nonce_sha256)
        ):
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request requirements target binding is invalid"
            )
        remote_verified = _utc(
            self.remote_publication_verified_at_utc,
            name="remote_publication_verified_at_utc",
        )
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if materialized < remote_verified:
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request requirements predate remote publication verification"
            )
        if any(getattr(self, name) is not True for name in _REQUIRED_TRUE):
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request mutation requirements are incomplete"
            )
        if any(getattr(self, name) is not False for name in _FORCED_FALSE):
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request requirements cannot grant mutation authority"
            )

    @property
    def requirements_authenticated(self) -> bool:
        return _get_live_pull_request_mutation_requirements_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPullRequestMutationRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request mutation requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request mutation requirements fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls, text: str
    ) -> "PilotExactTaskPullRequestMutationRequirements":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskPullRequestMutationRequirementsError(
                "pull-request mutation requirements JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_pull_request_mutation_requirements(
    *,
    remote_publication_write_transaction: PilotExactTaskRemotePublicationWriteTransaction,
    now_provider: Any,
) -> PilotExactTaskPullRequestMutationRequirements:
    transaction, capability = _require_live_transaction(
        remote_publication_write_transaction
    )
    materialized_at = now_provider()
    _utc(materialized_at, name="materialized_at_utc")
    head_branch = transaction.destination_ref.removeprefix("refs/heads/")
    result = PilotExactTaskPullRequestMutationRequirements(
        remote_publication_write_transaction_sha256=transaction.sha256,
        credential_capability_sha256=transaction.credential_capability_sha256,
        remote_write_reservation_sha256=transaction.remote_write_reservation_sha256,
        target_attestation_sha256=transaction.target_attestation_sha256,
        remote_publication_authorization_proof_sha256=(
            transaction.authorization_proof_sha256
        ),
        local_commit_publication_requirements_sha256=(
            transaction.local_commit_publication_requirements_sha256
        ),
        local_commit_write_transaction_sha256=(
            transaction.local_commit_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=transaction.remote_publication_nonce_sha256,
        repository="Ternedal/ModelRig",
        api_host=PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_API_HOST,
        canonical_remote_url=transaction.canonical_remote_url,
        base_ref=PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_BASE_REF,
        head_ref=transaction.destination_ref,
        head_branch=head_branch,
        predicted_commit_sha=transaction.predicted_commit_sha,
        remote_publication_verified_at_utc=transaction.verified_at_utc,
        materialized_at_utc=materialized_at,
    )
    if capability.sha256 != result.credential_capability_sha256:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "credential capability drifted while materializing PR requirements"
        )
    _mark_pull_request_mutation_requirements_authenticated(result, transaction)
    if result.requirements_authenticated is not True:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "pull-request requirements lost live ADR-DC-053 provenance"
        )
    return result


def materialize_pilot_exact_task_pull_request_mutation_requirements(
    remote_publication_write_transaction: PilotExactTaskRemotePublicationWriteTransaction,
) -> PilotExactTaskPullRequestMutationRequirements:
    """Freeze inert requirements for one later human-authorized draft PR create."""
    try:
        return _materialize_verified_pilot_exact_task_pull_request_mutation_requirements(
            remote_publication_write_transaction=remote_publication_write_transaction,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPullRequestMutationRequirementsError:
        raise
    except (ValueError, TypeError, AttributeError, UnicodeError) as exc:
        raise PilotExactTaskPullRequestMutationRequirementsError(
            "pull-request mutation requirements failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_SCOPE",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_BASE_REF",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_REQUIREMENTS_API_HOST",
    "PilotExactTaskPullRequestMutationRequirementsError",
    "PilotExactTaskPullRequestMutationRequirements",
    "materialize_pilot_exact_task_pull_request_mutation_requirements",
]
