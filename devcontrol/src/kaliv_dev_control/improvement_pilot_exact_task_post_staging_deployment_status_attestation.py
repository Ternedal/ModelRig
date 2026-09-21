"""ADR-DC-082 read-only exact post-staging Deployment Status attestation.

Normalizes exactly one completed ADR-DC-080 first Deployment Status transaction or
one completed ADR-DC-081 recovery into a restart-safe exact status attestation.
Durable completion evidence is reconstructed first, then the exact frozen first
``in_progress`` staging Deployment Status is observed twice through the
credential-bound GET-only recovery observer.

This boundary grants no Deployment Status, Deployment, release, merge, review,
production, or other remote mutation authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from ._improvement_pilot_start_consumption_impl import _safe_ledger_root
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from . import improvement_pilot_exact_task_staging_deployment_status_authorization as auth_boundary
from . import improvement_pilot_exact_task_staging_deployment_status_recovery as recovery_boundary
from . import improvement_pilot_exact_task_staging_deployment_status_transaction as tx_boundary
from .improvement_pilot_exact_task_staging_deployment_status_recovery import (
    PilotExactTaskStagingDeploymentStatusRecoveryReceipt,
)
from .improvement_pilot_exact_task_staging_deployment_status_transaction import (
    PilotExactTaskStagingDeploymentStatusTransactionReceipt,
)

PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-staging-deployment-status-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-staging-deployment-status-state-only"
)
PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_SCOPE = (
    "read-only-exact-post-staging-deployment-status-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPostStagingDeploymentStatusAttestationError(ValueError):
    """Durable first-status completion or exact remote state is untrustworthy."""


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
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "post-status evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "durable status payload is missing"
        )
    return hashlib.sha256(payload).hexdigest()


def _read_canonical(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        return recovery_boundary._read_canonical_object(path, name=name)
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            f"{name} is unavailable or invalid"
        ) from exc


@dataclass(frozen=True, slots=True)
class _StatusCompletionEvidence:
    source_kind: str
    source_receipt_sha256: str
    source_completed_at_utc: str
    transaction_lock_sha256: str
    recovery_lock_sha256: str | None
    source_final_remote_status_state_sha256: str
    deployment_status_id: int
    deployment_status_node_id_sha256: str
    source_action: str
    source_remote_write_performed: bool

    def __post_init__(self) -> None:
        if self.source_kind not in {"transaction", "recovery"}:
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "status completion source kind is unsupported"
            )
        for name in (
            "source_receipt_sha256",
            "transaction_lock_sha256",
            "source_final_remote_status_state_sha256",
            "deployment_status_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.recovery_lock_sha256 is not None:
            _hex64(self.recovery_lock_sha256, name="status_recovery_lock_sha256")
        if (
            isinstance(self.deployment_status_id, bool)
            or not isinstance(self.deployment_status_id, int)
            or self.deployment_status_id < 1
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "status completion ID is invalid"
            )
        if self.source_kind == "transaction":
            if (
                self.recovery_lock_sha256 is not None
                or self.source_action != "execute_exact_first_staging_deployment_status"
                or self.source_remote_write_performed is not True
            ):
                raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                    "normal status completion evidence is inconsistent"
                )
        elif (
            self.recovery_lock_sha256 is None
            or self.source_action != "finalize_existing_state"
            or self.source_remote_write_performed is not False
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "recovered status completion evidence is inconsistent"
            )
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")


def _transaction_lock_payload(*, authorization: Any, ledger: Any) -> bytes:
    _final, lock = ledger._paths(authorization.deployment_status_intent_sha256)
    raw, payload = _read_canonical(
        lock,
        name="ADR-DC-080 first Deployment Status transaction lock",
    )
    expected = {
        "schema": (
            "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-transaction-lock/v1"
        ),
        "ledger_scope": tx_boundary.PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "deployment_status_transaction_key_sha256": authorization.deployment_status_intent_sha256,
        "deployment_status_authorization_sha256": authorization.sha256,
        "deployment_status_state_observation_sha256": authorization.deployment_status_state_observation_sha256,
        "staging_deployment_status_plan_sha256": authorization.staging_deployment_status_plan_sha256,
        "deployment_status_intent_sha256": authorization.deployment_status_intent_sha256,
        "remote_pre_write_status_state_sha256": authorization.remote_deployment_status_state_sha256,
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_id": authorization.deployment_id,
        "deployment_node_id_sha256": authorization.deployment_node_id_sha256,
        "deployment_status_state": authorization.deployment_status_state,
        "deployment_status_environment": authorization.deployment_status_environment,
        "deployment_status_description_sha256": authorization.deployment_status_description_sha256,
        "deployment_status_body_sha256": authorization.deployment_status_body_sha256,
    }
    if raw != expected:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "ADR-DC-080 transaction lock differs from exact first-status authority"
        )
    return payload


def _validate_common_projection(*, receipt: Any, authorization: Any) -> None:
    expected = {
        "deployment_status_authorization_sha256": authorization.sha256,
        "staging_deployment_status_plan_sha256": authorization.staging_deployment_status_plan_sha256,
        "post_staging_deployment_attestation_sha256": authorization.post_staging_deployment_attestation_sha256,
        "completion_source_receipt_sha256": authorization.completion_source_receipt_sha256,
        "deployment_authorization_sha256": authorization.deployment_authorization_sha256,
        "deployment_intent_sha256": authorization.deployment_intent_sha256,
        "execution_nonce_sha256": authorization.execution_nonce_sha256,
        "deployment_status_intent_sha256": authorization.deployment_status_intent_sha256,
        "publisher_credential_config_sha256": authorization.publisher_credential_config_sha256,
        "publisher_credential_path_sha256": authorization.publisher_credential_path_sha256,
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_environment": authorization.deployment_environment,
        "merge_commit_sha": authorization.merge_commit_sha,
        "deployment_identity": authorization.deployment_identity,
        "deployment_ref": authorization.deployment_ref,
        "deployment_task": authorization.deployment_task,
        "deployment_id": authorization.deployment_id,
        "deployment_node_id_sha256": authorization.deployment_node_id_sha256,
        "completion_source": authorization.completion_source,
        "source_action": authorization.source_action,
        "source_remote_write_performed": authorization.source_remote_write_performed,
        "deployment_status_state": authorization.deployment_status_state,
        "deployment_status_environment": authorization.deployment_status_environment,
        "deployment_status_description_sha256": authorization.deployment_status_description_sha256,
        "deployment_status_body_sha256": authorization.deployment_status_body_sha256,
    }
    if any(getattr(receipt, name, None) != value for name, value in expected.items()):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "status completion projection differs from exact ADR-DC-079 authorization"
        )


def _read_completion(
    *,
    authorization: Any,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
) -> _StatusCompletionEvidence:
    key = authorization.deployment_status_intent_sha256
    tx_ledger = tx_boundary._PilotExactTaskStagingDeploymentStatusTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    recovery_ledger = recovery_boundary._PilotExactTaskStagingDeploymentStatusRecoveryLedger(
        _safe_ledger_root(recovery_ledger_root)
    )
    tx_final, _tx_lock = tx_ledger._paths(key)
    recovery_final, recovery_lock = recovery_ledger._paths(key)
    tx_present = tx_final.exists() or tx_final.is_symlink()
    recovery_present = recovery_final.exists() or recovery_final.is_symlink()
    if tx_present == recovery_present:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "post-status completion source must be exactly one of ADR-DC-080 or ADR-DC-081"
        )
    tx_lock_payload = _transaction_lock_payload(
        authorization=authorization,
        ledger=tx_ledger,
    )
    tx_lock_sha = _payload_sha256(tx_lock_payload)

    if tx_present:
        raw, payload = _read_canonical(
            tx_final,
            name="ADR-DC-080 final first Deployment Status transaction receipt",
        )
        try:
            receipt = PilotExactTaskStagingDeploymentStatusTransactionReceipt.from_mapping(
                raw
            )
        except Exception as exc:
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "ADR-DC-080 final first-status receipt is invalid"
            ) from exc
        _validate_common_projection(receipt=receipt, authorization=authorization)
        if (
            receipt.canonical_json().encode("utf-8") != payload
            or receipt.status_transaction_ledger_root_path_sha256
            != tx_ledger.root_sha256
            or receipt.deployment_status_transaction_key_sha256 != key
            or receipt.deployment_status_transaction_lock_sha256 != tx_lock_sha
            or receipt.deployment_status_state_observation_sha256
            != authorization.deployment_status_state_observation_sha256
            or receipt.transaction_lock_committed is not True
            or receipt.deployment_status_authorization_authenticated is not True
            or receipt.pre_write_clear_revalidated is not True
            or receipt.post_lock_clear_revalidated is not True
            or receipt.first_deployment_status_created is not True
            or receipt.exact_post_write_state_verified is not True
            or receipt.deployment_status_mutation_authorized is not False
            or receipt.deployment_mutation_authorized is not False
            or receipt.deploy_authorized is not False
            or receipt.remote_write_authorized is not False
            or receipt.production_activation_authorized is not False
            or receipt.nonce_reusable is not False
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "ADR-DC-080 final receipt is not exact first-status completion"
            )
        return _StatusCompletionEvidence(
            source_kind="transaction",
            source_receipt_sha256=receipt.sha256,
            source_completed_at_utc=receipt.created_at_utc,
            transaction_lock_sha256=tx_lock_sha,
            recovery_lock_sha256=None,
            source_final_remote_status_state_sha256=(
                receipt.post_write_remote_status_state_sha256
            ),
            deployment_status_id=receipt.deployment_status_id,
            deployment_status_node_id_sha256=receipt.deployment_status_node_id_sha256,
            source_action="execute_exact_first_staging_deployment_status",
            source_remote_write_performed=True,
        )

    raw, payload = _read_canonical(
        recovery_final,
        name="ADR-DC-081 final first Deployment Status recovery receipt",
    )
    recovery_lock_raw, recovery_lock_payload = _read_canonical(
        recovery_lock,
        name="ADR-DC-081 first Deployment Status recovery lock",
    )
    try:
        receipt = PilotExactTaskStagingDeploymentStatusRecoveryReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "ADR-DC-081 final first-status recovery receipt is invalid"
        ) from exc
    _validate_common_projection(receipt=receipt, authorization=authorization)
    expected_recovery_lock = {
        "schema": (
            "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-recovery-lock/v1"
        ),
        "ledger_scope": recovery_boundary.PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_RECOVERY_LEDGER_SCOPE,
        "ledger_root_path_sha256": recovery_ledger.root_sha256,
        "recovery_key_sha256": key,
        "recovery_state_fingerprint_sha256": receipt.recovery_state_fingerprint_sha256,
        "recovery_authorization_payload_sha256": receipt.recovery_authorization_payload_sha256,
        "deployment_status_authorization_sha256": authorization.sha256,
        "transaction_lock_sha256": tx_lock_sha,
        "action": "finalize_existing_state",
    }
    if any(
        recovery_lock_raw.get(name) != value
        for name, value in expected_recovery_lock.items()
    ):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "ADR-DC-081 recovery lock does not bind final recovery receipt"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(recovery_lock_raw.get(name), name=name)
    if set(recovery_lock_raw) != set(expected_recovery_lock) | {
        "operator_signature_sha256",
        "reviewer_signature_sha256",
    }:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "ADR-DC-081 recovery lock carries unexpected fields"
        )
    if (
        receipt.canonical_json().encode("utf-8") != payload
        or receipt.recovery_ledger_root_path_sha256 != recovery_ledger.root_sha256
        or receipt.recovery_key_sha256 != key
        or receipt.transaction_lock_sha256 != tx_lock_sha
        or receipt.source_durable_phase != "lock_only"
        or receipt.source_remote_state_class != "exact_existing"
        or receipt.action_performed != "finalize_existing_state"
        or receipt.remote_write_performed is not False
        or receipt.durable_state_verified is not True
        or receipt.remote_state_verified is not True
        or receipt.recovery_authority_consumed is not True
        or receipt.exact_first_deployment_status_finalized is not True
        or receipt.recovery_completed is not True
        or receipt.deployment_status_mutation_authorized is not False
        or receipt.deployment_mutation_authorized is not False
        or receipt.deploy_authorized is not False
        or receipt.remote_write_authorized is not False
        or receipt.production_activation_authorized is not False
        or receipt.nonce_reusable is not False
    ):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "ADR-DC-081 final receipt is not exact recovered first-status completion"
        )
    return _StatusCompletionEvidence(
        source_kind="recovery",
        source_receipt_sha256=receipt.sha256,
        source_completed_at_utc=receipt.recovered_at_utc,
        transaction_lock_sha256=tx_lock_sha,
        recovery_lock_sha256=_payload_sha256(recovery_lock_payload),
        source_final_remote_status_state_sha256=(
            receipt.final_remote_deployment_status_state_sha256
        ),
        deployment_status_id=receipt.deployment_status_id,
        deployment_status_node_id_sha256=receipt.deployment_status_node_id_sha256,
        source_action="finalize_existing_state",
        source_remote_write_performed=False,
    )


def _observe_exact_twice(
    *,
    authorization: Any,
    completion: _StatusCompletionEvidence,
    transport: Any,
) -> tuple[str, str, str]:
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "fresh GET-only first-status observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != authorization.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != authorization.publisher_credential_path_sha256
    ):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "post-status observer credential identity differs from ADR-DC-079"
        )
    try:
        first = transport.observe(authorization)
        second = transport.observe(authorization)
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "fresh first-status observation failed"
        ) from exc
    if (
        type(first) is not recovery_boundary._StatusRecoveryRemoteState
        or type(second) is not recovery_boundary._StatusRecoveryRemoteState
        or first != second
    ):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "first Deployment Status changed between attestation observations"
        )
    for value in (first, second):
        if (
            value.repository != authorization.repository
            or value.repository_id != authorization.repository_id
            or value.deployment_id != authorization.deployment_id
            or value.deployment_node_id_sha256
            != authorization.deployment_node_id_sha256
            or value.remote_state_class != "exact_existing"
            or value.deployment_status_lane_state != "exact"
            or value.deployment_status_id != completion.deployment_status_id
            or value.deployment_status_node_id_sha256
            != completion.deployment_status_node_id_sha256
            or value.observed_status_state != authorization.deployment_status_state
            or value.observed_status_environment
            != authorization.deployment_status_environment
            or value.observed_status_description_sha256
            != authorization.deployment_status_description_sha256
            or value.observed_status_log_url is not None
            or value.observed_status_environment_url is not None
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "GitHub state is not exact completed first staging Deployment Status"
            )
    observed_sha = first.sha256
    created = first.status_created_at_utc
    updated = first.status_updated_at_utc
    assert created is not None
    assert updated is not None
    return observed_sha, created, updated


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], str, str, str]] = {}

    def mark(
        receipt: Any,
        *,
        source_kind: str,
        source_receipt_sha256: str,
        observation_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            source_kind,
            source_receipt_sha256,
            observation_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            ref,
            source_kind,
            source_receipt_sha256,
            observation_sha256,
        ) = entry
        if (
            pid != os.getpid()
            or ref() is not receipt
            or receipt.sha256 != digest
            or receipt.status_completion_source != source_kind
            or receipt.status_completion_source_receipt_sha256
            != source_receipt_sha256
            or receipt.remote_status_observation_sha256 != observation_sha256
        ):
            return None
        return MappingProxyType(
            {
                "status_completion_source": source_kind,
                "status_completion_source_receipt_sha256": source_receipt_sha256,
                "remote_status_observation_sha256": observation_sha256,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_post_staging_deployment_status_attestation_authenticated,
    _get_live_post_staging_deployment_status_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostStagingDeploymentStatusAttestationReceipt:
    status_completion_source_receipt_sha256: str
    deployment_status_authorization_sha256: str
    deployment_status_state_observation_sha256: str
    staging_deployment_status_plan_sha256: str
    post_staging_deployment_attestation_sha256: str
    upstream_completion_source_receipt_sha256: str
    deployment_authorization_sha256: str
    deployment_state_observation_sha256: str
    staging_deployment_plan_sha256: str
    deploy_readiness_evaluation_sha256: str
    post_release_attestation_sha256: str
    deployment_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    release_transaction_lock_sha256: str
    deployment_transaction_lock_sha256: str
    deployment_recovery_lock_sha256: str | None
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    source_final_remote_status_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_status_observation_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_identity: str
    deployment_ref: str
    deployment_task: str
    deployment_payload_sha256: str
    deployment_description_sha256: str
    deployment_id: int
    deployment_node_id_sha256: str
    deployment_completion_source: str
    deployment_source_action: str
    deployment_source_remote_write_performed: bool
    deployment_status_state: str
    deployment_status_environment: str
    deployment_status_description_sha256: str
    deployment_status_body_sha256: str
    deployment_status_id: int
    deployment_status_node_id_sha256: str
    status_created_at_utc: str
    status_updated_at_utc: str
    status_completion_source: str
    status_source_action: str
    status_source_remote_write_performed: bool
    source_completed_at_utc: str
    attested_at_utc: str
    durable_completion_verified: bool = True
    exact_parent_deployment_verified: bool = True
    exact_remote_deployment_status_verified: bool = True
    exact_status_identity_verified: bool = True
    exact_status_state_verified: bool = True
    exact_status_environment_verified: bool = True
    exact_status_description_verified: bool = True
    status_urls_absent_verified: bool = True
    double_observation_matched: bool = True
    post_staging_deployment_status_verified: bool = True
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    attestation_scope: str = (
        PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_SCOPE
    )
    authority: str = PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_AUTHORITY
            or self.attestation_scope
            != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "post-status attestation identity is unsupported"
            )
        for name in (
            "status_completion_source_receipt_sha256",
            "deployment_status_authorization_sha256",
            "deployment_status_state_observation_sha256",
            "staging_deployment_status_plan_sha256",
            "post_staging_deployment_attestation_sha256",
            "upstream_completion_source_receipt_sha256",
            "deployment_authorization_sha256",
            "deployment_state_observation_sha256",
            "staging_deployment_plan_sha256",
            "deploy_readiness_evaluation_sha256",
            "post_release_attestation_sha256",
            "deployment_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "release_transaction_lock_sha256",
            "deployment_transaction_lock_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "source_final_remote_status_state_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_status_observation_sha256",
            "deployment_payload_sha256",
            "deployment_description_sha256",
            "deployment_node_id_sha256",
            "deployment_status_description_sha256",
            "deployment_status_body_sha256",
            "deployment_status_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "deployment_recovery_lock_sha256",
            "status_recovery_lock_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.deployment_task != "deploy"
            or self.deployment_identity != f"modelrig-staging-{self.merge_commit_sha}"
            or self.deployment_ref != f"modelrig-rsi-{self.merge_commit_sha}"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.deployment_status_id, bool)
            or not isinstance(self.deployment_status_id, int)
            or self.deployment_status_id < 1
            or self.deployment_completion_source not in {"transaction", "recovery"}
            or self.deployment_source_action
            not in {"execute_exact_staging_deployment", "finalize_existing_state"}
            or not isinstance(self.deployment_source_remote_write_performed, bool)
            or self.deployment_status_state != "in_progress"
            or self.deployment_status_environment != "staging"
            or self.status_completion_source not in {"transaction", "recovery"}
            or self.status_source_action
            not in {
                "execute_exact_first_staging_deployment_status",
                "finalize_existing_state",
            }
            or not isinstance(self.status_source_remote_write_performed, bool)
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "post-status deterministic identity is invalid"
            )
        if self.deployment_completion_source == "transaction":
            if (
                self.deployment_source_action != "execute_exact_staging_deployment"
                or self.deployment_source_remote_write_performed is not True
                or self.deployment_recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                    "normal upstream deployment completion source is inconsistent"
                )
        elif (
            self.deployment_source_action != "finalize_existing_state"
            or self.deployment_source_remote_write_performed is not False
            or self.deployment_recovery_lock_sha256 is None
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "recovered upstream deployment completion source is inconsistent"
            )
        if self.status_completion_source == "transaction":
            if (
                self.status_source_action
                != "execute_exact_first_staging_deployment_status"
                or self.status_source_remote_write_performed is not True
                or self.status_recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                    "normal status completion source is inconsistent"
                )
        elif (
            self.status_source_action != "finalize_existing_state"
            or self.status_source_remote_write_performed is not False
            or self.status_recovery_lock_sha256 is None
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "recovered status completion source is inconsistent"
            )
        created = _utc(self.status_created_at_utc, name="status_created_at_utc")
        updated = _utc(self.status_updated_at_utc, name="status_updated_at_utc")
        source_time = _utc(
            self.source_completed_at_utc, name="source_completed_at_utc"
        )
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if updated < created or attested < source_time or attested < updated:
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "post-status attestation timestamps are invalid"
            )
        required_true = (
            "durable_completion_verified",
            "exact_parent_deployment_verified",
            "exact_remote_deployment_status_verified",
            "exact_status_identity_verified",
            "exact_status_state_verified",
            "exact_status_environment_verified",
            "exact_status_description_verified",
            "status_urls_absent_verified",
            "double_observation_matched",
            "post_staging_deployment_status_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "post-status attestation evidence is incomplete"
            )
        forced_false = (
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "post-status attestation retains forbidden mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return (
            _get_live_post_staging_deployment_status_attestation_inputs(self)
            is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)
        ):
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "post-status attestation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_post_staging_deployment_status(
    *,
    deployment_status_intent_sha256: str,
    status_transaction_ledger_root: Path,
    status_recovery_ledger_root: Path,
    status_authorization_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskPostStagingDeploymentStatusAttestationReceipt:
    key = _hex64(
        deployment_status_intent_sha256,
        name="deployment_status_intent_sha256",
    )
    try:
        authorization = recovery_boundary._load_durable_authorization(
            key,
            _safe_ledger_root(status_authorization_ledger_root),
        )
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "durable ADR-DC-079 authorization could not be reconstructed"
        ) from exc
    completion = _read_completion(
        authorization=authorization,
        transaction_ledger_root=status_transaction_ledger_root,
        recovery_ledger_root=status_recovery_ledger_root,
    )
    observed_sha, status_created_at, status_updated_at = _observe_exact_twice(
        authorization=authorization,
        completion=completion,
        transport=transport,
    )
    attested_at = now_provider()
    if _utc(attested_at, name="attested_at_utc") < _utc(
        completion.source_completed_at_utc,
        name="source_completed_at_utc",
    ) or _utc(attested_at, name="attested_at_utc") < _utc(
        status_updated_at,
        name="status_updated_at_utc",
    ):
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "system clock moved backwards before post-status attestation"
        )
    receipt = PilotExactTaskPostStagingDeploymentStatusAttestationReceipt(
        status_completion_source_receipt_sha256=completion.source_receipt_sha256,
        deployment_status_authorization_sha256=authorization.sha256,
        deployment_status_state_observation_sha256=authorization.deployment_status_state_observation_sha256,
        staging_deployment_status_plan_sha256=authorization.staging_deployment_status_plan_sha256,
        post_staging_deployment_attestation_sha256=authorization.post_staging_deployment_attestation_sha256,
        upstream_completion_source_receipt_sha256=authorization.completion_source_receipt_sha256,
        deployment_authorization_sha256=authorization.deployment_authorization_sha256,
        deployment_state_observation_sha256=authorization.deployment_state_observation_sha256,
        staging_deployment_plan_sha256=authorization.staging_deployment_plan_sha256,
        deploy_readiness_evaluation_sha256=authorization.deploy_readiness_evaluation_sha256,
        post_release_attestation_sha256=authorization.post_release_attestation_sha256,
        deployment_intent_sha256=authorization.deployment_intent_sha256,
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        development_task_sha256=authorization.development_task_sha256,
        candidate_patch_sha256=authorization.candidate_patch_sha256,
        pr_intent_sha256=authorization.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=authorization.upstream_merge_transaction_lock_sha256,
        release_transaction_lock_sha256=authorization.release_transaction_lock_sha256,
        deployment_transaction_lock_sha256=authorization.transaction_lock_sha256,
        deployment_recovery_lock_sha256=authorization.recovery_lock_sha256,
        deployment_status_intent_sha256=authorization.deployment_status_intent_sha256,
        status_transaction_lock_sha256=completion.transaction_lock_sha256,
        status_recovery_lock_sha256=completion.recovery_lock_sha256,
        source_final_remote_status_state_sha256=completion.source_final_remote_status_state_sha256,
        publisher_credential_config_sha256=authorization.publisher_credential_config_sha256,
        publisher_credential_path_sha256=authorization.publisher_credential_path_sha256,
        remote_status_observation_sha256=observed_sha,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        deployment_environment=authorization.deployment_environment,
        merge_commit_sha=authorization.merge_commit_sha,
        deployment_identity=authorization.deployment_identity,
        deployment_ref=authorization.deployment_ref,
        deployment_task=authorization.deployment_task,
        deployment_payload_sha256=authorization.deployment_payload_sha256,
        deployment_description_sha256=authorization.deployment_description_sha256,
        deployment_id=authorization.deployment_id,
        deployment_node_id_sha256=authorization.deployment_node_id_sha256,
        deployment_completion_source=authorization.completion_source,
        deployment_source_action=authorization.source_action,
        deployment_source_remote_write_performed=authorization.source_remote_write_performed,
        deployment_status_state=authorization.deployment_status_state,
        deployment_status_environment=authorization.deployment_status_environment,
        deployment_status_description_sha256=authorization.deployment_status_description_sha256,
        deployment_status_body_sha256=authorization.deployment_status_body_sha256,
        deployment_status_id=completion.deployment_status_id,
        deployment_status_node_id_sha256=completion.deployment_status_node_id_sha256,
        status_created_at_utc=status_created_at,
        status_updated_at_utc=status_updated_at,
        status_completion_source=completion.source_kind,
        status_source_action=completion.source_action,
        status_source_remote_write_performed=completion.source_remote_write_performed,
        source_completed_at_utc=completion.source_completed_at_utc,
        attested_at_utc=attested_at,
    )
    _mark_post_staging_deployment_status_attestation_authenticated(
        receipt,
        source_kind=completion.source_kind,
        source_receipt_sha256=completion.source_receipt_sha256,
        observation_sha256=observed_sha,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "post-status attestation lost live provenance"
        )
    return receipt


def _canonical_runtime():
    try:
        _require_elevated_operator()
        if os.name == "posix":
            transaction_root = _require_host_controlled_ledger_root(
                tx_boundary._POSIX_LEDGER
            )
            recovery_root = _require_host_controlled_ledger_root(
                recovery_boundary._POSIX_LEDGER
            )
            authorization_root = _require_host_controlled_ledger_root(
                auth_boundary._POSIX_LEDGER
            )
        elif os.name == "nt":
            transaction_root = _require_host_controlled_ledger_root(
                tx_boundary._WINDOWS_LEDGER
            )
            recovery_root = _require_host_controlled_ledger_root(
                recovery_boundary._WINDOWS_LEDGER
            )
            authorization_root = _require_host_controlled_ledger_root(
                auth_boundary._WINDOWS_LEDGER
            )
        else:
            raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
                "post-status attestation platform is unsupported"
            )
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        observer = recovery_boundary._GitHubStagingDeploymentStatusRecoveryTransport(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return transaction_root, recovery_root, authorization_root, observer
    except PilotExactTaskPostStagingDeploymentStatusAttestationError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskPostStagingDeploymentStatusAttestationError(
            "post-status attestation runtime is not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_post_staging_deployment_status(
    deployment_status_intent_sha256: str,
) -> PilotExactTaskPostStagingDeploymentStatusAttestationReceipt:
    """Attest one completed exact first staging Deployment Status without writes."""
    transaction_root, recovery_root, authorization_root, observer = (
        _canonical_runtime()
    )
    return _attest_verified_pilot_exact_task_post_staging_deployment_status(
        deployment_status_intent_sha256=deployment_status_intent_sha256,
        status_transaction_ledger_root=transaction_root,
        status_recovery_ledger_root=recovery_root,
        status_authorization_ledger_root=authorization_root,
        transport=observer,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
