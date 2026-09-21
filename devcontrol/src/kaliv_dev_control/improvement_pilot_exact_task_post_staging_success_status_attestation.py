"""ADR-DC-090 read-only post-staging success Deployment Status attestation.

Normalizes exactly one durable ADR-DC-088 success-status transaction or one
completed ADR-DC-089 write-free recovery into a fresh exact attestation. The
exact frozen ``success`` staging Deployment Status is observed twice through
ADR-DC-089's credential-bound GET-only observer before the attestation is
published.

This boundary performs no remote write and grants no Deployment Status,
Deployment, release, merge, review, production, or other mutation authority.
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
from . import improvement_pilot_exact_task_staging_success_status_authorization as auth_boundary
from . import improvement_pilot_exact_task_staging_success_status_recovery as recovery_boundary
from . import improvement_pilot_exact_task_staging_success_status_state_observation as state_boundary
from . import improvement_pilot_exact_task_staging_success_status_transaction as tx_boundary
from .improvement_pilot_exact_task_staging_success_status_recovery import (
    PilotExactTaskStagingSuccessStatusRecoveryReceipt,
)
from .improvement_pilot_exact_task_staging_success_status_transaction import (
    PilotExactTaskStagingSuccessStatusTransactionReceipt,
)

PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-staging-success-status-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-staging-success-status-state-only"
)
PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_SCOPE = (
    "read-only-exact-post-staging-success-status-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPostStagingSuccessStatusAttestationError(ValueError):
    """Durable success completion or exact remote state is untrustworthy."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "post-success evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "durable success-status payload is missing"
        )
    return hashlib.sha256(payload).hexdigest()


def _read_canonical(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        return recovery_boundary._read_canonical_object(path, name=name)
    except Exception as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            f"{name} is unavailable or invalid"
        ) from exc


@dataclass(frozen=True, slots=True)
class _SuccessCompletionEvidence:
    source_kind: str
    source_receipt_sha256: str
    source_completed_at_utc: str
    transaction_lock_sha256: str
    recovery_lock_sha256: str | None
    source_final_remote_success_status_state_sha256: str
    success_deployment_status_id: int
    success_deployment_status_node_id_sha256: str
    source_action: str
    source_remote_write_performed: bool

    def __post_init__(self) -> None:
        if self.source_kind not in {"transaction", "recovery"}:
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "success completion source kind is unsupported"
            )
        for name in (
            "source_receipt_sha256",
            "transaction_lock_sha256",
            "source_final_remote_success_status_state_sha256",
            "success_deployment_status_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.recovery_lock_sha256 is not None:
            _hex64(self.recovery_lock_sha256, name="success_status_recovery_lock_sha256")
        if (
            isinstance(self.success_deployment_status_id, bool)
            or not isinstance(self.success_deployment_status_id, int)
            or self.success_deployment_status_id < 1
        ):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "success completion status ID is invalid"
            )
        if self.source_kind == "transaction":
            if (
                self.recovery_lock_sha256 is not None
                or self.source_action != "execute_exact_staging_success_status"
                or self.source_remote_write_performed is not True
            ):
                raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                    "normal success completion evidence is inconsistent"
                )
        elif (
            self.recovery_lock_sha256 is None
            or self.source_action != "finalize_existing_state"
            or self.source_remote_write_performed is not False
        ):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "recovered success completion evidence is inconsistent"
            )
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")


