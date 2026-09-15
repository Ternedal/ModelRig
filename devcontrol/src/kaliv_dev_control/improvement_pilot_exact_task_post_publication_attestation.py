"""ADR-DC-052 read-only exact post-publication attestation.

This boundary normalizes either one completed ADR-DC-050 publication transaction
or one completed ADR-DC-051 recovery into the same exact remote-state evidence.

It performs no Git or GitHub mutation. The deterministic ADR-DC-047 intent is
reconstructed from durable ADR-DC-049 plus ADR-DC-044 receipts, the durable
completion source is validated, and GitHub is observed twice through the
credential-free ADR-DC-051 GET-only transport. Any drift or mismatch fails
closed. No ready-for-review, reviewer-request, merge, release, deploy, or
production-activation authority is granted.
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
from . import improvement_pilot_exact_task_remote_publication_authorization as auth_boundary
from . import improvement_pilot_exact_task_remote_publication_recovery as recovery_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as tx_boundary
from .improvement_pilot_exact_task_remote_publication_recovery import (
    PilotExactTaskRemotePublicationRecoveryReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskRemotePublicationTransactionReceipt,
)

PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-publication-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-publication-state-only"
)
PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCOPE = (
    "read-only-exact-post-publication-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"


class PilotExactTaskPostPublicationAttestationError(ValueError):
    """Durable completion or exact remote post-publication state is untrustworthy."""


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
        raise PilotExactTaskPostPublicationAttestationError(
            "post-publication evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPostPublicationAttestationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPostPublicationAttestationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostPublicationAttestationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostPublicationAttestationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskPostPublicationAttestationError(
            f"{name} is not a canonical branch"
        )
    return value


@dataclass(frozen=True, slots=True)
class _CompletionEvidence:
    source_kind: str
    source_receipt_sha256: str
    source_completed_at_utc: str
    pull_request_number: int
    pull_request_api_url: str
    transaction_lock_sha256: str
    pushed_marker_sha256: str | None
    draft_pr_marker_sha256: str | None

    def __post_init__(self) -> None:
        if self.source_kind not in {"transaction", "recovery"}:
            raise PilotExactTaskPostPublicationAttestationError(
                "completion source kind is unsupported"
            )
        for name in ("source_receipt_sha256", "transaction_lock_sha256"):
            _hex64(getattr(self, name), name=name)
        for name in ("pushed_marker_sha256", "draft_pr_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
        ):
            raise PilotExactTaskPostPublicationAttestationError(
                "completion pull-request number is invalid"
            )


def _hash_payload(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPostPublicationAttestationError(
            "durable completion payload is missing"
        )
    return hashlib.sha256(payload).hexdigest()


def _read_completion(
    *,
    key: str,
    intent: Any,
    auth: Any,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
) -> _CompletionEvidence:
    tx_root = _safe_ledger_root(transaction_ledger_root)
    recovery_root = _safe_ledger_root(recovery_ledger_root)
    tx_ledger = tx_boundary._PilotExactTaskRemotePublicationTransactionLedger(tx_root)
    tx_final, tx_lock, tx_pushed, tx_pr = tx_ledger._paths(key)
    recovery_ledger = recovery_boundary._PilotExactTaskRemotePublicationRecoveryLedger(
        recovery_root
    )
    recovery_final, recovery_lock = recovery_ledger._paths(key)

    tx_final_present = tx_final.exists() or tx_final.is_symlink()
    recovery_final_present = recovery_final.exists() or recovery_final.is_symlink()
    if tx_final_present == recovery_final_present:
        raise PilotExactTaskPostPublicationAttestationError(
            "post-publication completion source must be exactly one of ADR-DC-050 or ADR-DC-051"
        )

    lock_raw, lock_payload = recovery_boundary._read_canonical_object(
        tx_lock, name="ADR-DC-050 transaction lock"
    )
    recovery_boundary._validate_lock(lock_raw, intent, tx_ledger.root_sha256)
    transaction_lock_sha = _hash_payload(lock_payload)

    pushed_hash = None
    pr_hash = None
    marker_number = None
    marker_url = None
    pushed_present = tx_pushed.exists() or tx_pushed.is_symlink()
    pr_present = tx_pr.exists() or tx_pr.is_symlink()
    if pr_present and not pushed_present:
        raise PilotExactTaskPostPublicationAttestationError(
            "ADR-DC-050 PR marker exists without pushed marker"
        )
    if pushed_present:
        pushed_raw, pushed_payload = recovery_boundary._read_canonical_object(
            tx_pushed, name="ADR-DC-050 pushed marker"
        )
        recovery_boundary._validate_pushed(pushed_raw, intent)
        pushed_hash = _hash_payload(pushed_payload)
    if pr_present:
        pr_raw, pr_payload = recovery_boundary._read_canonical_object(
            tx_pr, name="ADR-DC-050 PR marker"
        )
        marker_number, marker_url = recovery_boundary._validate_pr_marker(pr_raw, intent)
        pr_hash = _hash_payload(pr_payload)

    if tx_final_present:
        if not pushed_present or not pr_present:
            raise PilotExactTaskPostPublicationAttestationError(
                "completed ADR-DC-050 transaction lacks durable phase evidence"
            )
        final_raw, _ = recovery_boundary._read_canonical_object(
            tx_final, name="ADR-DC-050 final transaction receipt"
        )
        try:
            receipt = PilotExactTaskRemotePublicationTransactionReceipt.from_mapping(
                final_raw
            )
        except Exception as exc:
            raise PilotExactTaskPostPublicationAttestationError(
                "ADR-DC-050 final transaction receipt is invalid"
            ) from exc
        if (
            receipt.transaction_key_sha256 != key
            or receipt.execution_nonce_sha256 != key
            or receipt.remote_publication_authorization_sha256 != auth.sha256
            or receipt.remote_publication_plan_sha256 != intent.remote_publication_plan_sha256
            or receipt.pr_intent_sha256 != intent.pr_intent_sha256
            or receipt.development_task_sha256 != intent.development_task_sha256
            or receipt.candidate_patch_sha256 != intent.candidate_patch_sha256
            or receipt.task_id != intent.task_id
            or receipt.repository != intent.repository
            or receipt.repository_id != intent.repository_id
            or receipt.provider != "github"
            or receipt.host != "github.com"
            or receipt.remote_name != "origin"
            or receipt.base_branch != intent.base_branch
            or receipt.head_branch != intent.head_branch
            or receipt.exact_task_base_sha != intent.base_sha
            or receipt.predicted_commit_sha != intent.predicted_commit_sha
            or receipt.pull_request_number != marker_number
            or receipt.pull_request_api_url != marker_url
            or receipt.remote_branch_created is not True
            or receipt.exact_commit_pushed is not True
            or receipt.draft_pr_created is not True
            or receipt.draft_pr_verified is not True
            or receipt.remote_write_authorized is not False
            or receipt.push_authorized is not False
            or receipt.pr_mutation_authorized is not False
            or receipt.merge_authorized is not False
            or receipt.production_activation_authorized is not False
        ):
            raise PilotExactTaskPostPublicationAttestationError(
                "ADR-DC-050 final receipt is not bound to exact durable publication intent"
            )
        return _CompletionEvidence(
            source_kind="transaction",
            source_receipt_sha256=receipt.sha256,
            source_completed_at_utc=receipt.completed_at_utc,
            pull_request_number=receipt.pull_request_number,
            pull_request_api_url=receipt.pull_request_api_url,
            transaction_lock_sha256=transaction_lock_sha,
            pushed_marker_sha256=pushed_hash,
            draft_pr_marker_sha256=pr_hash,
        )

    recovery_raw, _ = recovery_boundary._read_canonical_object(
        recovery_final, name="ADR-DC-051 final recovery receipt"
    )
    recovery_lock_raw, _ = recovery_boundary._read_canonical_object(
        recovery_lock, name="ADR-DC-051 recovery lock"
    )
    try:
        recovery_receipt = PilotExactTaskRemotePublicationRecoveryReceipt.from_mapping(
            recovery_raw
        )
    except Exception as exc:
        raise PilotExactTaskPostPublicationAttestationError(
            "ADR-DC-051 final recovery receipt is invalid"
        ) from exc
    expected_recovery_lock = {
        "schema",
        "recovery_key_sha256",
        "recovery_state_fingerprint_sha256",
        "recovery_authorization_payload_sha256",
        "operator_signature_sha256",
        "reviewer_signature_sha256",
        "action",
    }
    if (
        set(recovery_lock_raw) != expected_recovery_lock
        or recovery_lock_raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-remote-publication-recovery-lock/v1"
        or recovery_lock_raw.get("recovery_key_sha256") != key
        or recovery_lock_raw.get("recovery_state_fingerprint_sha256")
        != recovery_receipt.recovery_state_fingerprint_sha256
        or recovery_lock_raw.get("recovery_authorization_payload_sha256")
        != recovery_receipt.recovery_authorization_payload_sha256
        or recovery_lock_raw.get("action") != recovery_receipt.recovery_action
    ):
        raise PilotExactTaskPostPublicationAttestationError(
            "ADR-DC-051 recovery lock does not bind final recovery receipt"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(recovery_lock_raw.get(name), name=name)
    if (
        recovery_receipt.recovery_key_sha256 != key
        or recovery_receipt.execution_nonce_sha256 != key
        or recovery_receipt.remote_publication_authorization_sha256 != auth.sha256
        or recovery_receipt.remote_publication_plan_sha256
        != intent.remote_publication_plan_sha256
        or recovery_receipt.pr_intent_sha256 != intent.pr_intent_sha256
        or recovery_receipt.development_task_sha256 != intent.development_task_sha256
        or recovery_receipt.candidate_patch_sha256 != intent.candidate_patch_sha256
        or recovery_receipt.task_id != intent.task_id
        or recovery_receipt.repository != intent.repository
        or recovery_receipt.repository_id != intent.repository_id
        or recovery_receipt.base_branch != intent.base_branch
        or recovery_receipt.head_branch != intent.head_branch
        or recovery_receipt.exact_task_base_sha != intent.base_sha
        or recovery_receipt.predicted_commit_sha != intent.predicted_commit_sha
        or recovery_receipt.root_tree_sha != intent.root_tree_sha
        or recovery_receipt.draft_pr_created is not True
        or recovery_receipt.draft_pr_verified is not True
        or recovery_receipt.remote_write_authorized is not False
        or recovery_receipt.push_authorized is not False
        or recovery_receipt.pr_mutation_authorized is not False
        or recovery_receipt.merge_authorized is not False
        or recovery_receipt.production_activation_authorized is not False
    ):
        raise PilotExactTaskPostPublicationAttestationError(
            "ADR-DC-051 final receipt is not bound to exact durable publication intent"
        )
    if marker_number is not None and (
        marker_number != recovery_receipt.pull_request_number
        or marker_url != recovery_receipt.pull_request_api_url
    ):
        raise PilotExactTaskPostPublicationAttestationError(
            "ADR-DC-050 PR marker disagrees with ADR-DC-051 final recovery"
        )
    return _CompletionEvidence(
        source_kind="recovery",
        source_receipt_sha256=recovery_receipt.sha256,
        source_completed_at_utc=recovery_receipt.recovered_at_utc,
        pull_request_number=recovery_receipt.pull_request_number,
        pull_request_api_url=recovery_receipt.pull_request_api_url,
        transaction_lock_sha256=transaction_lock_sha,
        pushed_marker_sha256=pushed_hash,
        draft_pr_marker_sha256=pr_hash,
    )


def _normalize_remote_observation(
    *, value: Any, intent: Any, completion: _CompletionEvidence
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPostPublicationAttestationError(
            "post-publication GitHub observation is invalid"
        )
    pr = value.get("pull_request")
    if (
        value.get("base_sha") != intent.base_sha
        or value.get("head_sha") != intent.predicted_commit_sha
        or not isinstance(pr, Mapping)
        or pr.get("number") != completion.pull_request_number
        or pr.get("api_url") != completion.pull_request_api_url
    ):
        raise PilotExactTaskPostPublicationAttestationError(
            "GitHub state does not equal exact completed publication"
        )
    return {
        "base_sha": intent.base_sha,
        "head_sha": intent.predicted_commit_sha,
        "pull_request": {
            "number": completion.pull_request_number,
            "api_url": completion.pull_request_api_url,
        },
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
    _mark_post_publication_attestation_authenticated,
    _get_live_post_publication_attestation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostPublicationAttestationReceipt:
    completion_source_receipt_sha256: str
    remote_publication_authorization_sha256: str
    remote_publication_plan_sha256: str
    pr_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    transaction_lock_sha256: str
    remote_observation_sha256: str
    task_id: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    root_tree_sha: str
    pull_request_number: int
    pull_request_api_url: str
    completion_source: str
    source_completed_at_utc: str
    attested_at_utc: str
    durable_completion_verified: bool = True
    deterministic_pr_intent_reconstructed: bool = True
    remote_base_verified: bool = True
    remote_exact_head_verified: bool = True
    draft_pr_verified: bool = True
    double_observation_matched: bool = True
    post_publication_verified: bool = True
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
    attestation_scope: str = PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_AUTHORITY
            or self.attestation_scope != PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPostPublicationAttestationError(
                "post-publication attestation identity is unsupported"
            )
        for name in (
            "completion_source_receipt_sha256",
            "remote_publication_authorization_sha256",
            "remote_publication_plan_sha256",
            "pr_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "transaction_lock_sha256",
            "remote_observation_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("exact_task_base_sha", "predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskPostPublicationAttestationError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskPostPublicationAttestationError("repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskPostPublicationAttestationError("repository_id is invalid")
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if self.completion_source not in {"transaction", "recovery"}:
            raise PilotExactTaskPostPublicationAttestationError(
                "completion_source is unsupported"
            )
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPostPublicationAttestationError(
                "pull-request identity is invalid"
            )
        source_time = _utc(self.source_completed_at_utc, name="source_completed_at_utc")
        attested = _utc(self.attested_at_utc, name="attested_at_utc")
        if attested < source_time:
            raise PilotExactTaskPostPublicationAttestationError(
                "attestation predates durable completion"
            )
        required_true = (
            "durable_completion_verified",
            "deterministic_pr_intent_reconstructed",
            "remote_base_verified",
            "remote_exact_head_verified",
            "draft_pr_verified",
            "double_observation_matched",
            "post_publication_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostPublicationAttestationError(
                "post-publication attestation evidence is incomplete"
            )
        forced_false = (
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
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostPublicationAttestationError(
                "read-only post-publication attestation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_post_publication_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPostPublicationAttestationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskPostPublicationAttestationError(
                "post-publication attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _attest_verified_pilot_exact_task_post_publication(
    *,
    execution_nonce_sha256: str,
    transaction_ledger_root: Path,
    recovery_ledger_root: Path,
    authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskPostPublicationAttestationReceipt:
    key = _hex64(execution_nonce_sha256, name="execution_nonce_sha256")
    try:
        auth, local = recovery_boundary._load_receipts(
            key=key,
            authorization_ledger_root=authorization_ledger_root,
            local_transaction_ledger_root=local_transaction_ledger_root,
        )
        intent = recovery_boundary._intent(auth, local)
    except Exception as exc:
        raise PilotExactTaskPostPublicationAttestationError(
            "durable exact publication intent reconstruction failed"
        ) from exc

    completion = _read_completion(
        key=key,
        intent=intent,
        auth=auth,
        transaction_ledger_root=transaction_ledger_root,
        recovery_ledger_root=recovery_ledger_root,
    )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskPostPublicationAttestationError(
            "read-only GitHub observer is required"
        )
    try:
        first = _normalize_remote_observation(
            value=transport.observe(intent), intent=intent, completion=completion
        )
        second = _normalize_remote_observation(
            value=transport.observe(intent), intent=intent, completion=completion
        )
    except PilotExactTaskPostPublicationAttestationError:
        raise
    except Exception as exc:
        raise PilotExactTaskPostPublicationAttestationError(
            "post-publication GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskPostPublicationAttestationError(
            "GitHub post-publication state changed between observations"
        )

    observation_sha = hashlib.sha256(_canonical(first).encode("utf-8")).hexdigest()
    attested_at = now_provider()
    if _utc(attested_at, name="attested_at_utc") < _utc(
        completion.source_completed_at_utc, name="source_completed_at_utc"
    ):
        raise PilotExactTaskPostPublicationAttestationError(
            "system clock moved backwards after durable publication completion"
        )
    receipt = PilotExactTaskPostPublicationAttestationReceipt(
        completion_source_receipt_sha256=completion.source_receipt_sha256,
        remote_publication_authorization_sha256=auth.sha256,
        remote_publication_plan_sha256=intent.remote_publication_plan_sha256,
        pr_intent_sha256=intent.pr_intent_sha256,
        execution_nonce_sha256=key,
        development_task_sha256=intent.development_task_sha256,
        candidate_patch_sha256=intent.candidate_patch_sha256,
        transaction_lock_sha256=completion.transaction_lock_sha256,
        remote_observation_sha256=observation_sha,
        task_id=intent.task_id,
        repository=intent.repository,
        repository_id=intent.repository_id,
        base_branch=intent.base_branch,
        head_branch=intent.head_branch,
        exact_task_base_sha=intent.base_sha,
        predicted_commit_sha=intent.predicted_commit_sha,
        root_tree_sha=intent.root_tree_sha,
        pull_request_number=completion.pull_request_number,
        pull_request_api_url=completion.pull_request_api_url,
        completion_source=completion.source_kind,
        source_completed_at_utc=completion.source_completed_at_utc,
        attested_at_utc=attested_at,
    )
    _mark_post_publication_attestation_authenticated(
        receipt,
        source_kind=completion.source_kind,
        source_receipt_sha256=completion.source_receipt_sha256,
        observation_sha256=observation_sha,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostPublicationAttestationError(
            "post-publication attestation lost live provenance"
        )
    return receipt


def _canonical_roots() -> tuple[Path, Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            roots = (
                tx_boundary._POSIX_LEDGER,
                recovery_boundary._POSIX_LEDGER,
                auth_boundary._POSIX_LEDGER,
                local_tx_boundary._POSIX_LEDGER,
            )
        elif os.name == "nt":
            roots = (
                tx_boundary._WINDOWS_LEDGER,
                recovery_boundary._WINDOWS_LEDGER,
                auth_boundary._WINDOWS_LEDGER,
                local_tx_boundary._WINDOWS_LEDGER,
            )
        else:
            raise PilotExactTaskPostPublicationAttestationError(
                "post-publication attestation is unsupported on this platform"
            )
        return tuple(
            _require_host_controlled_ledger_root(Path(root)) for root in roots
        )  # type: ignore[return-value]
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPostPublicationAttestationError(
            "canonical post-publication ledgers are not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_post_publication(
    execution_nonce_sha256: str,
) -> PilotExactTaskPostPublicationAttestationReceipt:
    """Read-only attest one exact durable remote publication completion."""
    try:
        tx_root, recovery_root, auth_root, local_root = _canonical_roots()
        return _attest_verified_pilot_exact_task_post_publication(
            execution_nonce_sha256=execution_nonce_sha256,
            transaction_ledger_root=tx_root,
            recovery_ledger_root=recovery_root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            transport=recovery_boundary._GitHubRecoveryTransport(),
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPostPublicationAttestationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPostPublicationAttestationError(
            "host-controlled post-publication attestation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCHEMA",
    "PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_AUTHORITY",
    "PILOT_EXACT_TASK_POST_PUBLICATION_ATTESTATION_SCOPE",
    "PilotExactTaskPostPublicationAttestationError",
    "PilotExactTaskPostPublicationAttestationReceipt",
    "attest_pilot_exact_task_post_publication",
]
