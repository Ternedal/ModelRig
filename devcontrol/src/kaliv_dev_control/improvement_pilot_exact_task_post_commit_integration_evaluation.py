"""ADR-DC-045 read-only post-commit integration-candidate evaluation.

This boundary accepts only the exact live ADR-DC-044 local commit transaction,
observes the completed local commit twice through TrustedGitRunner, and proves
that the branch, commit object, parent, tree, index and clean workspace still
match the exact precomputed identities.

It performs no Git mutation and grants no local or remote publication authority.
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
from typing import Any, Mapping

from . import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary
from . import improvement_pilot_exact_task_local_commit_transaction as transaction_boundary
from .improvement_pilot_exact_task_local_commit_object_identity import (
    PilotExactTaskLocalCommitObjectIdentity,
)
from .improvement_pilot_exact_task_local_commit_transaction import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_AUTHORITY,
    PilotExactTaskLocalCommitTransactionReceipt,
)

PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-commit-integration-evaluation/v1"
)
PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-local-commit-integration-candidate-only"
)
PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCOPE = (
    "mechanical-post-local-commit-integration-candidate-only-v1"
)
_MAX_COMMIT_PAYLOAD_BYTES = 1024 * 1024
_MAX_DIFF_BYTES = 32 * 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class PilotExactTaskPostCommitIntegrationEvaluationError(ValueError):
    """The exact local commit cannot be accepted as an integration candidate."""


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
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "post-commit integration evaluation is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPostCommitIntegrationEvaluationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostCommitIntegrationEvaluationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha_output(raw: bytes, *, name: str) -> str:
    try:
        value = raw.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            f"{name} is not canonical ASCII"
        ) from exc
    return _hex40(value, name=name)


def _require_live_local_commit_transaction(
    value: Any,
) -> tuple[
    PilotExactTaskLocalCommitTransactionReceipt,
    PilotExactTaskLocalCommitObjectIdentity,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskLocalCommitTransactionReceipt:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "exact ADR-DC-044 local commit transaction receipt is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitTransactionReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "ADR-DC-044 local commit transaction replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "ADR-DC-044 local commit transaction identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_TRANSACTION_AUTHORITY
        or value.transaction_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.local_commit_write_authorization_authenticated is not True
        or value.local_commit_write_authority_consumed is not True
        or value.prewrite_workspace_revalidated is not True
        or value.local_head_ref_bound is not True
        or value.write_tree_sha_matched is not True
        or value.commit_object_sha_matched is not True
        or value.commit_object_payload_matched is not True
        or value.local_ref_compare_and_swap_succeeded is not True
        or value.post_commit_head_verified is not True
        or value.post_commit_index_clean is not True
        or value.post_commit_worktree_clean is not True
        or value.local_commit_created is not True
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.integration_ready is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "evaluation requires one live completed inert ADR-DC-044 transaction"
        )

    inputs = transaction_boundary._get_live_local_commit_transaction_inputs(value)
    if inputs is None:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "ADR-DC-044 live transaction inputs are unavailable"
        )
    identity = inputs.get("local_commit_object_identity")
    authorization = inputs.get("local_commit_write_authorization")
    evaluation = inputs.get("post_execution_evaluation")
    task = inputs.get("task")
    if (
        type(identity) is not PilotExactTaskLocalCommitObjectIdentity
        or identity.identity_authenticated is not True
        or authorization is None
        or evaluation is None
        or task is None
        or identity.sha256 != value.local_commit_object_identity_sha256
        or getattr(authorization, "sha256", None)
        != value.local_commit_write_authorization_sha256
        or getattr(evaluation, "sha256", None)
        != identity.post_execution_evaluation_sha256
        or getattr(task, "task_id", None) != value.task_id
        or getattr(task, "repository", None) != value.repository
        or getattr(task, "base_sha", None) != value.base_sha
        or identity.execution_nonce_sha256 != value.execution_nonce_sha256
        or identity.development_task_sha256 != value.development_task_sha256
        or identity.root_tree_sha != value.root_tree_sha
        or identity.commit_payload_sha256 != value.commit_payload_sha256
        or identity.predicted_commit_sha != value.predicted_commit_sha
    ):
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "ADR-DC-044 transaction is not bound to its exact live provenance"
        )
    return value, identity, inputs


def _expected_commit_payload(identity: PilotExactTaskLocalCommitObjectIdentity) -> bytes:
    try:
        payload = identity_boundary._commit_payload(
            tree_sha=identity.root_tree_sha,
            parent_sha=identity.base_sha,
            subject=identity.commit_subject,
            epoch_seconds=identity.commit_epoch_seconds,
        )
    except Exception as exc:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "exact local commit payload reconstruction failed"
        ) from exc
    if (
        not payload
        or len(payload) > _MAX_COMMIT_PAYLOAD_BYTES
        or hashlib.sha256(payload).hexdigest() != identity.commit_payload_sha256
        or identity_boundary._git_sha1("commit", payload)
        != identity.predicted_commit_sha
    ):
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "exact local commit payload identity is inconsistent"
        )
    return payload


def _observe_exact_post_commit_state(
    transaction: PilotExactTaskLocalCommitTransactionReceipt,
    identity: PilotExactTaskLocalCommitObjectIdentity,
    inputs: Mapping[str, Any],
) -> Mapping[str, Any]:
    runner = inputs["git_runner"]
    cwd = Path(inputs["workspace_root"])
    ref = transaction_boundary._local_head_ref(transaction.local_head_ref)
    expected_payload = _expected_commit_payload(identity)
    try:
        symbolic = runner.run(
            ("symbolic-ref", "-q", "HEAD"),
            cwd=cwd,
            maximum=512,
            timeout_seconds=120,
        ).decode("ascii", errors="strict").strip()
        head = runner.run(
            ("rev-parse", "--verify", "HEAD"),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        )
        direct_ref = runner.run(
            ("rev-parse", "--verify", ref),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        )
        parent = runner.run(
            ("rev-parse", "--verify", f"{identity.predicted_commit_sha}^"),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        )
        tree = runner.run(
            ("rev-parse", "--verify", f"{identity.predicted_commit_sha}^{{tree}}"),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        )
        object_format = runner.run(
            ("rev-parse", "--show-object-format"),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        ).decode("ascii", errors="strict").strip()
        kind = runner.run(
            ("cat-file", "-t", identity.predicted_commit_sha),
            cwd=cwd,
            maximum=128,
            timeout_seconds=120,
        )
        commit_payload = runner.run(
            ("cat-file", "commit", identity.predicted_commit_sha),
            cwd=cwd,
            maximum=_MAX_COMMIT_PAYLOAD_BYTES,
            timeout_seconds=120,
        )
        index_payload = identity_boundary._read_index_manifest(inputs)
        cached = runner.run(
            (
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            ),
            cwd=cwd,
            maximum=_MAX_DIFF_BYTES,
            timeout_seconds=120,
        )
        unstaged = runner.run(
            (
                "diff",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            ),
            cwd=cwd,
            maximum=_MAX_DIFF_BYTES,
            timeout_seconds=120,
        )
        untracked = runner.run(
            ("ls-files", "--others", "--exclude-standard", "-z"),
            cwd=cwd,
            maximum=_MAX_DIFF_BYTES,
            timeout_seconds=120,
        )
    except Exception as exc:
        if isinstance(exc, PilotExactTaskPostCommitIntegrationEvaluationError):
            raise
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "read-only post-commit state observation failed"
        ) from exc

    head_sha = _sha_output(head, name="post-commit HEAD SHA")
    branch_sha = _sha_output(direct_ref, name="post-commit branch SHA")
    parent_sha = _sha_output(parent, name="post-commit parent SHA")
    tree_sha = _sha_output(tree, name="post-commit tree SHA")
    if symbolic != ref:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "local HEAD symbolic ref changed after ADR-DC-044"
        )
    if head_sha != identity.predicted_commit_sha or branch_sha != identity.predicted_commit_sha:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "local HEAD/ref no longer equals exact predicted commit"
        )
    if parent_sha != identity.base_sha:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "local commit parent no longer equals exact base"
        )
    if tree_sha != identity.root_tree_sha:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "local commit tree no longer equals exact root tree"
        )
    if object_format != identity.object_format or object_format != "sha1":
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "Git object format changed after local commit"
        )
    if kind != b"commit\n" or commit_payload != expected_payload:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "local commit object payload no longer matches exact identity"
        )
    if hashlib.sha256(index_payload).hexdigest() != identity.index_manifest_sha256:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "Git index identity changed after local commit"
        )
    if cached != b"":
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "Git index is not clean after local commit"
        )
    if unstaged != b"" or untracked != b"":
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "Git worktree is not clean after local commit"
        )

    return MappingProxyType(
        {
            "local_head_ref": ref,
            "head_sha": head_sha,
            "branch_sha": branch_sha,
            "parent_sha": parent_sha,
            "tree_sha": tree_sha,
            "object_format": object_format,
            "commit_payload_sha256": hashlib.sha256(commit_payload).hexdigest(),
            "index_manifest_sha256": hashlib.sha256(index_payload).hexdigest(),
            "cached_diff_sha256": hashlib.sha256(cached).hexdigest(),
            "unstaged_diff_sha256": hashlib.sha256(unstaged).hexdigest(),
            "untracked_sha256": hashlib.sha256(untracked).hexdigest(),
        }
    )


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
        ],
    ] = {}

    def mark(
        receipt: Any,
        transaction: PilotExactTaskLocalCommitTransactionReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(transaction),
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, transaction_ref = entry
        transaction = transaction_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or transaction is None
            or transaction.transaction_authenticated is not True
            or receipt.sha256 != digest
            or receipt.local_commit_transaction_sha256 != transaction.sha256
        ):
            return None
        inputs = transaction_boundary._get_live_local_commit_transaction_inputs(
            transaction
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["local_commit_transaction"] = transaction
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_post_commit_integration_evaluation_authenticated,
    _get_live_post_commit_integration_evaluation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostCommitIntegrationEvaluationReceipt:
    local_commit_transaction_sha256: str
    local_commit_write_authorization_sha256: str
    local_commit_object_identity_sha256: str
    post_execution_evaluation_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    local_head_ref: str
    predicted_commit_sha: str
    root_tree_sha: str
    commit_payload_sha256: str
    index_manifest_sha256: str
    committed_at_utc: str
    evaluated_at_utc: str
    local_commit_transaction_authenticated: bool = True
    local_commit_created: bool = True
    local_head_ref_verified: bool = True
    commit_object_verified: bool = True
    commit_payload_verified: bool = True
    parent_base_verified: bool = True
    root_tree_verified: bool = True
    index_manifest_preserved: bool = True
    index_clean: bool = True
    worktree_clean: bool = True
    double_observation_matched: bool = True
    mechanical_integration_evaluation_passed: bool = True
    integration_candidate_verified: bool = True
    semantic_acceptance_criteria_evaluated: bool = False
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    evaluation_scope: str = PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCHEMA:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration evaluation schema is unsupported"
            )
        if self.evaluation_scope != PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCOPE:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration evaluation scope is unsupported"
            )
        for name in (
            "local_commit_transaction_sha256",
            "local_commit_write_authorization_sha256",
            "local_commit_object_identity_sha256",
            "post_execution_evaluation_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "commit_payload_sha256",
            "index_manifest_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskPostCommitIntegrationEvaluationError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskPostCommitIntegrationEvaluationError("repository is invalid")
        if transaction_boundary._local_head_ref(self.local_head_ref) != self.local_head_ref:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "local_head_ref is non-canonical"
            )
        committed = _utc(self.committed_at_utc, name="committed_at_utc")
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if evaluated < committed:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit evaluation predates local commit"
            )
        required_true = (
            "local_commit_transaction_authenticated",
            "local_commit_created",
            "local_head_ref_verified",
            "commit_object_verified",
            "commit_payload_verified",
            "parent_base_verified",
            "root_tree_verified",
            "index_manifest_preserved",
            "index_clean",
            "worktree_clean",
            "double_observation_matched",
            "mechanical_integration_evaluation_passed",
            "integration_candidate_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration evidence is incomplete"
            )
        forced_false = (
            "semantic_acceptance_criteria_evaluated",
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
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
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "mechanical integration evidence cannot grant publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_AUTHORITY:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration evaluation authority is unsupported"
            )

    @property
    def evaluation_authenticated(self) -> bool:
        return _get_live_post_commit_integration_evaluation_inputs(self) is not None

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
    ) -> "PilotExactTaskPostCommitIntegrationEvaluationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration evaluation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration evaluation fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskPostCommitIntegrationEvaluationReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration evaluation JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_post_commit_integration(
    *,
    local_commit_transaction: PilotExactTaskLocalCommitTransactionReceipt,
    now_provider,
) -> PilotExactTaskPostCommitIntegrationEvaluationReceipt:
    transaction, identity, inputs = _require_live_local_commit_transaction(
        local_commit_transaction
    )

    first = _observe_exact_post_commit_state(transaction, identity, inputs)
    second = _observe_exact_post_commit_state(transaction, identity, inputs)
    if dict(first) != dict(second):
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "post-commit state changed between read-only observations"
        )
    for name in ("cached_diff_sha256", "unstaged_diff_sha256", "untracked_sha256"):
        if first[name] != _EMPTY_SHA256:
            raise PilotExactTaskPostCommitIntegrationEvaluationError(
                "post-commit integration candidate is not mechanically clean"
            )

    evaluated_at = now_provider()
    committed_time = _utc(transaction.committed_at_utc, name="committed_at_utc")
    evaluated_time = _utc(evaluated_at, name="evaluated_at_utc")
    if evaluated_time < committed_time:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "system clock moved backwards after ADR-DC-044 commit"
        )

    receipt = PilotExactTaskPostCommitIntegrationEvaluationReceipt(
        local_commit_transaction_sha256=transaction.sha256,
        local_commit_write_authorization_sha256=(
            transaction.local_commit_write_authorization_sha256
        ),
        local_commit_object_identity_sha256=transaction.local_commit_object_identity_sha256,
        post_execution_evaluation_sha256=identity.post_execution_evaluation_sha256,
        execution_nonce_sha256=transaction.execution_nonce_sha256,
        development_task_sha256=transaction.development_task_sha256,
        task_id=transaction.task_id,
        repository=transaction.repository,
        base_sha=transaction.base_sha,
        local_head_ref=transaction.local_head_ref,
        predicted_commit_sha=transaction.predicted_commit_sha,
        root_tree_sha=transaction.root_tree_sha,
        commit_payload_sha256=transaction.commit_payload_sha256,
        index_manifest_sha256=transaction.index_manifest_sha256,
        committed_at_utc=transaction.committed_at_utc,
        evaluated_at_utc=evaluated_at,
    )
    _mark_post_commit_integration_evaluation_authenticated(receipt, transaction)
    if receipt.evaluation_authenticated is not True:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "post-commit integration evaluation lost live provenance"
        )
    return receipt


def evaluate_pilot_exact_task_post_commit_integration(
    local_commit_transaction: PilotExactTaskLocalCommitTransactionReceipt,
) -> PilotExactTaskPostCommitIntegrationEvaluationReceipt:
    """Host-pinned ADR-DC-045 read-only mechanical integration evaluation."""
    try:
        return _evaluate_verified_pilot_exact_task_post_commit_integration(
            local_commit_transaction=local_commit_transaction,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPostCommitIntegrationEvaluationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPostCommitIntegrationEvaluationError(
            "host-controlled post-commit integration evaluation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCHEMA",
    "PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_AUTHORITY",
    "PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_SCOPE",
    "PilotExactTaskPostCommitIntegrationEvaluationError",
    "PilotExactTaskPostCommitIntegrationEvaluationReceipt",
    "evaluate_pilot_exact_task_post_commit_integration",
]