def _transaction_lock(
    *, authorization: Any, ledger: Any
) -> tuple[dict[str, Any], bytes]:
    _final, lock = ledger._paths(
        authorization.success_deployment_status_intent_sha256
    )
    raw, payload = _read_canonical(
        lock,
        name="ADR-DC-088 staging success-status transaction lock",
    )
    expected = {
        "schema": (
            "kaliv-rsi-dc-l16-exact-task-staging-success-status-"
            "transaction-lock/v1"
        ),
        "ledger_scope": (
            tx_boundary.PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_TRANSACTION_LEDGER_SCOPE
        ),
        "ledger_root_path_sha256": ledger.root_sha256,
        "success_status_transaction_key_sha256": (
            authorization.success_deployment_status_intent_sha256
        ),
        "success_status_authorization_sha256": authorization.sha256,
        "success_status_state_observation_sha256": (
            authorization.success_status_state_observation_sha256
        ),
        "staging_success_status_plan_sha256": (
            authorization.staging_success_status_plan_sha256
        ),
        "success_deployment_status_intent_sha256": (
            authorization.success_deployment_status_intent_sha256
        ),
        "remote_pre_write_success_status_state_sha256": (
            authorization.remote_success_status_state_sha256
        ),
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_id": authorization.deployment_id,
        "deployment_node_id_sha256": authorization.deployment_node_id_sha256,
        "current_deployment_status_id": authorization.current_deployment_status_id,
        "current_deployment_status_node_id_sha256": (
            authorization.current_deployment_status_node_id_sha256
        ),
        "success_deployment_status_state": (
            authorization.success_deployment_status_state
        ),
        "success_deployment_status_environment": (
            authorization.success_deployment_status_environment
        ),
        "success_deployment_status_description_sha256": (
            authorization.success_deployment_status_description_sha256
        ),
        "success_deployment_status_body_sha256": (
            authorization.success_deployment_status_body_sha256
        ),
    }
    if raw != expected:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "ADR-DC-088 transaction lock differs from exact success authority"
        )
    return raw, payload


def _validate_common_projection(*, receipt: Any, authorization: Any) -> None:
    expected = {
        "success_status_authorization_sha256": authorization.sha256,
        "success_deployment_status_intent_sha256": (
            authorization.success_deployment_status_intent_sha256
        ),
        "staging_success_status_plan_sha256": (
            authorization.staging_success_status_plan_sha256
        ),
        "staging_runtime_build_identity_sha256": (
            authorization.staging_runtime_build_identity_sha256
        ),
        "deployment_status_intent_sha256": authorization.deployment_status_intent_sha256,
        "status_transaction_lock_sha256": authorization.status_transaction_lock_sha256,
        "status_recovery_lock_sha256": authorization.status_recovery_lock_sha256,
        "publisher_credential_config_sha256": (
            authorization.publisher_credential_config_sha256
        ),
        "publisher_credential_path_sha256": (
            authorization.publisher_credential_path_sha256
        ),
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_environment": authorization.deployment_environment,
        "merge_commit_sha": authorization.merge_commit_sha,
        "deployment_id": authorization.deployment_id,
        "deployment_node_id_sha256": authorization.deployment_node_id_sha256,
        "current_deployment_status_id": authorization.current_deployment_status_id,
        "current_deployment_status_node_id_sha256": (
            authorization.current_deployment_status_node_id_sha256
        ),
        "success_deployment_status_state": (
            authorization.success_deployment_status_state
        ),
        "success_deployment_status_environment": (
            authorization.success_deployment_status_environment
        ),
        "success_deployment_status_description_sha256": (
            authorization.success_deployment_status_description_sha256
        ),
        "success_deployment_status_body_sha256": (
            authorization.success_deployment_status_body_sha256
        ),
    }
    if any(getattr(receipt, name, None) != value for name, value in expected.items()):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "success completion projection differs from exact ADR-DC-087 authorization"
        )


