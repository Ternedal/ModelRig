"""ADR-DC-056 read-only exact post-PR-lifecycle attestation.

This boundary normalizes either one completed ADR-DC-054 lifecycle transaction
or one completed ADR-DC-055 lifecycle recovery into one exact, read-only
post-lifecycle state attestation.

Completion identity is reconstructed from durable host-local evidence. GitHub is
then observed twice through ADR-DC-055's credential-free GET-only transport.
The exact pull request must be open, non-draft, bound to the exact repository /
base / head / commit identity and carry exactly the host-authorized reviewer set.

No review submission, review-thread mutation, ready-for-review, reviewer-request,
push, merge, release, deployment or production activation authority is granted.
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
from . import improvement_pilot_exact_task_local_commit_transaction as local_tx_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_recovery as lifecycle_recovery_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_transaction as lifecycle_tx_boundary
from . import improvement_pilot_exact_task_remote_publication_authorization as publication_auth_boundary
from .improvement_pilot_exact_task_pr_lifecycle_recovery import (
    PilotExactTaskPrLifecycleRecoveryReceipt,
)
from .improvement_pilot_exact_task_pr_lifecycle_transaction import (
    PilotExactTaskPrLifecycleTransactionReceipt,
)

PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-lifecycle-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-lifecycle-state-only"
)
PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCOPE = (
    "read-only-exact-post-lifecycle-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"


class PilotExactTaskPostLifecycleAttestationError(ValueError):
    """Durable lifecycle completion or exact GitHub state is untrustworthy."""


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
        raise PilotExactTaskPostLifecycleAttestationError(
            "post-lifecycle evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPostLifecycleAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostLifecycleAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostLifecycleAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            f"{name} is invalid"
        ) from exc


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
        raise PilotExactTaskPostLifecycleAttestationError(
            f"{name} is not a canonical branch"
        )
    return value


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPostLifecycleAttestationError(
            "durable lifecycle payload is missing"
        )
    return hashlib.sha256(payload).hexdigest()


def _reviewer_set_sha256(
    usernames: tuple[str, ...], teams: tuple[str, ...]
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "reviewer_usernames": list(usernames),
                "reviewer_team_slugs": list(teams),
            }
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class _LifecycleCompletionEvidence:
    source_kind: str
    source_receipt_sha256: str
    source_completed_at_utc: str
    transaction_lock_sha256: str
    ready_marker_sha256: str | None
    reviewers_marker_sha256: str | None
    pull_request_node_id_sha256: str

    def __post_init__(self) -> None:
        if self.source_kind not in {"transaction", "recovery"}:
            raise PilotExactTaskPostLifecycleAttestationError(
                "lifecycle completion source kind is unsupported"
            )
        for name in (
            "source_receipt_sha256",
            "transaction_lock_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("ready_marker_sha256", "reviewers_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")


def _read_canonical(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        return lifecycle_recovery_boundary._read_canonical_object(path, name=name)
    except Exception as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            f"{name} is unavailable or invalid"
        ) from exc


def _read_completion(
    *,
    key: str,
    intent: Any,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
) -> _LifecycleCompletionEvidence:
    tx_ledger = lifecycle_tx_boundary._PilotExactTaskPrLifecycleTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    recovery_ledger = lifecycle_recovery_boundary._PilotExactTaskPrLifecycleRecoveryLedger(
        _safe_ledger_root(recovery_ledger_root)
    )
    tx_final, tx_lock, tx_ready, tx_reviewers = tx_ledger._paths(key)
    recovery_final, recovery_lock = recovery_ledger._paths(key)

    tx_final_present = tx_final.exists() or tx_final.is_symlink()
    recovery_final_present = recovery_final.exists() or recovery_final.is_symlink()
    if tx_final_present == recovery_final_present:
        raise PilotExactTaskPostLifecycleAttestationError(
            "post-lifecycle completion source must be exactly one of ADR-DC-054 or ADR-DC-055"
        )

    lock_raw, lock_payload = _read_canonical(
        tx_lock, name="ADR-DC-054 lifecycle transaction lock"
    )
    try:
        lifecycle_recovery_boundary._validate_transaction_lock(
            lock_raw,
            key=key,
            intent=intent,
            transaction_ledger_root_sha256=tx_ledger.root_sha256,
        )
    except Exception as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            "ADR-DC-054 transaction lock does not bind exact lifecycle intent"
        ) from exc
    transaction_lock_sha = _payload_sha256(lock_payload)

    ready_hash = None
    reviewers_hash = None
    ready_node_sha = None
    ready_state_sha = None
    reviewers_state_sha = None

    ready_present = tx_ready.exists() or tx_ready.is_symlink()
    reviewers_present = tx_reviewers.exists() or tx_reviewers.is_symlink()
    if reviewers_present and not ready_present:
        raise PilotExactTaskPostLifecycleAttestationError(
            "ADR-DC-054 reviewers marker exists without ready marker"
        )
    if ready_present:
        ready_raw, ready_payload = _read_canonical(
            tx_ready, name="ADR-DC-054 ready marker"
        )
        try:
            ready_node_sha, ready_state_sha, _ready_at = (
                lifecycle_recovery_boundary._validate_ready_marker(
                    ready_raw, key=key, intent=intent
                )
            )
        except Exception as exc:
            raise PilotExactTaskPostLifecycleAttestationError(
                "ADR-DC-054 ready marker is invalid"
            ) from exc
        ready_hash = _payload_sha256(ready_payload)
    if reviewers_present:
        reviewers_raw, reviewers_payload = _read_canonical(
            tx_reviewers, name="ADR-DC-054 reviewers marker"
        )
        try:
            reviewers_state_sha, _reviewers_at = (
                lifecycle_recovery_boundary._validate_reviewers_marker(
                    reviewers_raw, key=key, intent=intent
                )
            )
        except Exception as exc:
            raise PilotExactTaskPostLifecycleAttestationError(
                "ADR-DC-054 reviewers marker is invalid"
            ) from exc
        reviewers_hash = _payload_sha256(reviewers_payload)

    if tx_final_present:
        if not ready_present or not reviewers_present:
            raise PilotExactTaskPostLifecycleAttestationError(
                "completed ADR-DC-054 transaction lacks durable phase evidence"
            )
        raw, _payload = _read_canonical(
            tx_final, name="ADR-DC-054 final lifecycle transaction receipt"
        )
        try:
            receipt = PilotExactTaskPrLifecycleTransactionReceipt.from_mapping(raw)
        except Exception as exc:
            raise PilotExactTaskPostLifecycleAttestationError(
                "ADR-DC-054 final lifecycle transaction receipt is invalid"
            ) from exc
        if (
            receipt.transaction_key_sha256 != key
            or receipt.execution_nonce_sha256 != key
            or receipt.pr_lifecycle_authorization_sha256
            != intent.pr_lifecycle_authorization_sha256
            or receipt.post_publication_attestation_sha256
            != intent.post_publication_attestation_sha256
            or receipt.lifecycle_config_sha256 != intent.lifecycle_config_sha256
            or receipt.reviewer_set_sha256 != intent.reviewer_set_sha256
            or receipt.development_task_sha256 != intent.development_task_sha256
            or receipt.candidate_patch_sha256 != intent.candidate_patch_sha256
            or receipt.pr_intent_sha256 != intent.pr_intent_sha256
            or receipt.repository != intent.repository
            or receipt.repository_id != intent.repository_id
            or receipt.base_branch != intent.base_branch
            or receipt.head_branch != intent.head_branch
            or receipt.predicted_commit_sha != intent.predicted_commit_sha
            or receipt.pull_request_number != intent.pull_request_number
            or receipt.pull_request_api_url != intent.pull_request_api_url
            or receipt.pull_request_node_id_sha256 != ready_node_sha
            or receipt.reviewer_usernames != intent.reviewer_usernames
            or receipt.reviewer_team_slugs != intent.reviewer_team_slugs
            or receipt.post_ready_state_sha256 != ready_state_sha
            or receipt.final_state_sha256 != reviewers_state_sha
            or receipt.ready_for_review_completed is not True
            or receipt.reviewer_requests_completed is not True
            or receipt.final_pr_state_verified is not True
            or receipt.ready_for_review_authorized is not False
            or receipt.reviewer_request_authorized is not False
            or receipt.remote_write_authorized is not False
            or receipt.push_authorized is not False
            or receipt.pr_mutation_authorized is not False
            or receipt.merge_authorized is not False
            or receipt.release_authorized is not False
            or receipt.deploy_authorized is not False
            or receipt.production_activation_authorized is not False
            or receipt.draft is not False
            or receipt.nonce_reusable is not False
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "ADR-DC-054 final receipt is not bound to exact lifecycle intent"
            )
        return _LifecycleCompletionEvidence(
            source_kind="transaction",
            source_receipt_sha256=receipt.sha256,
            source_completed_at_utc=receipt.completed_at_utc,
            transaction_lock_sha256=transaction_lock_sha,
            ready_marker_sha256=ready_hash,
            reviewers_marker_sha256=reviewers_hash,
            pull_request_node_id_sha256=receipt.pull_request_node_id_sha256,
        )

    recovery_raw, _recovery_payload = _read_canonical(
        recovery_final, name="ADR-DC-055 final lifecycle recovery receipt"
    )
    recovery_lock_raw, _recovery_lock_payload = _read_canonical(
        recovery_lock, name="ADR-DC-055 lifecycle recovery lock"
    )
    try:
        receipt = PilotExactTaskPrLifecycleRecoveryReceipt.from_mapping(recovery_raw)
    except Exception as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            "ADR-DC-055 final lifecycle recovery receipt is invalid"
        ) from exc

    expected_lock = {
        "schema",
        "recovery_key_sha256",
        "recovery_state_fingerprint_sha256",
        "recovery_authorization_payload_sha256",
        "operator_signature_sha256",
        "reviewer_signature_sha256",
        "action",
    }
    if (
        set(recovery_lock_raw) != expected_lock
        or recovery_lock_raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-recovery-lock/v1"
        or recovery_lock_raw.get("recovery_key_sha256") != key
        or recovery_lock_raw.get("recovery_state_fingerprint_sha256")
        != receipt.recovery_state_fingerprint_sha256
        or recovery_lock_raw.get("recovery_authorization_payload_sha256")
        != receipt.recovery_authorization_payload_sha256
        or recovery_lock_raw.get("action") != receipt.recovery_action
    ):
        raise PilotExactTaskPostLifecycleAttestationError(
            "ADR-DC-055 recovery lock does not bind final recovery receipt"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(recovery_lock_raw.get(name), name=name)

    if (
        receipt.recovery_key_sha256 != key
        or receipt.execution_nonce_sha256 != key
        or receipt.transaction_lock_sha256 != transaction_lock_sha
        or receipt.ready_marker_sha256 != ready_hash
        or receipt.reviewers_marker_sha256 != reviewers_hash
        or receipt.pr_lifecycle_authorization_sha256
        != intent.pr_lifecycle_authorization_sha256
        or receipt.post_publication_attestation_sha256
        != intent.post_publication_attestation_sha256
        or receipt.lifecycle_config_sha256 != intent.lifecycle_config_sha256
        or receipt.reviewer_set_sha256 != intent.reviewer_set_sha256
        or receipt.development_task_sha256 != intent.development_task_sha256
        or receipt.candidate_patch_sha256 != intent.candidate_patch_sha256
        or receipt.pr_intent_sha256 != intent.pr_intent_sha256
        or receipt.repository != intent.repository
        or receipt.repository_id != intent.repository_id
        or receipt.base_branch != intent.base_branch
        or receipt.head_branch != intent.head_branch
        or receipt.exact_task_base_sha != intent.exact_task_base_sha
        or receipt.predicted_commit_sha != intent.predicted_commit_sha
        or receipt.pull_request_number != intent.pull_request_number
        or receipt.pull_request_api_url != intent.pull_request_api_url
        or receipt.reviewer_usernames != intent.reviewer_usernames
        or receipt.reviewer_team_slugs != intent.reviewer_team_slugs
        or receipt.exact_pr_verified is not True
        or receipt.ready_for_review_verified is not True
        or receipt.reviewer_requests_verified is not True
        or receipt.ready_for_review_authorized is not False
        or receipt.reviewer_request_authorized is not False
        or receipt.remote_write_authorized is not False
        or receipt.push_authorized is not False
        or receipt.pr_mutation_authorized is not False
        or receipt.merge_authorized is not False
        or receipt.release_authorized is not False
        or receipt.deploy_authorized is not False
        or receipt.production_activation_authorized is not False
        or receipt.draft is not False
        or receipt.nonce_reusable is not False
    ):
        raise PilotExactTaskPostLifecycleAttestationError(
            "ADR-DC-055 final receipt is not bound to exact lifecycle intent"
        )
    return _LifecycleCompletionEvidence(
        source_kind="recovery",
        source_receipt_sha256=receipt.sha256,
        source_completed_at_utc=receipt.recovered_at_utc,
        transaction_lock_sha256=transaction_lock_sha,
        ready_marker_sha256=ready_hash,
        reviewers_marker_sha256=reviewers_hash,
        pull_request_node_id_sha256=receipt.pull_request_node_id_sha256,
    )


def _normalize_remote_state(
    *, value: Any, intent: Any, completion: _LifecycleCompletionEvidence
) -> dict[str, Any]:
    if type(value) is not lifecycle_recovery_boundary._LifecycleRemoteState:
        raise PilotExactTaskPostLifecycleAttestationError(
            "post-lifecycle GitHub observer returned invalid state"
        )
    try:
        lifecycle_recovery_boundary._validate_remote_state(value, intent)
    except Exception as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            "GitHub lifecycle state is not bound to exact intent"
        ) from exc
    if (
        value.draft is not False
        or value.reviewer_usernames != intent.reviewer_usernames
        or value.reviewer_team_slugs != intent.reviewer_team_slugs
        or _reviewer_set_sha256(
            value.reviewer_usernames, value.reviewer_team_slugs
        )
        != intent.reviewer_set_sha256
        or hashlib.sha256(
            value.pull_request_node_id.encode("utf-8")
        ).hexdigest()
        != completion.pull_request_node_id_sha256
    ):
        raise PilotExactTaskPostLifecycleAttestationError(
            "GitHub lifecycle state is not exact completed non-draft reviewer state"
        )
    return {
        "repository": value.repository,
        "repository_id": value.repository_id,
        "base_branch": value.base_branch,
        "base_sha": value.base_sha,
        "head_branch": value.head_branch,
        "head_sha": value.head_sha,
        "pull_request_number": value.pull_request_number,
        "pull_request_api_url": value.pull_request_api_url,
        "pull_request_node_id_sha256": completion.pull_request_node_id_sha256,
        "draft": False,
        "reviewer_usernames": list(value.reviewer_usernames),
        "reviewer_team_slugs": list(value.reviewer_team_slugs),
        "maintainer_can_modify": False,
        "state": "open",
    }


def _live_registry():
    records: dict[
        int,
        tuple[int, str, weakref.ReferenceType[Any], str, str, str],
    ] = {}

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
            or receipt.completion_source != source_kind
            or receipt.completion_source_receipt_sha256
            != source_receipt_sha256
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
    _mark_post_lifecycle_attestation_authenticated,
    _get_live_post_lifecycle_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostLifecycleAttestationReceipt:
    completion_source_receipt_sha256: str
    pr_lifecycle_authorization_sha256: str
    post_publication_attestation_sha256: str
    lifecycle_config_sha256: str
    reviewer_set_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    ready_marker_sha256: str | None
    reviewers_marker_sha256: str | None
    remote_observation_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    completion_source: str
    source_completed_at_utc: str
    attested_at_utc: str
    durable_completion_verified: bool = True
    exact_pr_verified: bool = True
    ready_for_review_verified: bool = True
    reviewer_requests_verified: bool = True
    double_observation_matched: bool = True
    post_lifecycle_verified: bool = True
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    draft: bool = False
    nonce_reusable: bool = False
    attestation_scope: str = PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_AUTHORITY
            or self.attestation_scope
            != PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle attestation identity is unsupported"
            )
        for name in (
            "completion_source_receipt_sha256",
            "pr_lifecycle_authorization_sha256",
            "post_publication_attestation_sha256",
            "lifecycle_config_sha256",
            "reviewer_set_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "remote_observation_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("ready_marker_sha256", "reviewers_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.exact_task_base_sha, name="exact_task_base_sha")
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle pull-request identity is invalid"
            )
        if self.completion_source not in {"transaction", "recovery"}:
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle completion source is unsupported"
            )
        if (
            list(self.reviewer_usernames)
            != sorted(set(self.reviewer_usernames))
            or list(self.reviewer_team_slugs)
            != sorted(set(self.reviewer_team_slugs))
            or (
                not self.reviewer_usernames
                and not self.reviewer_team_slugs
            )
            or _reviewer_set_sha256(
                self.reviewer_usernames, self.reviewer_team_slugs
            )
            != self.reviewer_set_sha256
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle reviewer set is invalid"
            )
        if self.completion_source == "transaction" and (
            self.ready_marker_sha256 is None
            or self.reviewers_marker_sha256 is None
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "normal lifecycle completion requires both durable phase markers"
            )
        source_time = _utc(
            self.source_completed_at_utc, name="source_completed_at_utc"
        )
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if attested < source_time:
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle attestation predates durable completion"
            )
        required_true = (
            "durable_completion_verified",
            "exact_pr_verified",
            "ready_for_review_verified",
            "reviewer_requests_verified",
            "double_observation_matched",
            "post_lifecycle_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle attestation evidence is incomplete"
            )
        forced_false = (
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "draft",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostLifecycleAttestationError(
                "read-only post-lifecycle attestation retains forbidden authority/state"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_post_lifecycle_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["reviewer_usernames"] = list(self.reviewer_usernames)
        result["reviewer_team_slugs"] = list(self.reviewer_team_slugs)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPostLifecycleAttestationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle attestation fields mismatch"
            )
        data = dict(value)
        if not isinstance(data.get("reviewer_usernames"), list) or not isinstance(
            data.get("reviewer_team_slugs"), list
        ):
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle reviewer sets are invalid"
            )
        data["reviewer_usernames"] = tuple(data["reviewer_usernames"])
        data["reviewer_team_slugs"] = tuple(data["reviewer_team_slugs"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_post_lifecycle(
    *,
    execution_nonce_sha256: str,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
    lifecycle_authorization_ledger_root: Path,
    publication_authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskPostLifecycleAttestationReceipt:
    key = _hex64(execution_nonce_sha256, name="execution_nonce_sha256")
    try:
        intent = lifecycle_recovery_boundary._reconstruct_intent(
            key=key,
            lifecycle_authorization_ledger_root=lifecycle_authorization_ledger_root,
            publication_authorization_ledger_root=publication_authorization_ledger_root,
            local_transaction_ledger_root=local_transaction_ledger_root,
        )
    except Exception as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            "durable exact lifecycle intent reconstruction failed"
        ) from exc

    completion = _read_completion(
        key=key,
        intent=intent,
        transaction_ledger_root=transaction_ledger_root,
        recovery_ledger_root=recovery_ledger_root,
    )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskPostLifecycleAttestationError(
            "read-only lifecycle GitHub observer is required"
        )
    try:
        first = _normalize_remote_state(
            value=transport.observe(intent),
            intent=intent,
            completion=completion,
        )
        second = _normalize_remote_state(
            value=transport.observe(intent),
            intent=intent,
            completion=completion,
        )
    except PilotExactTaskPostLifecycleAttestationError:
        raise
    except Exception as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            "post-lifecycle GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskPostLifecycleAttestationError(
            "GitHub post-lifecycle state changed between observations"
        )

    observation_sha = hashlib.sha256(
        _canonical(first).encode("utf-8")
    ).hexdigest()
    attested_at = now_provider()
    if _utc(attested_at, name="attested_at_utc") < _utc(
        completion.source_completed_at_utc,
        name="source_completed_at_utc",
    ):
        raise PilotExactTaskPostLifecycleAttestationError(
            "system clock moved backwards after lifecycle completion"
        )

    receipt = PilotExactTaskPostLifecycleAttestationReceipt(
        completion_source_receipt_sha256=completion.source_receipt_sha256,
        pr_lifecycle_authorization_sha256=intent.pr_lifecycle_authorization_sha256,
        post_publication_attestation_sha256=intent.post_publication_attestation_sha256,
        lifecycle_config_sha256=intent.lifecycle_config_sha256,
        reviewer_set_sha256=intent.reviewer_set_sha256,
        execution_nonce_sha256=key,
        development_task_sha256=intent.development_task_sha256,
        candidate_patch_sha256=intent.candidate_patch_sha256,
        pr_intent_sha256=intent.pr_intent_sha256,
        transaction_lock_sha256=completion.transaction_lock_sha256,
        ready_marker_sha256=completion.ready_marker_sha256,
        reviewers_marker_sha256=completion.reviewers_marker_sha256,
        remote_observation_sha256=observation_sha,
        repository=intent.repository,
        repository_id=intent.repository_id,
        base_branch=intent.base_branch,
        head_branch=intent.head_branch,
        exact_task_base_sha=intent.exact_task_base_sha,
        predicted_commit_sha=intent.predicted_commit_sha,
        pull_request_number=intent.pull_request_number,
        pull_request_api_url=intent.pull_request_api_url,
        pull_request_node_id_sha256=completion.pull_request_node_id_sha256,
        reviewer_usernames=intent.reviewer_usernames,
        reviewer_team_slugs=intent.reviewer_team_slugs,
        completion_source=completion.source_kind,
        source_completed_at_utc=completion.source_completed_at_utc,
        attested_at_utc=attested_at,
    )
    _mark_post_lifecycle_attestation_authenticated(
        receipt,
        source_kind=completion.source_kind,
        source_receipt_sha256=completion.source_receipt_sha256,
        observation_sha256=observation_sha,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostLifecycleAttestationError(
            "post-lifecycle attestation lost live provenance"
        )
    return receipt


def _canonical_roots() -> tuple[Path, Path, Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            roots = (
                lifecycle_tx_boundary._POSIX_LEDGER,
                lifecycle_recovery_boundary._POSIX_LEDGER,
                lifecycle_auth_boundary._POSIX_LEDGER,
                publication_auth_boundary._POSIX_LEDGER,
                local_tx_boundary._POSIX_LEDGER,
            )
        elif os.name == "nt":
            roots = (
                lifecycle_tx_boundary._WINDOWS_LEDGER,
                lifecycle_recovery_boundary._WINDOWS_LEDGER,
                lifecycle_auth_boundary._WINDOWS_LEDGER,
                publication_auth_boundary._WINDOWS_LEDGER,
                local_tx_boundary._WINDOWS_LEDGER,
            )
        else:
            raise PilotExactTaskPostLifecycleAttestationError(
                "post-lifecycle attestation is unsupported on this platform"
            )
        return tuple(
            _require_host_controlled_ledger_root(Path(root))
            for root in roots
        )  # type: ignore[return-value]
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            "canonical post-lifecycle ledgers are not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_post_lifecycle(
    execution_nonce_sha256: str,
) -> PilotExactTaskPostLifecycleAttestationReceipt:
    """Read-only attest one exact durable PR-lifecycle completion."""
    try:
        (
            tx_root,
            recovery_root,
            lifecycle_auth_root,
            publication_auth_root,
            local_root,
        ) = _canonical_roots()
        return _attest_verified_pilot_exact_task_post_lifecycle(
            execution_nonce_sha256=execution_nonce_sha256,
            transaction_ledger_root=tx_root,
            recovery_ledger_root=recovery_root,
            lifecycle_authorization_ledger_root=lifecycle_auth_root,
            publication_authorization_ledger_root=publication_auth_root,
            local_transaction_ledger_root=local_root,
            transport=lifecycle_recovery_boundary._GitHubLifecycleRecoveryTransport(),
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPostLifecycleAttestationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPostLifecycleAttestationError(
            "host-controlled post-lifecycle attestation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_POST_LIFECYCLE_ATTESTATION_SCOPE",
    "PilotExactTaskPostLifecycleAttestationError",
    "PilotExactTaskPostLifecycleAttestationReceipt",
    "attest_pilot_exact_task_post_lifecycle",
]