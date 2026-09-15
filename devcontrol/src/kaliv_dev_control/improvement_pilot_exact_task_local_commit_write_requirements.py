"""ADR-DC-043 inert requirements for one exact local commit write.

This boundary accepts only the exact live ADR-DC-042 commit-object identity and
freezes the host/human requirements that a later replay-safe write transaction
must satisfy before any Git object or local ref mutation may occur.

It performs no Git command, writes no object, moves no ref, and grants no local
or remote publication authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY,
    PilotExactTaskLocalCommitObjectIdentity,
)

PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-write-requirements/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_AUTHORITY = (
    "dc-l16-exact-local-commit-write-requirements-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCOPE = (
    "one-exact-local-commit-write-requirements-only-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskLocalCommitWriteRequirementsError(ValueError):
    """ADR-DC-043 local-commit write requirements are malformed or unsafe."""


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
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "local commit write requirements are not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskLocalCommitWriteRequirementsError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitWriteRequirementsError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitWriteRequirementsError(f"{name} is invalid")
    return value


def _require_live_identity(
    value: Any,
) -> tuple[PilotExactTaskLocalCommitObjectIdentity, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskLocalCommitObjectIdentity:
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "exact ADR-DC-042 local commit object identity is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitObjectIdentity.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "ADR-DC-042 identity replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "ADR-DC-042 identity replay mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY
        or value.identity_authenticated is not True
        or value.local_commit_plan_authenticated is not True
        or value.fresh_workspace_snapshot_matched is not True
        or value.index_manifest_bound is not True
        or value.root_tree_identity_materialized is not True
        or value.commit_object_identity_materialized is not True
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.local_commit_created is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "write requirements require one live inert ADR-DC-042 identity"
        )
    inputs = identity_boundary._get_live_local_commit_object_identity_inputs(value)
    if inputs is None:
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "ADR-DC-042 live identity inputs are unavailable"
        )
    plan = inputs.get("local_commit_plan")
    if (
        plan is None
        or getattr(plan, "sha256", None) != value.local_commit_plan_sha256
        or getattr(plan, "plan_authenticated", None) is not True
        or getattr(plan, "execution_nonce_sha256", None) != value.execution_nonce_sha256
        or getattr(plan, "development_task_sha256", None) != value.development_task_sha256
        or getattr(plan, "candidate_patch_sha256", None) != value.candidate_patch_sha256
        or getattr(plan, "candidate_numstat_sha256", None) != value.candidate_numstat_sha256
        or getattr(plan, "scope_policy_sha256", None) != value.scope_policy_sha256
        or getattr(plan, "commit_subject_sha256", None) != value.commit_subject_sha256
    ):
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "ADR-DC-042 identity is not bound to the exact live ADR-DC-041 plan"
        )
    return value, inputs


def _execution_authorizer_actor_id(
    *,
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> str:
    receipt = inputs.get("admission_receipt")
    try:
        proof = receipt.revalidation_attestation_proof
        execution_proof = proof.attestation.packet.execution_authorization_proof
        authorization = execution_proof.authorization
        actor_id = authorization.execution_authorizer_actor_id
    except AttributeError as exc:
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "upstream human execution-authority provenance is unavailable"
        ) from exc
    if (
        getattr(receipt, "execution_nonce_sha256", None) != identity.execution_nonce_sha256
        or getattr(receipt, "execution_authorization_proof_sha256", None)
        != getattr(execution_proof, "sha256", None)
        or getattr(execution_proof, "execution_nonce_sha256", None)
        != identity.execution_nonce_sha256
    ):
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "upstream human execution-authority provenance is not exact-bound"
        )
    return _actor(actor_id, name="execution_authorizer_actor_id")


_REQUIRED_TRUE = (
    "local_commit_write_requirements_materialized",
    "exact_live_identity_required",
    "fresh_identity_revalidation_required",
    "fresh_workspace_snapshot_required",
    "exact_index_manifest_revalidation_required",
    "exact_root_tree_revalidation_required",
    "exact_commit_payload_revalidation_required",
    "separate_human_local_commit_authorization_required",
    "human_local_commit_authorizer_continuity_required",
    "one_shot_local_write_nonce_required",
    "local_write_nonce_distinct_from_execution_nonce_required",
    "canonical_local_write_ledger_required",
    "durable_prewrite_reservation_required",
    "reservation_before_git_object_write_required",
    "uncertain_write_reservation_fails_closed",
    "git_object_write_via_trusted_git_only_required",
    "exact_predicted_commit_sha_required",
    "local_ref_target_host_pinned_required",
    "atomic_compare_and_swap_ref_update_required",
    "ref_update_after_commit_object_verification_required",
    "post_write_commit_object_verification_required",
    "post_write_ref_verification_required",
    "remote_write_forbidden",
)

_FORCED_FALSE = (
    "git_object_write_authorized",
    "local_ref_update_authorized",
    "local_commit_authorized",
    "local_commit_created",
    "integration_ready",
    "product_pilot_started",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
)


@dataclass(frozen=True, slots=True)
class PilotExactTaskLocalCommitWriteRequirements:
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    post_execution_evaluation_sha256: str
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    execution_authorizer_actor_id: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    candidate_patch_sha256: str
    candidate_numstat_sha256: str
    scope_policy_sha256: str
    index_manifest_sha256: str
    root_tree_sha: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    commit_subject_sha256: str
    commit_message_policy: str
    materialized_at_utc: str
    local_commit_write_requirements_materialized: bool = True
    exact_live_identity_required: bool = True
    fresh_identity_revalidation_required: bool = True
    fresh_workspace_snapshot_required: bool = True
    exact_index_manifest_revalidation_required: bool = True
    exact_root_tree_revalidation_required: bool = True
    exact_commit_payload_revalidation_required: bool = True
    separate_human_local_commit_authorization_required: bool = True
    human_local_commit_authorizer_continuity_required: bool = True
    one_shot_local_write_nonce_required: bool = True
    local_write_nonce_distinct_from_execution_nonce_required: bool = True
    canonical_local_write_ledger_required: bool = True
    durable_prewrite_reservation_required: bool = True
    reservation_before_git_object_write_required: bool = True
    uncertain_write_reservation_fails_closed: bool = True
    git_object_write_via_trusted_git_only_required: bool = True
    exact_predicted_commit_sha_required: bool = True
    local_ref_target_host_pinned_required: bool = True
    atomic_compare_and_swap_ref_update_required: bool = True
    ref_update_after_commit_object_verification_required: bool = True
    post_write_commit_object_verification_required: bool = True
    post_write_ref_verification_required: bool = True
    remote_write_forbidden: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements schema is unsupported"
            )
        if self.requirements_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCOPE:
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements scope is unsupported"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_AUTHORITY:
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements authority is unsupported"
            )

        for name in (
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "post_execution_evaluation_sha256",
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "candidate_numstat_sha256",
            "scope_policy_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
            "commit_subject_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        _actor(self.execution_authorizer_actor_id, name="execution_authorizer_actor_id")

        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskLocalCommitWriteRequirementsError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskLocalCommitWriteRequirementsError("repository is invalid")
        if (
            not isinstance(self.commit_message_policy, str)
            or not self.commit_message_policy
            or self.commit_message_policy.strip() != self.commit_message_policy
        ):
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "commit_message_policy is invalid"
            )
        if (
            not isinstance(self.materialized_at_utc, str)
            or _UTC.fullmatch(self.materialized_at_utc) is None
        ):
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "materialized_at_utc is invalid"
            )

        if any(getattr(self, name) is not True for name in _REQUIRED_TRUE):
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements are incomplete"
            )
        if any(getattr(self, name) is not False for name in _FORCED_FALSE):
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements cannot grant write/publication authority"
            )

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
        cls,
        value: Any,
    ) -> "PilotExactTaskLocalCommitWriteRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskLocalCommitWriteRequirements":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitWriteRequirementsError(
                "local commit write requirements JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def materialize_pilot_exact_task_local_commit_write_requirements(
    local_commit_object_identity: PilotExactTaskLocalCommitObjectIdentity,
) -> PilotExactTaskLocalCommitWriteRequirements:
    """Freeze inert ADR-DC-043 requirements from one exact live ADR-DC-042 identity."""
    try:
        identity, inputs = _require_live_identity(local_commit_object_identity)
        actor_id = _execution_authorizer_actor_id(identity=identity, inputs=inputs)
        return PilotExactTaskLocalCommitWriteRequirements(
            local_commit_object_identity_sha256=identity.sha256,
            local_commit_plan_sha256=identity.local_commit_plan_sha256,
            post_execution_evaluation_sha256=identity.post_execution_evaluation_sha256,
            execution_transaction_sha256=identity.execution_transaction_sha256,
            tier_a_receipt_sha256=identity.tier_a_receipt_sha256,
            execution_nonce_sha256=identity.execution_nonce_sha256,
            execution_authorizer_actor_id=actor_id,
            development_task_sha256=identity.development_task_sha256,
            task_id=identity.task_id,
            repository=identity.repository,
            base_sha=identity.base_sha,
            candidate_patch_sha256=identity.candidate_patch_sha256,
            candidate_numstat_sha256=identity.candidate_numstat_sha256,
            scope_policy_sha256=identity.scope_policy_sha256,
            index_manifest_sha256=identity.index_manifest_sha256,
            root_tree_sha=identity.root_tree_sha,
            commit_payload_sha256=identity.commit_payload_sha256,
            predicted_commit_sha=identity.predicted_commit_sha,
            commit_subject_sha256=identity.commit_subject_sha256,
            commit_message_policy=identity.commit_message_policy,
            materialized_at_utc=identity.materialized_at_utc,
        )
    except PilotExactTaskLocalCommitWriteRequirementsError:
        raise
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotExactTaskLocalCommitWriteRequirementsError(
            "host-controlled local commit write requirements failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_WRITE_REQUIREMENTS_SCOPE",
    "PilotExactTaskLocalCommitWriteRequirementsError",
    "PilotExactTaskLocalCommitWriteRequirements",
    "materialize_pilot_exact_task_local_commit_write_requirements",
]