def _read_completion(
    *,
    authorization: Any,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
) -> _SuccessCompletionEvidence:
    key = authorization.success_deployment_status_intent_sha256
    tx_ledger = tx_boundary._PilotExactTaskStagingSuccessStatusTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    recovery_ledger = recovery_boundary._PilotExactTaskStagingSuccessStatusRecoveryLedger(
        _safe_ledger_root(recovery_ledger_root)
    )
    tx_final, _tx_lock = tx_ledger._paths(key)
    recovery_final, recovery_lock = recovery_ledger._paths(key)
    tx_present = tx_final.exists() or tx_final.is_symlink()
    recovery_present = recovery_final.exists() or recovery_final.is_symlink()
    recovery_lock_present = recovery_lock.exists() or recovery_lock.is_symlink()
    if tx_present == recovery_present:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "post-success completion source must be exactly one of ADR-DC-088 or ADR-DC-089"
        )
    if tx_present and recovery_lock_present:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "normal success completion collides with consumed recovery state"
        )
    if recovery_present and not recovery_lock_present:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "recovered success completion is missing its durable recovery lock"
        )
    _tx_lock_raw, tx_lock_payload = _transaction_lock(
        authorization=authorization,
        ledger=tx_ledger,
    )
    tx_lock_sha = _payload_sha256(tx_lock_payload)

    if tx_present:
        raw, payload = _read_canonical(
            tx_final,
            name="ADR-DC-088 final staging success-status transaction receipt",
        )
        try:
            receipt = PilotExactTaskStagingSuccessStatusTransactionReceipt.from_mapping(
                raw
            )
        except Exception as exc:
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "ADR-DC-088 final success-status receipt is invalid"
            ) from exc
        _validate_common_projection(receipt=receipt, authorization=authorization)
        if (
            receipt.canonical_json().encode("utf-8") != payload
            or receipt.success_status_transaction_ledger_root_path_sha256
            != tx_ledger.root_sha256
            or receipt.success_status_transaction_key_sha256 != key
            or receipt.success_status_transaction_lock_sha256 != tx_lock_sha
            or receipt.transaction_lock_committed is not True
            or receipt.success_status_authorization_authenticated is not True
            or receipt.pre_write_clear_revalidated is not True
            or receipt.post_lock_clear_revalidated is not True
            or receipt.success_deployment_status_created is not True
            or receipt.exact_post_write_state_verified is not True
            or receipt.success_deployment_status_authorized is not False
            or receipt.deployment_status_mutation_authorized is not False
            or receipt.remote_write_authorized is not False
            or receipt.production_activation_authorized is not False
            or receipt.nonce_reusable is not False
        ):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "ADR-DC-088 final receipt is not exact success completion"
            )
        return _SuccessCompletionEvidence(
            source_kind="transaction",
            source_receipt_sha256=receipt.sha256,
            source_completed_at_utc=receipt.created_at_utc,
            transaction_lock_sha256=tx_lock_sha,
            recovery_lock_sha256=None,
            source_final_remote_success_status_state_sha256=(
                receipt.post_write_remote_success_status_state_sha256
            ),
            success_deployment_status_id=receipt.success_deployment_status_id,
            success_deployment_status_node_id_sha256=(
                receipt.success_deployment_status_node_id_sha256
            ),
            source_action="execute_exact_staging_success_status",
            source_remote_write_performed=True,
        )

    raw, payload = _read_canonical(
        recovery_final,
        name="ADR-DC-089 final staging success-status recovery receipt",
    )
    recovery_lock_raw, recovery_lock_payload = _read_canonical(
        recovery_lock,
        name="ADR-DC-089 staging success-status recovery lock",
    )
    try:
        receipt = PilotExactTaskStagingSuccessStatusRecoveryReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "ADR-DC-089 final success-status recovery receipt is invalid"
        ) from exc
    _validate_common_projection(receipt=receipt, authorization=authorization)
    required_recovery_lock = {
        "schema": (
            "kaliv-rsi-dc-l16-exact-task-staging-success-status-recovery-lock/v1"
        ),
        "ledger_scope": (
            recovery_boundary.PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_LEDGER_SCOPE
        ),
        "ledger_root_path_sha256": recovery_ledger.root_sha256,
        "recovery_key_sha256": key,
        "recovery_state_fingerprint_sha256": receipt.recovery_state_fingerprint_sha256,
        "recovery_authorization_payload_sha256": (
            receipt.recovery_authorization_payload_sha256
        ),
        "success_status_authorization_sha256": authorization.sha256,
        "success_status_transaction_lock_sha256": tx_lock_sha,
        "action": "finalize_existing_state",
    }
    if any(
        recovery_lock_raw.get(name) != value
        for name, value in required_recovery_lock.items()
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "ADR-DC-089 recovery lock does not bind final recovery receipt"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(recovery_lock_raw.get(name), name=name)
    if set(recovery_lock_raw) != set(required_recovery_lock) | {
        "operator_signature_sha256",
        "reviewer_signature_sha256",
    }:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "ADR-DC-089 recovery lock carries unexpected fields"
        )
    if (
        receipt.canonical_json().encode("utf-8") != payload
        or receipt.recovery_ledger_root_path_sha256 != recovery_ledger.root_sha256
        or receipt.recovery_key_sha256 != key
        or receipt.success_status_transaction_lock_sha256 != tx_lock_sha
        or receipt.source_durable_phase != "lock_only"
        or receipt.source_remote_state_class != "exact_existing"
        or receipt.action_performed != "finalize_existing_state"
        or receipt.remote_write_performed is not False
        or receipt.durable_state_verified is not True
        or receipt.remote_state_verified is not True
        or receipt.recovery_authority_consumed is not True
        or receipt.exact_success_deployment_status_finalized is not True
        or receipt.recovery_completed is not True
        or receipt.deployment_status_mutation_authorized is not False
        or receipt.remote_write_authorized is not False
        or receipt.production_activation_authorized is not False
        or receipt.nonce_reusable is not False
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "ADR-DC-089 final receipt is not exact recovered success completion"
        )
    return _SuccessCompletionEvidence(
        source_kind="recovery",
        source_receipt_sha256=receipt.sha256,
        source_completed_at_utc=receipt.recovered_at_utc,
        transaction_lock_sha256=tx_lock_sha,
        recovery_lock_sha256=_payload_sha256(recovery_lock_payload),
        source_final_remote_success_status_state_sha256=(
            receipt.final_remote_success_status_state_sha256
        ),
        success_deployment_status_id=receipt.success_deployment_status_id,
        success_deployment_status_node_id_sha256=(
            receipt.success_deployment_status_node_id_sha256
        ),
        source_action="finalize_existing_state",
        source_remote_write_performed=False,
    )


