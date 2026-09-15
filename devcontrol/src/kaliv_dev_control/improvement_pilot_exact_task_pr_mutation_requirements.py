"""ADR-DC-054 deterministic requirements for one exact draft PR creation.

The boundary accepts only one live authenticated ADR-DC-053 remote publication
transaction. It derives a fixed draft pull-request plan for Ternedal/ModelRig
without calling GitHub and without granting PR, merge, release, deploy or
production-activation authority.
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
from . import improvement_pilot_exact_task_remote_publication_state_observation as state_boundary
from . import improvement_pilot_exact_task_remote_publication_target_attestation as target_boundary
from . import improvement_pilot_exact_task_remote_publication_write_reservation as reservation_boundary
from . import improvement_pilot_exact_task_remote_publication_write_transaction as transaction_boundary
from .improvement_pilot_exact_task_remote_publication_write_transaction import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY,
    PilotExactTaskRemotePublicationWriteTransaction,
)

PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-mutation-requirements/v1"
)
PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_AUTHORITY = (
    "dc-l16-exact-draft-pr-mutation-requirements-only"
)
PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCOPE = "one-draft-pr-create-only-v1"
PILOT_EXACT_TASK_PR_MUTATION_BASE_BRANCH = "main"
PILOT_EXACT_TASK_PR_MUTATION_REPOSITORY = "Ternedal/ModelRig"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_REF = re.compile(r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPrMutationRequirementsError(ValueError):
    """The exact draft-PR requirements are malformed, unauthenticated or unsafe."""


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
        raise PilotExactTaskPrMutationRequirementsError(
            "PR mutation requirements are not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrMutationRequirementsError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrMutationRequirementsError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrMutationRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrMutationRequirementsError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_transaction(
    value: Any,
) -> tuple[PilotExactTaskRemotePublicationWriteTransaction, Mapping[str, Any], Any]:
    if type(value) is not PilotExactTaskRemotePublicationWriteTransaction:
        raise PilotExactTaskPrMutationRequirementsError(
            "exact ADR-DC-053 remote publication transaction is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationWriteTransaction.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-053 transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-053 transaction identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_WRITE_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or value.remote_publication_authorization_consumed is not True
        or value.remote_write_slot_consumed is not True
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
        or _REF.fullmatch(value.destination_ref) is None
    ):
        raise PilotExactTaskPrMutationRequirementsError(
            "PR requirements require one completed inert ADR-DC-053 transaction"
        )
    transaction_inputs = transaction_boundary._get_live_remote_publication_write_transaction_inputs(
        value
    )
    if transaction_inputs is None:
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-053 live transaction provenance is unavailable"
        )
    capability = transaction_inputs.get("remote_publication_credential_capability")
    if (
        capability is None
        or getattr(capability, "sha256", None) != value.credential_capability_sha256
        or getattr(capability, "capability_authenticated", None) is not True
    ):
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-053 lost exact ADR-DC-052 capability provenance"
        )
    return value, transaction_inputs, capability


def _remote_authorization_proof(capability: Any) -> Any:
    cap_inputs = capability_boundary._get_live_remote_publication_credential_capability_inputs(
        capability
    )
    if cap_inputs is None:
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-052 live capability provenance is unavailable"
        )
    reservation = cap_inputs.get("remote_publication_write_reservation")
    if reservation is None or getattr(reservation, "reservation_authenticated", None) is not True:
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-051 live reservation provenance is unavailable"
        )
    reservation_inputs = reservation_boundary._get_live_remote_publication_write_reservation_inputs(
        reservation
    )
    observation = None if reservation_inputs is None else reservation_inputs.get(
        "remote_publication_state_observation"
    )
    if observation is None or getattr(observation, "observation_authenticated", None) is not True:
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-050 live observation provenance is unavailable"
        )
    state_inputs = state_boundary._get_live_remote_publication_state_observation_inputs(
        observation
    )
    attestation = None if state_inputs is None else state_inputs.get(
        "remote_publication_target_attestation"
    )
    if attestation is None or getattr(attestation, "target_attestation_authenticated", None) is not True:
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-049 live target provenance is unavailable"
        )
    target_inputs = target_boundary._get_live_remote_publication_target_attestation_inputs(
        attestation
    )
    proof = None if target_inputs is None else target_inputs.get(
        "remote_publication_authorization_proof"
    )
    if (
        proof is None
        or getattr(proof, "sha256", None) != capability.authorization_proof_sha256
        or getattr(proof, "human_remote_publication_authorization_verified", None) is not True
    ):
        raise PilotExactTaskPrMutationRequirementsError(
            "ADR-DC-048 live human authorization provenance is unavailable"
        )
    return proof


def _pr_plan(
    *,
    transaction: PilotExactTaskRemotePublicationWriteTransaction,
) -> dict[str, Any]:
    head_branch = transaction.destination_ref.removeprefix("refs/heads/")
    title = f"RSI candidate {transaction.predicted_commit_sha[:12]}"
    body = (
        "Automated RSI candidate from a verified ModelRig DevControl chain.\n\n"
        f"Candidate commit: `{transaction.predicted_commit_sha}`\n"
        f"Remote transaction: `{transaction.sha256}`\n"
        f"Head: `{head_branch}`\n"
        f"Base: `{PILOT_EXACT_TASK_PR_MUTATION_BASE_BRANCH}`\n\n"
        "This pull request must remain draft. Review, merge, release, deploy, and "
        "production activation require separate authority."
    )
    return {
        "repository": PILOT_EXACT_TASK_PR_MUTATION_REPOSITORY,
        "base_branch": PILOT_EXACT_TASK_PR_MUTATION_BASE_BRANCH,
        "head_branch": head_branch,
        "title": title,
        "body": body,
        "draft": True,
        "maintainer_can_modify": False,
    }


def _plan_sha256(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(plan).encode("utf-8")).hexdigest()


def _live_registry():
    records: dict[
        int,
        tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any]],
    ] = {}

    def mark(requirements: Any, transaction: PilotExactTaskRemotePublicationWriteTransaction) -> None:
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
            or requirements.remote_write_transaction_sha256 != transaction.sha256
        ):
            return None
        return MappingProxyType({"remote_publication_write_transaction": transaction})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_pr_mutation_requirements_authenticated,
    _get_live_pr_mutation_requirements_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrMutationRequirements:
    remote_write_transaction_sha256: str
    credential_capability_sha256: str
    remote_write_reservation_sha256: str
    authorization_proof_sha256: str
    remote_publication_nonce_sha256: str
    execution_nonce_sha256: str
    local_write_nonce_sha256: str
    predicted_commit_sha: str
    destination_ref: str
    remote_verified_at_utc: str
    prior_remote_publication_authorizer_actor_id: str
    repository: str
    base_branch: str
    head_branch: str
    pr_title: str
    pr_body: str
    pr_plan_sha256: str
    materialized_at_utc: str
    remote_publication_completed: bool = True
    remote_ref_verified: bool = True
    create_new_draft_pull_request_required: bool = True
    base_branch_host_pinned: bool = True
    head_branch_exact_remote_candidate: bool = True
    pr_title_deterministic: bool = True
    pr_body_deterministic: bool = True
    maintainer_can_modify: bool = False
    separate_human_pr_mutation_authorization_required: bool = True
    one_shot_pr_mutation_nonce_required: bool = True
    no_existing_open_pr_required: bool = True
    ready_for_review_forbidden: bool = True
    reviewer_mutation_forbidden: bool = True
    label_mutation_forbidden: bool = True
    pr_mutation_authorization_consumed: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_created: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskPrMutationRequirementsError("PR requirements schema is unsupported")
        if (
            self.authority != PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_AUTHORITY
            or self.requirements_scope != PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCOPE
        ):
            raise PilotExactTaskPrMutationRequirementsError(
                "PR requirements authority/scope is unsupported"
            )
        for name in (
            "remote_write_transaction_sha256",
            "credential_capability_sha256",
            "remote_write_reservation_sha256",
            "authorization_proof_sha256",
            "remote_publication_nonce_sha256",
            "execution_nonce_sha256",
            "local_write_nonce_sha256",
            "pr_plan_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if _REF.fullmatch(self.destination_ref) is None:
            raise PilotExactTaskPrMutationRequirementsError("destination_ref is invalid")
        if self.remote_publication_nonce_sha256 in {
            self.execution_nonce_sha256,
            self.local_write_nonce_sha256,
        }:
            raise PilotExactTaskPrMutationRequirementsError(
                "remote publication nonce must remain distinct from prior nonces"
            )
        if (
            not isinstance(self.prior_remote_publication_authorizer_actor_id, str)
            or _ACTOR.fullmatch(self.prior_remote_publication_authorizer_actor_id) is None
        ):
            raise PilotExactTaskPrMutationRequirementsError(
                "prior remote-publication authorizer actor is invalid"
            )
        remote_verified = _utc(self.remote_verified_at_utc, name="remote_verified_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if materialized < remote_verified:
            raise PilotExactTaskPrMutationRequirementsError(
                "PR requirements predate remote verification"
            )
        expected_head = self.destination_ref.removeprefix("refs/heads/")
        if (
            self.repository != PILOT_EXACT_TASK_PR_MUTATION_REPOSITORY
            or self.base_branch != PILOT_EXACT_TASK_PR_MUTATION_BASE_BRANCH
            or self.head_branch != expected_head
            or not self.pr_title
            or len(self.pr_title) > 256
            or not self.pr_body
            or len(self.pr_body.encode("utf-8")) > 64 * 1024
        ):
            raise PilotExactTaskPrMutationRequirementsError(
                "PR requirements deterministic target/metadata binding is invalid"
            )
        expected_plan = {
            "repository": self.repository,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "title": self.pr_title,
            "body": self.pr_body,
            "draft": True,
            "maintainer_can_modify": False,
        }
        if self.pr_plan_sha256 != _plan_sha256(expected_plan):
            raise PilotExactTaskPrMutationRequirementsError(
                "PR plan digest does not match exact PR metadata"
            )
        required_true = (
            "remote_publication_completed",
            "remote_ref_verified",
            "create_new_draft_pull_request_required",
            "base_branch_host_pinned",
            "head_branch_exact_remote_candidate",
            "pr_title_deterministic",
            "pr_body_deterministic",
            "separate_human_pr_mutation_authorization_required",
            "one_shot_pr_mutation_nonce_required",
            "no_existing_open_pr_required",
            "ready_for_review_forbidden",
            "reviewer_mutation_forbidden",
            "label_mutation_forbidden",
        )
        forced_false = (
            "maintainer_can_modify",
            "pr_mutation_authorization_consumed",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrMutationRequirementsError(
                "PR requirements safety gates are incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrMutationRequirementsError(
                "PR requirements cannot grant mutation authority"
            )

    @property
    def requirements_authenticated(self) -> bool:
        return _get_live_pr_mutation_requirements_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrMutationRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrMutationRequirementsError(
                "PR requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrMutationRequirementsError(
                "PR requirements fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def materialize_pilot_exact_task_pr_mutation_requirements(
    remote_write_transaction: PilotExactTaskRemotePublicationWriteTransaction,
) -> PilotExactTaskPrMutationRequirements:
    transaction, _transaction_inputs, capability = _require_live_transaction(
        remote_write_transaction
    )
    proof = _remote_authorization_proof(capability)
    authorization = proof.authorization
    local_requirements = authorization.local_commit_publication_requirements
    actor = authorization.remote_publication_authorizer_actor_id
    plan = _pr_plan(transaction=transaction)
    result = PilotExactTaskPrMutationRequirements(
        remote_write_transaction_sha256=transaction.sha256,
        credential_capability_sha256=transaction.credential_capability_sha256,
        remote_write_reservation_sha256=transaction.remote_write_reservation_sha256,
        authorization_proof_sha256=transaction.authorization_proof_sha256,
        remote_publication_nonce_sha256=transaction.remote_publication_nonce_sha256,
        execution_nonce_sha256=local_requirements.execution_nonce_sha256,
        local_write_nonce_sha256=local_requirements.local_write_nonce_sha256,
        predicted_commit_sha=transaction.predicted_commit_sha,
        destination_ref=transaction.destination_ref,
        remote_verified_at_utc=transaction.verified_at_utc,
        prior_remote_publication_authorizer_actor_id=actor,
        repository=plan["repository"],
        base_branch=plan["base_branch"],
        head_branch=plan["head_branch"],
        pr_title=plan["title"],
        pr_body=plan["body"],
        pr_plan_sha256=_plan_sha256(plan),
        materialized_at_utc=_now_utc_seconds(),
    )
    _mark_pr_mutation_requirements_authenticated(result, transaction)
    if result.requirements_authenticated is not True:
        raise PilotExactTaskPrMutationRequirementsError(
            "PR requirements lost live ADR-DC-053 provenance"
        )
    return result


__all__ = [
    "PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_PR_MUTATION_REQUIREMENTS_SCOPE",
    "PILOT_EXACT_TASK_PR_MUTATION_BASE_BRANCH",
    "PILOT_EXACT_TASK_PR_MUTATION_REPOSITORY",
    "PilotExactTaskPrMutationRequirementsError",
    "PilotExactTaskPrMutationRequirements",
    "materialize_pilot_exact_task_pr_mutation_requirements",
]
