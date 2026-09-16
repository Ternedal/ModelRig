"""ADR-DC-076 read-only exact post-staging Deployment attestation.

Normalizes exactly one completed ADR-DC-074 staging Deployment transaction or
one completed ADR-DC-075 recovery into a restart-safe exact Deployment
attestation. Durable completion evidence is reconstructed first, then the exact
staging Deployment is observed twice through a credential-bound GET-only
observer.

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
from . import improvement_pilot_exact_task_staging_deployment_authorization as auth_boundary
from . import improvement_pilot_exact_task_staging_deployment_recovery as recovery_boundary
from . import improvement_pilot_exact_task_staging_deployment_transaction as tx_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_staging_deployment_recovery import (
    PilotExactTaskStagingDeploymentRecoveryReceipt,
)
from .improvement_pilot_exact_task_staging_deployment_transaction import (
    PilotExactTaskStagingDeploymentTransactionReceipt,
)

PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-staging-deployment-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-staging-deployment-state-only"
)
PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_SCOPE = (
    "read-only-exact-post-staging-deployment-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPostStagingDeploymentAttestationError(ValueError):
    """Durable deployment completion or exact remote state is untrustworthy."""


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
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "post-staging deployment evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPostStagingDeploymentAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostStagingDeploymentAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "durable deployment payload is missing"
        )
    return hashlib.sha256(payload).hexdigest()


def _read_canonical(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        return recovery_boundary._read_canonical_object(path, name=name)
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            f"{name} is unavailable or invalid"
        ) from exc


@dataclass(frozen=True, slots=True)
class _DeploymentCompletionEvidence:
    source_kind: str
    source_receipt_sha256: str
    source_completed_at_utc: str
    transaction_lock_sha256: str
    recovery_lock_sha256: str | None
    source_final_remote_deployment_state_sha256: str
    deployment_id: int
    deployment_node_id_sha256: str
    source_action: str
    source_remote_write_performed: bool

    def __post_init__(self) -> None:
        if self.source_kind not in {"transaction", "recovery"}:
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "deployment completion source kind is unsupported"
            )
        for name in (
            "source_receipt_sha256",
            "transaction_lock_sha256",
            "source_final_remote_deployment_state_sha256",
            "deployment_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.recovery_lock_sha256 is not None:
            _hex64(self.recovery_lock_sha256, name="recovery_lock_sha256")
        if (
            isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
        ):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "deployment completion Deployment ID is invalid"
            )
        if self.source_kind == "transaction":
            if (
                self.recovery_lock_sha256 is not None
                or self.source_action != "execute_exact_staging_deployment"
                or self.source_remote_write_performed is not True
            ):
                raise PilotExactTaskPostStagingDeploymentAttestationError(
                    "normal deployment completion evidence is inconsistent"
                )
        elif (
            self.recovery_lock_sha256 is None
            or self.source_action != "finalize_existing_state"
            or self.source_remote_write_performed is not False
        ):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "recovered deployment completion evidence is inconsistent"
            )
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")


def _transaction_lock_payload(*, authorization: Any, ledger: Any) -> bytes:
    final, lock = ledger._paths(authorization.execution_nonce_sha256)
    del final
    raw, payload = _read_canonical(
        lock,
        name="ADR-DC-074 staging Deployment transaction lock",
    )
    expected = {
        "schema": "kaliv-rsi-dc-l16-exact-task-staging-deployment-transaction-lock/v1",
        "ledger_scope": tx_boundary.PILOT_EXACT_TASK_STAGING_DEPLOYMENT_TRANSACTION_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "deployment_transaction_key_sha256": authorization.execution_nonce_sha256,
        "deployment_authorization_sha256": authorization.sha256,
        "deployment_state_observation_sha256": authorization.deployment_state_observation_sha256,
        "staging_deployment_plan_sha256": authorization.staging_deployment_plan_sha256,
        "deployment_intent_sha256": authorization.deployment_intent_sha256,
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_environment": authorization.deployment_environment,
        "deployment_ref": authorization.deployment_ref,
        "deployment_task": authorization.deployment_task,
        "merge_commit_sha": authorization.merge_commit_sha,
        "deployment_payload_sha256": authorization.deployment_payload_sha256,
        "deployment_description_sha256": authorization.deployment_description_sha256,
    }
    if raw != expected:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "ADR-DC-074 transaction lock differs from exact deployment authority"
        )
    return payload


def _validate_common_projection(*, receipt: Any, authorization: Any) -> None:
    expected = {
        "deployment_authorization_sha256": authorization.sha256,
        "deployment_intent_sha256": authorization.deployment_intent_sha256,
        "execution_nonce_sha256": authorization.execution_nonce_sha256,
        "publisher_credential_config_sha256": authorization.publisher_credential_config_sha256,
        "publisher_credential_path_sha256": authorization.publisher_credential_path_sha256,
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_environment": authorization.deployment_environment,
        "merge_commit_sha": authorization.merge_commit_sha,
        "deployment_ref": authorization.deployment_ref,
        "deployment_task": authorization.deployment_task,
        "deployment_payload_sha256": authorization.deployment_payload_sha256,
        "deployment_description_sha256": authorization.deployment_description_sha256,
    }
    if any(getattr(receipt, name, None) != value for name, value in expected.items()):
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "deployment completion projection differs from exact authorization"
        )


def _read_completion(
    *,
    authorization: Any,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
) -> _DeploymentCompletionEvidence:
    key = authorization.execution_nonce_sha256
    tx_ledger = tx_boundary._PilotExactTaskStagingDeploymentTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    recovery_ledger = recovery_boundary._PilotExactTaskStagingDeploymentRecoveryLedger(
        _safe_ledger_root(recovery_ledger_root)
    )
    tx_final, _tx_lock = tx_ledger._paths(key)
    recovery_final, recovery_lock = recovery_ledger._paths(key)
    tx_present = tx_final.exists() or tx_final.is_symlink()
    recovery_present = recovery_final.exists() or recovery_final.is_symlink()
    if tx_present == recovery_present:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "post-staging completion source must be exactly one of ADR-DC-074 or ADR-DC-075"
        )
    tx_lock_payload = _transaction_lock_payload(
        authorization=authorization,
        ledger=tx_ledger,
    )
    tx_lock_sha = _payload_sha256(tx_lock_payload)

    if tx_present:
        raw, payload = _read_canonical(
            tx_final,
            name="ADR-DC-074 final staging Deployment transaction receipt",
        )
        try:
            receipt = PilotExactTaskStagingDeploymentTransactionReceipt.from_mapping(raw)
        except Exception as exc:
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "ADR-DC-074 final staging Deployment receipt is invalid"
            ) from exc
        _validate_common_projection(receipt=receipt, authorization=authorization)
        if (
            receipt.canonical_json().encode("utf-8") != payload
            or receipt.deployment_transaction_ledger_root_path_sha256 != tx_ledger.root_sha256
            or receipt.deployment_transaction_key_sha256 != key
            or receipt.deployment_transaction_lock_sha256 != tx_lock_sha
            or receipt.deployment_state_observation_sha256
            != authorization.deployment_state_observation_sha256
            or receipt.staging_deployment_plan_sha256
            != authorization.staging_deployment_plan_sha256
            or receipt.transaction_lock_committed is not True
            or receipt.deployment_authorization_authenticated is not True
            or receipt.pre_write_clear_revalidated is not True
            or receipt.post_lock_clear_revalidated is not True
            or receipt.deployment_created is not True
            or receipt.exact_post_write_state_verified is not True
            or receipt.deployment_status_mutation_authorized is not False
            or receipt.deployment_mutation_authorized is not False
            or receipt.deploy_authorized is not False
            or receipt.remote_write_authorized is not False
            or receipt.production_activation_authorized is not False
            or receipt.nonce_reusable is not False
        ):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "ADR-DC-074 final receipt is not exact deployment completion"
            )
        return _DeploymentCompletionEvidence(
            source_kind="transaction",
            source_receipt_sha256=receipt.sha256,
            source_completed_at_utc=receipt.created_at_utc,
            transaction_lock_sha256=tx_lock_sha,
            recovery_lock_sha256=None,
            source_final_remote_deployment_state_sha256=(
                receipt.post_write_remote_state_sha256
            ),
            deployment_id=receipt.deployment_id,
            deployment_node_id_sha256=receipt.deployment_node_id_sha256,
            source_action="execute_exact_staging_deployment",
            source_remote_write_performed=True,
        )

    raw, payload = _read_canonical(
        recovery_final,
        name="ADR-DC-075 final staging Deployment recovery receipt",
    )
    recovery_lock_raw, recovery_lock_payload = _read_canonical(
        recovery_lock,
        name="ADR-DC-075 staging Deployment recovery lock",
    )
    try:
        receipt = PilotExactTaskStagingDeploymentRecoveryReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "ADR-DC-075 final staging Deployment recovery receipt is invalid"
        ) from exc
    _validate_common_projection(receipt=receipt, authorization=authorization)
    expected_recovery_lock = {
        "schema": "kaliv-rsi-dc-l16-exact-task-staging-deployment-recovery-lock/v1",
        "ledger_scope": recovery_boundary.PILOT_EXACT_TASK_STAGING_DEPLOYMENT_RECOVERY_LEDGER_SCOPE,
        "ledger_root_path_sha256": recovery_ledger.root_sha256,
        "recovery_key_sha256": key,
        "recovery_state_fingerprint_sha256": receipt.recovery_state_fingerprint_sha256,
        "recovery_authorization_payload_sha256": receipt.recovery_authorization_payload_sha256,
        "deployment_authorization_sha256": authorization.sha256,
        "action": "finalize_existing_state",
    }
    if any(recovery_lock_raw.get(name) != value for name, value in expected_recovery_lock.items()):
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "ADR-DC-075 recovery lock does not bind final recovery receipt"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(recovery_lock_raw.get(name), name=name)
    if set(recovery_lock_raw) != set(expected_recovery_lock) | {
        "operator_signature_sha256",
        "reviewer_signature_sha256",
    }:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "ADR-DC-075 recovery lock carries unexpected fields"
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
        or receipt.exact_staging_deployment_finalized is not True
        or receipt.recovery_completed is not True
        or receipt.deployment_status_mutation_authorized is not False
        or receipt.deployment_mutation_authorized is not False
        or receipt.deploy_authorized is not False
        or receipt.remote_write_authorized is not False
        or receipt.production_activation_authorized is not False
        or receipt.nonce_reusable is not False
    ):
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "ADR-DC-075 final receipt is not exact recovered deployment completion"
        )
    return _DeploymentCompletionEvidence(
        source_kind="recovery",
        source_receipt_sha256=receipt.sha256,
        source_completed_at_utc=receipt.recovered_at_utc,
        transaction_lock_sha256=tx_lock_sha,
        recovery_lock_sha256=_payload_sha256(recovery_lock_payload),
        source_final_remote_deployment_state_sha256=(
            receipt.final_remote_deployment_state_sha256
        ),
        deployment_id=receipt.deployment_id,
        deployment_node_id_sha256=receipt.deployment_node_id_sha256,
        source_action="finalize_existing_state",
        source_remote_write_performed=False,
    )


def _normalize_remote_state(
    *,
    value: Any,
    authorization: Any,
    completion: _DeploymentCompletionEvidence,
) -> dict[str, Any]:
    if type(value) is not recovery_boundary._DeploymentRecoveryRemoteState:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "post-staging observer returned invalid state"
        )
    if (
        value.repository != authorization.repository
        or value.repository_id != authorization.repository_id
        or value.remote_state_class != "exact_existing"
        or value.deployment_state != "exact"
        or value.deployment_id != completion.deployment_id
        or value.deployment_node_id_sha256 != completion.deployment_node_id_sha256
        or value.deployment_sha != authorization.merge_commit_sha
        or value.observed_payload_sha256 != authorization.deployment_payload_sha256
        or value.observed_description_sha256
        != authorization.deployment_description_sha256
    ):
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "GitHub state is not exact completed staging Deployment"
        )
    return {
        "repository": value.repository,
        "repository_id": value.repository_id,
        "deployment_environment": "staging",
        "deployment_state": "exact",
        "deployment_id": completion.deployment_id,
        "deployment_node_id_sha256": completion.deployment_node_id_sha256,
        "merge_commit_sha": authorization.merge_commit_sha,
        "deployment_identity": authorization.deployment_identity,
        "deployment_ref": authorization.deployment_ref,
        "deployment_task": authorization.deployment_task,
        "deployment_payload_sha256": authorization.deployment_payload_sha256,
        "deployment_description_sha256": authorization.deployment_description_sha256,
        "transient_environment": False,
        "production_environment": False,
    }


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
        pid, digest, ref, source_kind, source_receipt_sha256, observation_sha256 = entry
        if (
            pid != os.getpid()
            or ref() is not receipt
            or receipt.sha256 != digest
            or receipt.completion_source != source_kind
            or receipt.completion_source_receipt_sha256 != source_receipt_sha256
            or receipt.remote_observation_sha256 != observation_sha256
        ):
            return None
        return MappingProxyType({
            "completion_source": source_kind,
            "completion_source_receipt_sha256": source_receipt_sha256,
            "remote_observation_sha256": observation_sha256,
        })

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_post_staging_deployment_attestation_authenticated,
    _get_live_post_staging_deployment_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostStagingDeploymentAttestationReceipt:
    completion_source_receipt_sha256: str
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
    transaction_lock_sha256: str
    recovery_lock_sha256: str | None
    source_final_remote_deployment_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_observation_sha256: str
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
    completion_source: str
    source_action: str
    source_remote_write_performed: bool
    source_completed_at_utc: str
    attested_at_utc: str
    durable_completion_verified: bool = True
    exact_remote_deployment_verified: bool = True
    exact_merge_commit_verified: bool = True
    exact_payload_verified: bool = True
    exact_description_verified: bool = True
    double_observation_matched: bool = True
    post_staging_deployment_verified: bool = True
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
    attestation_scope: str = PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_AUTHORITY
            or self.attestation_scope
            != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "post-staging deployment attestation identity is unsupported"
            )
        for name in (
            "completion_source_receipt_sha256",
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
            "transaction_lock_sha256",
            "source_final_remote_deployment_state_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_observation_sha256",
            "deployment_payload_sha256",
            "deployment_description_sha256",
            "deployment_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.recovery_lock_sha256 is not None:
            _hex64(self.recovery_lock_sha256, name="recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or not self.repository_id.isdigit()
            or self.repository_id.startswith("0")
            or self.deployment_environment != "staging"
            or self.deployment_task != "deploy"
            or self.deployment_identity
            != f"modelrig-staging-{self.merge_commit_sha}"
            or self.deployment_ref != f"modelrig-rsi-{self.merge_commit_sha}"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or self.completion_source not in {"transaction", "recovery"}
            or self.source_action
            not in {"execute_exact_staging_deployment", "finalize_existing_state"}
            or not isinstance(self.source_remote_write_performed, bool)
        ):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "post-staging deployment deterministic identity is invalid"
            )
        if self.completion_source == "transaction":
            if (
                self.source_action != "execute_exact_staging_deployment"
                or self.source_remote_write_performed is not True
                or self.recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskPostStagingDeploymentAttestationError(
                    "normal post-staging completion source is inconsistent"
                )
        elif (
            self.source_action != "finalize_existing_state"
            or self.source_remote_write_performed is not False
            or self.recovery_lock_sha256 is None
        ):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "recovered post-staging completion source is inconsistent"
            )
        source_time = _utc(self.source_completed_at_utc, name="source_completed_at_utc")
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if attested < source_time:
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "post-staging deployment attestation predates completion"
            )
        required_true = (
            "durable_completion_verified",
            "exact_remote_deployment_verified",
            "exact_merge_commit_verified",
            "exact_payload_verified",
            "exact_description_verified",
            "double_observation_matched",
            "post_staging_deployment_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "post-staging deployment attestation evidence is incomplete"
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
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "read-only post-staging attestation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_post_staging_deployment_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "post-staging deployment attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_post_staging_deployment(
    *,
    execution_nonce_sha256: str,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
    deployment_authorization_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskPostStagingDeploymentAttestationReceipt:
    key = _hex64(execution_nonce_sha256, name="execution_nonce_sha256")
    try:
        authorization = recovery_boundary._load_durable_authorization(
            key,
            deployment_authorization_ledger_root,
        )
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "durable exact staging Deployment authorization reconstruction failed"
        ) from exc
    completion = _read_completion(
        authorization=authorization,
        transaction_ledger_root=transaction_ledger_root,
        recovery_ledger_root=recovery_ledger_root,
    )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "read-only post-staging GitHub observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != authorization.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != authorization.publisher_credential_path_sha256
    ):
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "post-staging observer credential identity differs from ADR-DC-073"
        )
    try:
        first = _normalize_remote_state(
            value=transport.observe(authorization),
            authorization=authorization,
            completion=completion,
        )
        second = _normalize_remote_state(
            value=transport.observe(authorization),
            authorization=authorization,
            completion=completion,
        )
    except PilotExactTaskPostStagingDeploymentAttestationError:
        raise
    except Exception as exc:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "post-staging GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "GitHub post-staging Deployment changed between observations"
        )
    observation_sha = hashlib.sha256(_canonical(first).encode("utf-8")).hexdigest()
    attested_at = now_provider()
    if _utc(attested_at, name="attested_at_utc") < _utc(
        completion.source_completed_at_utc,
        name="source_completed_at_utc",
    ):
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "system clock moved backwards after staging Deployment completion"
        )
    receipt = PilotExactTaskPostStagingDeploymentAttestationReceipt(
        completion_source_receipt_sha256=completion.source_receipt_sha256,
        deployment_authorization_sha256=authorization.sha256,
        deployment_state_observation_sha256=authorization.deployment_state_observation_sha256,
        staging_deployment_plan_sha256=authorization.staging_deployment_plan_sha256,
        deploy_readiness_evaluation_sha256=authorization.deploy_readiness_evaluation_sha256,
        post_release_attestation_sha256=authorization.post_release_attestation_sha256,
        deployment_intent_sha256=authorization.deployment_intent_sha256,
        execution_nonce_sha256=key,
        development_task_sha256=authorization.development_task_sha256,
        candidate_patch_sha256=authorization.candidate_patch_sha256,
        pr_intent_sha256=authorization.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=(
            authorization.upstream_merge_transaction_lock_sha256
        ),
        release_transaction_lock_sha256=authorization.release_transaction_lock_sha256,
        transaction_lock_sha256=completion.transaction_lock_sha256,
        recovery_lock_sha256=completion.recovery_lock_sha256,
        source_final_remote_deployment_state_sha256=(
            completion.source_final_remote_deployment_state_sha256
        ),
        publisher_credential_config_sha256=authorization.publisher_credential_config_sha256,
        publisher_credential_path_sha256=authorization.publisher_credential_path_sha256,
        remote_observation_sha256=observation_sha,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        deployment_environment=authorization.deployment_environment,
        merge_commit_sha=authorization.merge_commit_sha,
        deployment_identity=authorization.deployment_identity,
        deployment_ref=authorization.deployment_ref,
        deployment_task=authorization.deployment_task,
        deployment_payload_sha256=authorization.deployment_payload_sha256,
        deployment_description_sha256=authorization.deployment_description_sha256,
        deployment_id=completion.deployment_id,
        deployment_node_id_sha256=completion.deployment_node_id_sha256,
        completion_source=completion.source_kind,
        source_action=completion.source_action,
        source_remote_write_performed=completion.source_remote_write_performed,
        source_completed_at_utc=completion.source_completed_at_utc,
        attested_at_utc=attested_at,
    )
    _mark_post_staging_deployment_attestation_authenticated(
        receipt,
        source_kind=completion.source_kind,
        source_receipt_sha256=completion.source_receipt_sha256,
        observation_sha256=observation_sha,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "post-staging deployment attestation lost live provenance"
        )
    return receipt


def _canonical_roots() -> tuple[Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            roots = (
                tx_boundary._POSIX_LEDGER,
                recovery_boundary._POSIX_LEDGER,
                auth_boundary._POSIX_LEDGER,
            )
        elif os.name == "nt":
            roots = (
                tx_boundary._WINDOWS_LEDGER,
                recovery_boundary._WINDOWS_LEDGER,
                auth_boundary._WINDOWS_LEDGER,
            )
        else:
            raise PilotExactTaskPostStagingDeploymentAttestationError(
                "post-staging deployment attestation is unsupported on this platform"
            )
        return tuple(
            _require_host_controlled_ledger_root(Path(root)) for root in roots
        )
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "canonical post-staging deployment ledgers are not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_post_staging_deployment(
    execution_nonce_sha256: str,
) -> PilotExactTaskPostStagingDeploymentAttestationReceipt:
    """Read-only attest one exact durable staging Deployment completion."""
    try:
        tx_root, recovery_root, auth_root = _canonical_roots()
        credential, digest, path = publication_tx_boundary._canonical_credential()
        transport = recovery_boundary._GitHubStagingDeploymentRecoveryTransport(
            credential=credential,
            credential_config_sha256=digest,
            credential_path=path,
        )
        return _attest_verified_pilot_exact_task_post_staging_deployment(
            execution_nonce_sha256=execution_nonce_sha256,
            transaction_ledger_root=tx_root,
            recovery_ledger_root=recovery_root,
            deployment_authorization_ledger_root=auth_root,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPostStagingDeploymentAttestationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPostStagingDeploymentAttestationError(
            "host-controlled post-staging deployment attestation failed closed"
        ) from exc


__all__: list[str] = []