def _durable_remote_state_sha256(
    *,
    authorization: Any,
    completion: _SuccessCompletionEvidence,
    observed: Any,
) -> str:
    if completion.source_kind == "recovery":
        return observed.sha256
    try:
        original = state_boundary._RemoteStagingSuccessStatusState(
            repository=observed.repository,
            repository_id=observed.repository_id,
            deployment_id=observed.deployment_id,
            deployment_node_id_sha256=observed.deployment_node_id_sha256,
            current_deployment_status_id=observed.current_deployment_status_id,
            current_deployment_status_node_id_sha256=(
                observed.current_deployment_status_node_id_sha256
            ),
            success_deployment_status_id=observed.success_deployment_status_id,
            success_deployment_status_node_id_sha256=(
                observed.success_deployment_status_node_id_sha256
            ),
            observed_success_status_state=observed.observed_success_status_state,
            observed_success_status_environment=(
                observed.observed_success_status_environment
            ),
            observed_success_status_description_sha256=(
                observed.observed_success_status_description_sha256
            ),
            observed_success_status_log_url=None,
            observed_success_status_environment_url=None,
            success_status_created_at_utc=observed.success_status_created_at_utc,
            success_status_updated_at_utc=observed.success_status_updated_at_utc,
            remote_state_class="exact-existing",
        )
    except Exception as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "fresh success state cannot reconstruct ADR-DC-088 final observation"
        ) from exc
    if (
        original.repository != authorization.repository
        or original.repository_id != authorization.repository_id
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "reconstructed ADR-DC-088 final observation identity changed"
        )
    return original.sha256


