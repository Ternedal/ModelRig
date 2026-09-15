"""ADR-DC-062 read-only exact post-merge attestation.

This boundary normalizes either one completed ADR-DC-060 merge transaction or
one completed ADR-DC-061 merge recovery into one exact, restart-safe durable
completion source. GitHub is then observed twice through ADR-DC-061's
credential-bound GET-only observer.

No merge, release, deploy, production activation, PR mutation or other remote
write authority is granted by this boundary.
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
from . import improvement_pilot_exact_task_merge_authorization as auth_boundary
from . import improvement_pilot_exact_task_merge_recovery as recovery_boundary
from . import improvement_pilot_exact_task_merge_transaction as tx_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_merge_recovery import (
    PilotExactTaskMergeRecoveryReceipt,
)
from .improvement_pilot_exact_task_merge_transaction import (
    PilotExactTaskMergeTransactionReceipt,
)

PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-merge-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-merge-state-only"
)
PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCOPE = (
    "read-only-exact-post-merge-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"


class PilotExactTaskPostMergeAttestationError(ValueError):
    """Durable merge completion or exact GitHub merged state is untrustworthy."""


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
        raise PilotExactTaskPostMergeAttestationError(
            "post-merge evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPostMergeAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostMergeAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostMergeAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostMergeAttestationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskPostMergeAttestationError(f"{name} is invalid")
    return value


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPostMergeAttestationError(
            "durable merge payload is missing"
        )
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _MergeCompletionEvidence:
    source_kind: str
    source_receipt_sha256: str
    source_completed_at_utc: str
    transaction_lock_sha256: str
    source_merged_marker_state_sha256: str
    source_merged_marker_present: bool
    source_merge_response_sha256: str | None
    source_final_remote_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    merge_commit_sha: str

    def __post_init__(self) -> None:
        if self.source_kind not in {"transaction", "recovery"}:
            raise PilotExactTaskPostMergeAttestationError(
                "merge completion source kind is unsupported"
            )
        for name in (
            "source_receipt_sha256",
            "transaction_lock_sha256",
            "source_merged_marker_state_sha256",
            "source_final_remote_state_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.source_merge_response_sha256 is not None:
            _hex64(
                self.source_merge_response_sha256,
                name="source_merge_response_sha256",
            )
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if not isinstance(self.source_merged_marker_present, bool):
            raise PilotExactTaskPostMergeAttestationError(
                "merged-marker presence is invalid"
            )
        if self.source_kind == "transaction" and (
            self.source_merged_marker_present is not True
            or self.source_merge_response_sha256 is None
        ):
            raise PilotExactTaskPostMergeAttestationError(
                "normal merge completion requires durable merged marker evidence"
            )
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")


def _read_canonical(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        return recovery_boundary._read_canonical_object(path, name=name)
    except Exception as exc:
        raise PilotExactTaskPostMergeAttestationError(
            f"{name} is unavailable or invalid"
        ) from exc


def _marker_state_sha(*, present: bool, payload: bytes | None = None) -> str:
    if present:
        if payload is None:
            raise PilotExactTaskPostMergeAttestationError(
                "present merged marker lacks payload"
            )
        value = {"present": True, "payload_sha256": _payload_sha256(payload)}
    else:
        value = {"present": False}
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_completion(
    *,
    key: str,
    authorization: Any,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
) -> _MergeCompletionEvidence:
    tx_ledger = tx_boundary._PilotExactTaskMergeTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    recovery_ledger = recovery_boundary._PilotExactTaskMergeRecoveryLedger(
        _safe_ledger_root(recovery_ledger_root)
    )
    tx_final, tx_lock, tx_merged = tx_ledger._paths(key)
    recovery_final, recovery_lock = recovery_ledger._paths(key)

    tx_final_present = tx_final.exists() or tx_final.is_symlink()
    recovery_final_present = recovery_final.exists() or recovery_final.is_symlink()
    if tx_final_present == recovery_final_present:
        raise PilotExactTaskPostMergeAttestationError(
            "post-merge completion source must be exactly one of ADR-DC-060 or ADR-DC-061"
        )

    lock_raw, lock_payload = _read_canonical(
        tx_lock, name="ADR-DC-060 merge transaction lock"
    )
    try:
        (
            _pre_state_sha,
            _fresh_readiness_sha,
            credential_config_sha,
            credential_path_sha,
        ) = recovery_boundary._validate_transaction_lock(
            lock_raw,
            payload=lock_payload,
            key=key,
            authorization=authorization,
            transaction_ledger_root_sha256=tx_ledger.root_sha256,
        )
    except Exception as exc:
        raise PilotExactTaskPostMergeAttestationError(
            "ADR-DC-060 transaction lock does not bind exact merge authority"
        ) from exc
    lock_sha = _payload_sha256(lock_payload)

    merged_present = tx_merged.exists() or tx_merged.is_symlink()
    marker_payload = None
    marker_merge_sha = None
    marker_response_sha = None
    marker_state_sha = _marker_state_sha(present=False)
    if merged_present:
        merged_raw, marker_payload = _read_canonical(
            tx_merged, name="ADR-DC-060 merged marker"
        )
        try:
            marker_merge_sha, marker_response_sha, _marker_time = (
                recovery_boundary._validate_merged_marker(
                    merged_raw,
                    key=key,
                    authorization=authorization,
                )
            )
        except Exception as exc:
            raise PilotExactTaskPostMergeAttestationError(
                "ADR-DC-060 merged marker is not exact"
            ) from exc
        marker_state_sha = _marker_state_sha(
            present=True, payload=marker_payload
        )

    if tx_final_present:
        if not merged_present:
            raise PilotExactTaskPostMergeAttestationError(
                "completed ADR-DC-060 transaction lacks merged marker"
            )
        raw, _payload = _read_canonical(
            tx_final, name="ADR-DC-060 final merge transaction receipt"
        )
        try:
            receipt = PilotExactTaskMergeTransactionReceipt.from_mapping(raw)
        except Exception as exc:
            raise PilotExactTaskPostMergeAttestationError(
                "ADR-DC-060 final merge receipt is invalid"
            ) from exc
        if (
            receipt.transaction_key_sha256 != key
            or receipt.execution_nonce_sha256 != key
            or receipt.merge_authorization_sha256 != authorization.sha256
            or receipt.merge_readiness_evaluation_sha256
            != authorization.merge_readiness_evaluation_sha256
            or receipt.merge_readiness_policy_sha256
            != authorization.merge_readiness_policy_sha256
            or receipt.merge_config_sha256 != authorization.merge_config_sha256
            or receipt.development_task_sha256 != authorization.development_task_sha256
            or receipt.candidate_patch_sha256 != authorization.candidate_patch_sha256
            or receipt.pr_intent_sha256 != authorization.pr_intent_sha256
            or receipt.repository != authorization.repository
            or receipt.repository_id != authorization.repository_id
            or receipt.base_branch != authorization.base_branch
            or receipt.authorized_base_sha != authorization.base_sha
            or receipt.head_branch != authorization.head_branch
            or receipt.head_sha != authorization.head_sha
            or receipt.pull_request_number != authorization.pull_request_number
            or receipt.pull_request_api_url != authorization.pull_request_api_url
            or receipt.pull_request_node_id_sha256
            != authorization.pull_request_node_id_sha256
            or receipt.merge_method != "squash"
            or receipt.publisher_credential_config_sha256 != credential_config_sha
            or receipt.publisher_credential_path_sha256 != credential_path_sha
            or receipt.merge_commit_sha != marker_merge_sha
            or receipt.merge_response_sha256 != marker_response_sha
            or receipt.merged is not True
            or receipt.exact_base_parent_verified is not True
            or receipt.merge_authorized is not False
            or receipt.remote_write_authorized is not False
            or receipt.release_authorized is not False
            or receipt.deploy_authorized is not False
            or receipt.production_activation_authorized is not False
            or receipt.nonce_reusable is not False
        ):
            raise PilotExactTaskPostMergeAttestationError(
                "ADR-DC-060 final receipt is not bound to exact merge authority"
            )
        return _MergeCompletionEvidence(
            source_kind="transaction",
            source_receipt_sha256=receipt.sha256,
            source_completed_at_utc=receipt.completed_at_utc,
            transaction_lock_sha256=lock_sha,
            source_merged_marker_state_sha256=marker_state_sha,
            source_merged_marker_present=True,
            source_merge_response_sha256=receipt.merge_response_sha256,
            source_final_remote_state_sha256=receipt.final_remote_state_sha256,
            publisher_credential_config_sha256=credential_config_sha,
            publisher_credential_path_sha256=credential_path_sha,
            merge_commit_sha=receipt.merge_commit_sha,
        )

    raw, _payload = _read_canonical(
        recovery_final, name="ADR-DC-061 final merge recovery receipt"
    )
    recovery_lock_raw, _recovery_lock_payload = _read_canonical(
        recovery_lock, name="ADR-DC-061 merge recovery lock"
    )
    try:
        receipt = PilotExactTaskMergeRecoveryReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskPostMergeAttestationError(
            "ADR-DC-061 final recovery receipt is invalid"
        ) from exc

    expected_recovery_lock = {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "recovery_key_sha256",
        "recovery_state_fingerprint_sha256",
        "recovery_authorization_payload_sha256",
        "merge_authorization_sha256",
        "merge_commit_sha",
        "operator_signature_sha256",
        "reviewer_signature_sha256",
    }
    if (
        set(recovery_lock_raw) != expected_recovery_lock
        or recovery_lock_raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-merge-recovery-lock/v1"
        or recovery_lock_raw.get("ledger_scope")
        != recovery_boundary.PILOT_EXACT_TASK_MERGE_RECOVERY_LEDGER_SCOPE
        or recovery_lock_raw.get("ledger_root_path_sha256")
        != recovery_ledger.root_sha256
        or recovery_lock_raw.get("recovery_key_sha256") != key
        or recovery_lock_raw.get("recovery_state_fingerprint_sha256")
        != receipt.recovery_state_fingerprint_sha256
        or recovery_lock_raw.get("recovery_authorization_payload_sha256")
        != receipt.recovery_authorization_payload_sha256
        or recovery_lock_raw.get("merge_authorization_sha256")
        != receipt.merge_authorization_sha256
        or recovery_lock_raw.get("merge_commit_sha") != receipt.merge_commit_sha
    ):
        raise PilotExactTaskPostMergeAttestationError(
            "ADR-DC-061 recovery lock does not bind final recovery receipt"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(recovery_lock_raw.get(name), name=name)

    if (
        receipt.recovery_key_sha256 != key
        or receipt.execution_nonce_sha256 != key
        or receipt.transaction_lock_sha256 != lock_sha
        or receipt.source_merged_marker_state_sha256 != marker_state_sha
        or receipt.source_merged_marker_present is not merged_present
        or receipt.merge_authorization_sha256 != authorization.sha256
        or receipt.merge_readiness_evaluation_sha256
        != authorization.merge_readiness_evaluation_sha256
        or receipt.merge_readiness_policy_sha256
        != authorization.merge_readiness_policy_sha256
        or receipt.merge_config_sha256 != authorization.merge_config_sha256
        or receipt.development_task_sha256 != authorization.development_task_sha256
        or receipt.candidate_patch_sha256 != authorization.candidate_patch_sha256
        or receipt.pr_intent_sha256 != authorization.pr_intent_sha256
        or receipt.repository != authorization.repository
        or receipt.repository_id != authorization.repository_id
        or receipt.base_branch != authorization.base_branch
        or receipt.authorized_base_sha != authorization.base_sha
        or receipt.head_branch != authorization.head_branch
        or receipt.head_sha != authorization.head_sha
        or receipt.pull_request_number != authorization.pull_request_number
        or receipt.pull_request_api_url != authorization.pull_request_api_url
        or receipt.pull_request_node_id_sha256
        != authorization.pull_request_node_id_sha256
        or receipt.merge_method != "squash"
        or receipt.merge_commit_sha == authorization.base_sha
        or receipt.merge_commit_sha == authorization.head_sha
        or receipt.exact_remote_merge_verified is not True
        or receipt.exact_base_parent_verified is not True
        or receipt.transaction_finalization_recovered is not True
        or receipt.merged is not True
        or receipt.merge_authorized is not False
        or receipt.remote_write_authorized is not False
        or receipt.release_authorized is not False
        or receipt.deploy_authorized is not False
        or receipt.production_activation_authorized is not False
        or receipt.nonce_reusable is not False
    ):
        raise PilotExactTaskPostMergeAttestationError(
            "ADR-DC-061 final receipt is not bound to exact merge authority"
        )
    if merged_present and (
        receipt.source_merge_response_sha256 != marker_response_sha
        or receipt.merge_commit_sha != marker_merge_sha
    ):
        raise PilotExactTaskPostMergeAttestationError(
            "ADR-DC-061 recovery disagrees with ADR-DC-060 merged marker"
        )
    if not merged_present and receipt.source_merge_response_sha256 is not None:
        raise PilotExactTaskPostMergeAttestationError(
            "lock-only recovery invented merge-response evidence"
        )
    return _MergeCompletionEvidence(
        source_kind="recovery",
        source_receipt_sha256=receipt.sha256,
        source_completed_at_utc=receipt.recovered_at_utc,
        transaction_lock_sha256=lock_sha,
        source_merged_marker_state_sha256=marker_state_sha,
        source_merged_marker_present=merged_present,
        source_merge_response_sha256=receipt.source_merge_response_sha256,
        source_final_remote_state_sha256=receipt.final_remote_state_sha256,
        publisher_credential_config_sha256=credential_config_sha,
        publisher_credential_path_sha256=credential_path_sha,
        merge_commit_sha=receipt.merge_commit_sha,
    )


def _normalize_remote_state(
    *,
    value: Any,
    authorization: Any,
    completion: _MergeCompletionEvidence,
) -> dict[str, Any]:
    if type(value) is not recovery_boundary._MergeRecoveryRemoteState:
        raise PilotExactTaskPostMergeAttestationError(
            "post-merge GitHub observer returned invalid state"
        )
    if (
        value.repository != authorization.repository
        or value.repository_id != authorization.repository_id
        or value.base_branch != authorization.base_branch
        or value.head_branch != authorization.head_branch
        or value.head_sha != authorization.head_sha
        or value.pull_request_number != authorization.pull_request_number
        or value.pull_request_api_url != authorization.pull_request_api_url
        or value.pull_request_node_id_sha256
        != authorization.pull_request_node_id_sha256
        or value.state != "closed"
        or value.draft is not False
        or value.merged is not True
        or value.maintainer_can_modify is not False
        or value.merge_commit_sha != completion.merge_commit_sha
        or value.base_ref_sha != completion.merge_commit_sha
        or value.merge_commit_parent_sha != authorization.base_sha
    ):
        raise PilotExactTaskPostMergeAttestationError(
            "GitHub state is not exact authorized completed squash merge"
        )
    return {
        "repository": value.repository,
        "repository_id": value.repository_id,
        "base_branch": value.base_branch,
        "base_ref_sha": value.base_ref_sha,
        "head_branch": value.head_branch,
        "head_sha": value.head_sha,
        "pull_request_number": value.pull_request_number,
        "pull_request_api_url": value.pull_request_api_url,
        "pull_request_node_id_sha256": value.pull_request_node_id_sha256,
        "state": "closed",
        "draft": False,
        "merged": True,
        "maintainer_can_modify": False,
        "merge_commit_sha": completion.merge_commit_sha,
        "merge_commit_parent_sha": authorization.base_sha,
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
        return MappingProxyType(
            {
                "completion_source": source_kind,
                "completion_source_receipt_sha256": source_receipt_sha256,
                "remote_observation_sha256": observation_sha256,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_post_merge_attestation_authenticated,
    _get_live_post_merge_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostMergeAttestationReceipt:
    completion_source_receipt_sha256: str
    merge_authorization_sha256: str
    merge_readiness_evaluation_sha256: str
    merge_readiness_policy_sha256: str
    merge_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    source_merged_marker_state_sha256: str
    source_merged_marker_present: bool
    source_merge_response_sha256: str | None
    source_final_remote_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_observation_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    authorized_base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    merge_method: str
    merge_commit_sha: str
    completion_source: str
    source_completed_at_utc: str
    attested_at_utc: str
    durable_completion_verified: bool = True
    exact_remote_merge_verified: bool = True
    exact_base_parent_verified: bool = True
    double_observation_matched: bool = True
    post_merge_verified: bool = True
    merge_authorized: bool = False
    remote_write_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    attestation_scope: str = PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_AUTHORITY
            or self.attestation_scope != PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge attestation identity is unsupported"
            )
        for name in (
            "completion_source_receipt_sha256",
            "merge_authorization_sha256",
            "merge_readiness_evaluation_sha256",
            "merge_readiness_policy_sha256",
            "merge_config_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "source_merged_marker_state_sha256",
            "source_final_remote_state_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_observation_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.source_merge_response_sha256 is not None:
            _hex64(
                self.source_merge_response_sha256,
                name="source_merge_response_sha256",
            )
        for name in ("authorized_base_sha", "head_sha", "merge_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
            or self.merge_method != "squash"
            or not isinstance(self.source_merged_marker_present, bool)
        ):
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge target/source identity is invalid"
            )
        if self.completion_source not in {"transaction", "recovery"}:
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge completion source is unsupported"
            )
        if self.completion_source == "transaction" and (
            self.source_merged_marker_present is not True
            or self.source_merge_response_sha256 is None
        ):
            raise PilotExactTaskPostMergeAttestationError(
                "normal merge completion lacks merged marker evidence"
            )
        source_time = _utc(
            self.source_completed_at_utc, name="source_completed_at_utc"
        )
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if attested < source_time:
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge attestation predates durable completion"
            )
        required_true = (
            "durable_completion_verified",
            "exact_remote_merge_verified",
            "exact_base_parent_verified",
            "double_observation_matched",
            "post_merge_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge attestation evidence is incomplete"
            )
        forced_false = (
            "merge_authorized",
            "remote_write_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostMergeAttestationError(
                "read-only post-merge attestation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_post_merge_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPostMergeAttestationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_post_merge(
    *,
    execution_nonce_sha256: str,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
    merge_authorization_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskPostMergeAttestationReceipt:
    key = _hex64(execution_nonce_sha256, name="execution_nonce_sha256")
    try:
        authorization, _authorization_payload = (
            recovery_boundary._load_durable_authorization(
                key=key,
                merge_authorization_ledger_root=merge_authorization_ledger_root,
            )
        )
    except Exception as exc:
        raise PilotExactTaskPostMergeAttestationError(
            "durable exact merge authorization reconstruction failed"
        ) from exc

    completion = _read_completion(
        key=key,
        authorization=authorization,
        transaction_ledger_root=transaction_ledger_root,
        recovery_ledger_root=recovery_ledger_root,
    )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskPostMergeAttestationError(
            "read-only post-merge GitHub observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != completion.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != completion.publisher_credential_path_sha256
    ):
        raise PilotExactTaskPostMergeAttestationError(
            "post-merge observer credential identity differs from ADR-DC-060 lock"
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
    except PilotExactTaskPostMergeAttestationError:
        raise
    except Exception as exc:
        raise PilotExactTaskPostMergeAttestationError(
            "post-merge GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskPostMergeAttestationError(
            "GitHub post-merge state changed between observations"
        )
    observation_sha = hashlib.sha256(
        _canonical(first).encode("utf-8")
    ).hexdigest()

    attested_at = now_provider()
    if _utc(attested_at, name="attested_at_utc") < _utc(
        completion.source_completed_at_utc, name="source_completed_at_utc"
    ):
        raise PilotExactTaskPostMergeAttestationError(
            "system clock moved backwards after merge completion"
        )

    receipt = PilotExactTaskPostMergeAttestationReceipt(
        completion_source_receipt_sha256=completion.source_receipt_sha256,
        merge_authorization_sha256=authorization.sha256,
        merge_readiness_evaluation_sha256=authorization.merge_readiness_evaluation_sha256,
        merge_readiness_policy_sha256=authorization.merge_readiness_policy_sha256,
        merge_config_sha256=authorization.merge_config_sha256,
        execution_nonce_sha256=key,
        development_task_sha256=authorization.development_task_sha256,
        candidate_patch_sha256=authorization.candidate_patch_sha256,
        pr_intent_sha256=authorization.pr_intent_sha256,
        transaction_lock_sha256=completion.transaction_lock_sha256,
        source_merged_marker_state_sha256=completion.source_merged_marker_state_sha256,
        source_merged_marker_present=completion.source_merged_marker_present,
        source_merge_response_sha256=completion.source_merge_response_sha256,
        source_final_remote_state_sha256=completion.source_final_remote_state_sha256,
        publisher_credential_config_sha256=completion.publisher_credential_config_sha256,
        publisher_credential_path_sha256=completion.publisher_credential_path_sha256,
        remote_observation_sha256=observation_sha,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        base_branch=authorization.base_branch,
        authorized_base_sha=authorization.base_sha,
        head_branch=authorization.head_branch,
        head_sha=authorization.head_sha,
        pull_request_number=authorization.pull_request_number,
        pull_request_api_url=authorization.pull_request_api_url,
        pull_request_node_id_sha256=authorization.pull_request_node_id_sha256,
        merge_method="squash",
        merge_commit_sha=completion.merge_commit_sha,
        completion_source=completion.source_kind,
        source_completed_at_utc=completion.source_completed_at_utc,
        attested_at_utc=attested_at,
    )
    _mark_post_merge_attestation_authenticated(
        receipt,
        source_kind=completion.source_kind,
        source_receipt_sha256=completion.source_receipt_sha256,
        observation_sha256=observation_sha,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostMergeAttestationError(
            "post-merge attestation lost live provenance"
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
            raise PilotExactTaskPostMergeAttestationError(
                "post-merge attestation is unsupported on this platform"
            )
        return tuple(
            _require_host_controlled_ledger_root(Path(root)) for root in roots
        )  # type: ignore[return-value]
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPostMergeAttestationError(
            "canonical post-merge ledgers are not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_post_merge(
    execution_nonce_sha256: str,
) -> PilotExactTaskPostMergeAttestationReceipt:
    """Read-only attest one exact durable merge completion."""
    try:
        tx_root, recovery_root, auth_root = _canonical_roots()
        credential, digest, path = publication_tx_boundary._canonical_credential()
        transport = recovery_boundary._GitHubMergeRecoveryObserver(
            credential=credential,
            credential_config_sha256=digest,
            credential_path=path,
        )
        return _attest_verified_pilot_exact_task_post_merge(
            execution_nonce_sha256=execution_nonce_sha256,
            transaction_ledger_root=tx_root,
            recovery_ledger_root=recovery_root,
            merge_authorization_ledger_root=auth_root,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPostMergeAttestationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPostMergeAttestationError(
            "host-controlled post-merge attestation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_POST_MERGE_ATTESTATION_SCOPE",
    "PilotExactTaskPostMergeAttestationError",
    "PilotExactTaskPostMergeAttestationReceipt",
    "attest_pilot_exact_task_post_merge",
]