def _observe_exact_twice(
    *,
    authorization: Any,
    completion: _SuccessCompletionEvidence,
    transport: Any,
) -> tuple[str, str, str]:
    try:
        observed = recovery_boundary._double_observe(transport, authorization)
    except Exception as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "fresh staging success-status observation failed"
        ) from exc
    if (
        observed.remote_state_class != "exact_existing"
        or observed.success_deployment_status_id
        != completion.success_deployment_status_id
        or observed.success_deployment_status_node_id_sha256
        != completion.success_deployment_status_node_id_sha256
        or observed.observed_success_status_state
        != authorization.success_deployment_status_state
        or observed.observed_success_status_environment
        != authorization.success_deployment_status_environment
        or observed.observed_success_status_description_sha256
        != authorization.success_deployment_status_description_sha256
        or observed.success_status_created_at_utc is None
        or observed.success_status_updated_at_utc is None
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "GitHub state is not the exact completed staging success status"
        )
    if (
        _durable_remote_state_sha256(
            authorization=authorization,
            completion=completion,
            observed=observed,
        )
        != completion.source_final_remote_success_status_state_sha256
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "fresh success state differs from durable final remote-state evidence"
        )
    return (
        observed.sha256,
        observed.success_status_created_at_utc,
        observed.success_status_updated_at_utc,
    )


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

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
            receipt_ref,
            source_kind,
            source_receipt_sha256,
            observation_sha256,
        ) = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or receipt.success_status_completion_source != source_kind
            or receipt.success_status_completion_source_receipt_sha256
            != source_receipt_sha256
            or receipt.remote_success_status_observation_sha256 != observation_sha256
        ):
            return None
        return MappingProxyType(
            {
                "success_status_completion_source": source_kind,
                "success_status_completion_source_receipt_sha256": (
                    source_receipt_sha256
                ),
                "remote_success_status_observation_sha256": observation_sha256,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_post_staging_success_status_attestation_authenticated,
    _get_live_post_staging_success_status_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostStagingSuccessStatusAttestationReceipt:
    success_status_completion_source_receipt_sha256: str
    success_status_authorization_sha256: str
    success_status_state_observation_sha256: str
    staging_success_status_plan_sha256: str
    staging_runtime_build_identity_sha256: str
    success_deployment_status_intent_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    success_status_transaction_lock_sha256: str
    success_status_recovery_lock_sha256: str | None
    source_final_remote_success_status_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_success_status_observation_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_state: str
    success_deployment_status_environment: str
    success_deployment_status_description_sha256: str
    success_deployment_status_body_sha256: str
    success_deployment_status_id: int
    success_deployment_status_node_id_sha256: str
    success_status_created_at_utc: str
    success_status_updated_at_utc: str
    success_status_completion_source: str
    success_status_source_action: str
    success_status_source_remote_write_performed: bool
    source_completed_at_utc: str
    attested_at_utc: str
    durable_completion_verified: bool = True
    exact_parent_deployment_verified: bool = True
    exact_current_status_verified: bool = True
    exact_success_status_verified: bool = True
    exact_success_status_identity_verified: bool = True
    exact_success_status_state_verified: bool = True
    exact_success_status_environment_verified: bool = True
    exact_success_status_description_verified: bool = True
    double_observation_matched: bool = True
    post_staging_success_status_verified: bool = True
    success_deployment_status_authorized: bool = False
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
    attestation_scope: str = PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_AUTHORITY
            or self.attestation_scope
            != PILOT_EXACT_TASK_POST_STAGING_SUCCESS_STATUS_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "post-success attestation identity is unsupported"
            )
        for name in (
            "success_status_completion_source_receipt_sha256",
            "success_status_authorization_sha256",
            "success_status_state_observation_sha256",
            "staging_success_status_plan_sha256",
            "staging_runtime_build_identity_sha256",
            "success_deployment_status_intent_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "success_status_transaction_lock_sha256",
            "source_final_remote_success_status_state_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_success_status_observation_sha256",
            "deployment_node_id_sha256",
            "current_deployment_status_node_id_sha256",
            "success_deployment_status_description_sha256",
            "success_deployment_status_body_sha256",
            "success_deployment_status_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "status_recovery_lock_sha256",
            "success_status_recovery_lock_sha256",
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
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.current_deployment_status_id, bool)
            or not isinstance(self.current_deployment_status_id, int)
            or self.current_deployment_status_id < 1
            or isinstance(self.success_deployment_status_id, bool)
            or not isinstance(self.success_deployment_status_id, int)
            or self.success_deployment_status_id < 1
            or self.success_deployment_status_id == self.current_deployment_status_id
            or self.success_deployment_status_state != "success"
            or self.success_deployment_status_environment != "staging"
            or self.success_status_completion_source not in {"transaction", "recovery"}
        ):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "post-success attestation projection is invalid"
            )
        if self.success_status_completion_source == "transaction":
            if (
                self.success_status_recovery_lock_sha256 is not None
                or self.success_status_source_action
                != "execute_exact_staging_success_status"
                or self.success_status_source_remote_write_performed is not True
            ):
                raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                    "normal success completion source is inconsistent"
                )
        elif (
            self.success_status_recovery_lock_sha256 is None
            or self.success_status_source_action != "finalize_existing_state"
            or self.success_status_source_remote_write_performed is not False
        ):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "recovered success completion source is inconsistent"
            )
        created = _utc(
            self.success_status_created_at_utc,
            name="success_status_created_at_utc",
        )
        updated = _utc(
            self.success_status_updated_at_utc,
            name="success_status_updated_at_utc",
        )
        source_time = _utc(
            self.source_completed_at_utc,
            name="source_completed_at_utc",
        )
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if updated < created or attested < source_time or attested < updated:
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "post-success attestation timestamps are invalid"
            )
        required_true = (
            "durable_completion_verified",
            "exact_parent_deployment_verified",
            "exact_current_status_verified",
            "exact_success_status_verified",
            "exact_success_status_identity_verified",
            "exact_success_status_state_verified",
            "exact_success_status_environment_verified",
            "exact_success_status_description_verified",
            "double_observation_matched",
            "post_staging_success_status_verified",
        )
        forced_false = (
            "success_deployment_status_authorized",
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "post-success attestation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "post-success attestation retains forbidden mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_post_staging_success_status_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "post-success attestation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_post_staging_success_status(
    *,
    success_deployment_status_intent_sha256: str,
    success_status_transaction_ledger_root: Path,
    success_status_recovery_ledger_root: Path,
    success_status_authorization_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskPostStagingSuccessStatusAttestationReceipt:
    key = _hex64(
        success_deployment_status_intent_sha256,
        name="success_deployment_status_intent_sha256",
    )
    try:
        authorization = recovery_boundary._load_durable_authorization(
            key,
            _safe_ledger_root(success_status_authorization_ledger_root),
        )
    except Exception as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "durable ADR-DC-087 authorization could not be reconstructed"
        ) from exc
    completion = _read_completion(
        authorization=authorization,
        transaction_ledger_root=success_status_transaction_ledger_root,
        recovery_ledger_root=success_status_recovery_ledger_root,
    )
    observed_sha, created_at, updated_at = _observe_exact_twice(
        authorization=authorization,
        completion=completion,
        transport=transport,
    )
    attested_at = now_provider()
    if (
        _utc(attested_at, name="attested_at_utc")
        < _utc(completion.source_completed_at_utc, name="source_completed_at_utc")
        or _utc(attested_at, name="attested_at_utc")
        < _utc(updated_at, name="success_status_updated_at_utc")
    ):
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "system clock moved backwards before post-success attestation"
        )
    receipt = PilotExactTaskPostStagingSuccessStatusAttestationReceipt(
        success_status_completion_source_receipt_sha256=(
            completion.source_receipt_sha256
        ),
        success_status_authorization_sha256=authorization.sha256,
        success_status_state_observation_sha256=(
            authorization.success_status_state_observation_sha256
        ),
        staging_success_status_plan_sha256=(
            authorization.staging_success_status_plan_sha256
        ),
        staging_runtime_build_identity_sha256=(
            authorization.staging_runtime_build_identity_sha256
        ),
        success_deployment_status_intent_sha256=(
            authorization.success_deployment_status_intent_sha256
        ),
        deployment_status_intent_sha256=authorization.deployment_status_intent_sha256,
        status_transaction_lock_sha256=authorization.status_transaction_lock_sha256,
        status_recovery_lock_sha256=authorization.status_recovery_lock_sha256,
        success_status_transaction_lock_sha256=completion.transaction_lock_sha256,
        success_status_recovery_lock_sha256=completion.recovery_lock_sha256,
        source_final_remote_success_status_state_sha256=(
            completion.source_final_remote_success_status_state_sha256
        ),
        publisher_credential_config_sha256=(
            authorization.publisher_credential_config_sha256
        ),
        publisher_credential_path_sha256=(
            authorization.publisher_credential_path_sha256
        ),
        remote_success_status_observation_sha256=observed_sha,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        deployment_environment=authorization.deployment_environment,
        merge_commit_sha=authorization.merge_commit_sha,
        deployment_id=authorization.deployment_id,
        deployment_node_id_sha256=authorization.deployment_node_id_sha256,
        current_deployment_status_id=authorization.current_deployment_status_id,
        current_deployment_status_node_id_sha256=(
            authorization.current_deployment_status_node_id_sha256
        ),
        success_deployment_status_state=authorization.success_deployment_status_state,
        success_deployment_status_environment=(
            authorization.success_deployment_status_environment
        ),
        success_deployment_status_description_sha256=(
            authorization.success_deployment_status_description_sha256
        ),
        success_deployment_status_body_sha256=(
            authorization.success_deployment_status_body_sha256
        ),
        success_deployment_status_id=completion.success_deployment_status_id,
        success_deployment_status_node_id_sha256=(
            completion.success_deployment_status_node_id_sha256
        ),
        success_status_created_at_utc=created_at,
        success_status_updated_at_utc=updated_at,
        success_status_completion_source=completion.source_kind,
        success_status_source_action=completion.source_action,
        success_status_source_remote_write_performed=(
            completion.source_remote_write_performed
        ),
        source_completed_at_utc=completion.source_completed_at_utc,
        attested_at_utc=attested_at,
    )
    _mark_post_staging_success_status_attestation_authenticated(
        receipt,
        source_kind=completion.source_kind,
        source_receipt_sha256=completion.source_receipt_sha256,
        observation_sha256=observed_sha,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "post-success attestation lost live provenance"
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
            raise PilotExactTaskPostStagingSuccessStatusAttestationError(
                "post-success attestation platform is unsupported"
            )
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        observer = recovery_boundary._GitHubStagingSuccessStatusRecoveryTransport(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return transaction_root, recovery_root, authorization_root, observer
    except PilotExactTaskPostStagingSuccessStatusAttestationError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskPostStagingSuccessStatusAttestationError(
            "post-success attestation runtime is not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_post_staging_success_status(
    success_deployment_status_intent_sha256: str,
) -> PilotExactTaskPostStagingSuccessStatusAttestationReceipt:
    """Attest one completed exact staging success Deployment Status without writes."""
    transaction_root, recovery_root, authorization_root, observer = (
        _canonical_runtime()
    )
    return _attest_verified_pilot_exact_task_post_staging_success_status(
        success_deployment_status_intent_sha256=(
            success_deployment_status_intent_sha256
        ),
        success_status_transaction_ledger_root=transaction_root,
        success_status_recovery_ledger_root=recovery_root,
        success_status_authorization_ledger_root=authorization_root,
        transport=observer,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
