"""ADR-DC-046 externally authenticated semantic acceptance and integration readiness.

This boundary accepts only the exact live ADR-DC-045 mechanical integration
candidate, binds every immutable DevelopmentTask acceptance criterion to one
canonical semantic-acceptance claim, verifies a detached Ed25519 signature using
a host-pinned public-key keyring, and then re-observes the exact local commit
twice before issuing integration-readiness evidence.

The runtime contains no private semantic-review key and grants no push, PR,
merge, release, deploy or production-activation authority.
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
from typing import Any, Mapping, Sequence

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
)
from .contract import DevelopmentTask, MergeAuthority
from . import improvement_pilot_exact_task_post_commit_integration_evaluation as evaluation_boundary
from .improvement_pilot_exact_task_post_commit_integration_evaluation import (
    PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_AUTHORITY,
    PilotExactTaskPostCommitIntegrationEvaluationReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_INTEGRATION_READINESS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-integration-readiness-receipt/v1"
)
PILOT_EXACT_TASK_INTEGRATION_READINESS_AUTHORITY = (
    "externally-reviewed-one-dc-l16-exact-integration-ready-only"
)
PILOT_EXACT_TASK_INTEGRATION_READINESS_SCOPE = (
    "semantic-acceptance-and-readiness-only-v1"
)
PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-semantic-acceptance-claim/v1"
)
PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-semantic-acceptance-keyring/v1"
)
_SEMANTIC_ACCEPTANCE_POLICY_DOMAIN = (
    b"kaliv-rsi-dc-l16-exact-task-semantic-acceptance-policy/v1\0"
)
_ACCEPTANCE_CRITERIA_DOMAIN = (
    b"kaliv-rsi-dc-l16-exact-task-acceptance-criteria/v1\0"
)
_CRITERION_DOMAIN = b"kaliv-rsi-dc-l16-exact-task-criterion/v1\0"
_MAX_KEYRING_BYTES = 1024 * 1024
_MAX_CLAIM_BYTES = 4 * 1024 * 1024
_MAX_RATIONALE_BYTES = 4096
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/"
    "rsi-pilot-exact-task-semantic-acceptance-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\ProgramData\ModelRig\DevControl\config")
    / "rsi-pilot-exact-task-semantic-acceptance-keyring-v1.json"
)

PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_POLICY = (
    "Accept only the exact live ADR-DC-045 mechanically verified local commit candidate.",
    "Evaluate every immutable DevelopmentTask acceptance criterion in exact contract order.",
    "Require every criterion to be explicitly satisfied with a non-empty rationale; uncertainty or findings are not readiness.",
    "Require a detached Ed25519 signature from a host-pinned, non-revoked external semantic-review public key.",
    "Re-observe the exact local commit twice after signature verification; any ref, object, index or worktree drift fails closed.",
    "Integration readiness grants no Git write, remote write, push, pull-request mutation, merge, release, deploy or production-activation authority.",
)


class PilotExactTaskIntegrationReadinessError(ValueError):
    """Semantic acceptance or exact integration readiness is not trustworthy."""


def _canonical(value: Mapping[str, Any] | Sequence[Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "integration readiness evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskIntegrationReadinessError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskIntegrationReadinessError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskIntegrationReadinessError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskIntegrationReadinessError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _text(value: Any, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or "\r" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise PilotExactTaskIntegrationReadinessError(f"{name} is invalid")
    return value


def pilot_exact_task_semantic_acceptance_policy_sha256() -> str:
    payload = json.dumps(
        list(PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_SEMANTIC_ACCEPTANCE_POLICY_DOMAIN + payload).hexdigest()


def _criterion_sha256(criterion: str) -> str:
    clean = _text(criterion, name="acceptance criterion", maximum=1024)
    return hashlib.sha256(_CRITERION_DOMAIN + clean.encode("utf-8")).hexdigest()


def _acceptance_criteria_sha256(criteria: tuple[str, ...]) -> str:
    if not isinstance(criteria, tuple) or not criteria:
        raise PilotExactTaskIntegrationReadinessError(
            "task acceptance criteria are unavailable"
        )
    canonical = [
        _text(item, name="acceptance criterion", maximum=1024) for item in criteria
    ]
    if len(canonical) != len(set(canonical)):
        raise PilotExactTaskIntegrationReadinessError(
            "task acceptance criteria are duplicated"
        )
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_ACCEPTANCE_CRITERIA_DOMAIN + payload).hexdigest()


def _development_task_sha256(task: DevelopmentTask) -> str:
    if not isinstance(task, DevelopmentTask):
        raise PilotExactTaskIntegrationReadinessError(
            "validated DevelopmentTask is required"
        )
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotExactTaskSemanticCriterionAssessment:
    criterion_sha256: str
    rationale: str
    outcome: str = "satisfied"

    def __post_init__(self) -> None:
        _hex64(self.criterion_sha256, name="criterion_sha256")
        _text(
            self.rationale,
            name="criterion rationale",
            maximum=_MAX_RATIONALE_BYTES,
        )
        if self.outcome != "satisfied":
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness requires every criterion satisfied"
            )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskSemanticCriterionAssessment":
        if not isinstance(value, Mapping) or set(value) != {
            "criterion_sha256",
            "rationale",
            "outcome",
        }:
            raise PilotExactTaskIntegrationReadinessError(
                "semantic criterion assessment fields mismatch"
            )
        return cls(
            criterion_sha256=value["criterion_sha256"],
            rationale=value["rationale"],
            outcome=value["outcome"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_sha256": self.criterion_sha256,
            "rationale": self.rationale,
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class PilotExactTaskSemanticAcceptanceClaim:
    post_commit_integration_evaluation_sha256: str
    local_commit_transaction_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    predicted_commit_sha: str
    candidate_patch_sha256: str
    acceptance_criteria_sha256: str
    semantic_acceptance_policy_sha256: str
    criterion_assessments: tuple[PilotExactTaskSemanticCriterionAssessment, ...]
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    reviewed_at_utc: str
    decision: str = "approve"
    all_acceptance_criteria_satisfied: bool = True
    remote_publication_authorized: bool = False
    schema: str = PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_CLAIM_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_CLAIM_SCHEMA:
            raise PilotExactTaskIntegrationReadinessError(
                "semantic acceptance claim schema is unsupported"
            )
        for name in (
            "post_commit_integration_evaluation_sha256",
            "local_commit_transaction_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "acceptance_criteria_sha256",
            "semantic_acceptance_policy_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskIntegrationReadinessError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskIntegrationReadinessError("repository is invalid")
        if (
            not isinstance(self.reviewer_actor_id, str)
            or _ACTOR_ID.fullmatch(self.reviewer_actor_id) is None
        ):
            raise PilotExactTaskIntegrationReadinessError(
                "semantic reviewer actor is invalid"
            )
        for name in ("reviewer_system_id", "reviewer_key_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise PilotExactTaskIntegrationReadinessError(f"{name} is invalid")
        _utc(self.reviewed_at_utc, name="reviewed_at_utc")
        if self.decision != "approve":
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness requires semantic approval"
            )
        if self.all_acceptance_criteria_satisfied is not True:
            raise PilotExactTaskIntegrationReadinessError(
                "all acceptance criteria must be satisfied"
            )
        if self.remote_publication_authorized is not False:
            raise PilotExactTaskIntegrationReadinessError(
                "semantic acceptance cannot grant remote publication authority"
            )
        if (
            self.semantic_acceptance_policy_sha256
            != pilot_exact_task_semantic_acceptance_policy_sha256()
        ):
            raise PilotExactTaskIntegrationReadinessError(
                "semantic acceptance policy identity is unsupported"
            )
        if (
            not isinstance(self.criterion_assessments, tuple)
            or not self.criterion_assessments
            or any(
                type(item) is not PilotExactTaskSemanticCriterionAssessment
                for item in self.criterion_assessments
            )
        ):
            raise PilotExactTaskIntegrationReadinessError(
                "semantic criterion assessments are invalid"
            )
        hashes = tuple(item.criterion_sha256 for item in self.criterion_assessments)
        if len(hashes) != len(set(hashes)):
            raise PilotExactTaskIntegrationReadinessError(
                "semantic criterion assessments are duplicated"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskSemanticAcceptanceClaim":
        fields = {
            "schema",
            "post_commit_integration_evaluation_sha256",
            "local_commit_transaction_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "task_id",
            "repository",
            "base_sha",
            "predicted_commit_sha",
            "candidate_patch_sha256",
            "acceptance_criteria_sha256",
            "semantic_acceptance_policy_sha256",
            "criterion_assessments",
            "reviewer_actor_id",
            "reviewer_system_id",
            "reviewer_key_id",
            "reviewed_at_utc",
            "decision",
            "all_acceptance_criteria_satisfied",
            "remote_publication_authorized",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise PilotExactTaskIntegrationReadinessError(
                "semantic acceptance claim fields mismatch"
            )
        assessments = value["criterion_assessments"]
        if not isinstance(assessments, list):
            raise PilotExactTaskIntegrationReadinessError(
                "semantic criterion assessments must be an array"
            )
        return cls(
            schema=value["schema"],
            post_commit_integration_evaluation_sha256=value[
                "post_commit_integration_evaluation_sha256"
            ],
            local_commit_transaction_sha256=value["local_commit_transaction_sha256"],
            execution_nonce_sha256=value["execution_nonce_sha256"],
            development_task_sha256=value["development_task_sha256"],
            task_id=value["task_id"],
            repository=value["repository"],
            base_sha=value["base_sha"],
            predicted_commit_sha=value["predicted_commit_sha"],
            candidate_patch_sha256=value["candidate_patch_sha256"],
            acceptance_criteria_sha256=value["acceptance_criteria_sha256"],
            semantic_acceptance_policy_sha256=value[
                "semantic_acceptance_policy_sha256"
            ],
            criterion_assessments=tuple(
                PilotExactTaskSemanticCriterionAssessment.from_mapping(item)
                for item in assessments
            ),
            reviewer_actor_id=value["reviewer_actor_id"],
            reviewer_system_id=value["reviewer_system_id"],
            reviewer_key_id=value["reviewer_key_id"],
            reviewed_at_utc=value["reviewed_at_utc"],
            decision=value["decision"],
            all_acceptance_criteria_satisfied=value[
                "all_acceptance_criteria_satisfied"
            ],
            remote_publication_authorized=value["remote_publication_authorized"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "post_commit_integration_evaluation_sha256": (
                self.post_commit_integration_evaluation_sha256
            ),
            "local_commit_transaction_sha256": self.local_commit_transaction_sha256,
            "execution_nonce_sha256": self.execution_nonce_sha256,
            "development_task_sha256": self.development_task_sha256,
            "task_id": self.task_id,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "predicted_commit_sha": self.predicted_commit_sha,
            "candidate_patch_sha256": self.candidate_patch_sha256,
            "acceptance_criteria_sha256": self.acceptance_criteria_sha256,
            "semantic_acceptance_policy_sha256": (
                self.semantic_acceptance_policy_sha256
            ),
            "criterion_assessments": [
                item.to_dict() for item in self.criterion_assessments
            ],
            "reviewer_actor_id": self.reviewer_actor_id,
            "reviewer_system_id": self.reviewer_system_id,
            "reviewer_key_id": self.reviewer_key_id,
            "reviewed_at_utc": self.reviewed_at_utc,
            "decision": self.decision,
            "all_acceptance_criteria_satisfied": (
                self.all_acceptance_criteria_satisfied
            ),
            "remote_publication_authorized": self.remote_publication_authorized,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _require_live_evaluation(
    value: Any,
) -> tuple[
    PilotExactTaskPostCommitIntegrationEvaluationReceipt,
    Mapping[str, Any],
    DevelopmentTask,
]:
    if type(value) is not PilotExactTaskPostCommitIntegrationEvaluationReceipt:
        raise PilotExactTaskIntegrationReadinessError(
            "exact ADR-DC-045 post-commit integration evaluation is required"
        )
    try:
        replayed = (
            PilotExactTaskPostCommitIntegrationEvaluationReceipt.from_mapping(
                value.to_dict()
            )
        )
    except Exception as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "ADR-DC-045 integration evaluation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskIntegrationReadinessError(
            "ADR-DC-045 integration evaluation identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_POST_COMMIT_INTEGRATION_EVALUATION_AUTHORITY
        or value.evaluation_authenticated is not True
        or value.local_commit_transaction_authenticated is not True
        or value.local_commit_created is not True
        or value.local_head_ref_verified is not True
        or value.commit_object_verified is not True
        or value.commit_payload_verified is not True
        or value.parent_base_verified is not True
        or value.root_tree_verified is not True
        or value.index_manifest_preserved is not True
        or value.index_clean is not True
        or value.worktree_clean is not True
        or value.double_observation_matched is not True
        or value.mechanical_integration_evaluation_passed is not True
        or value.integration_candidate_verified is not True
        or value.semantic_acceptance_criteria_evaluated is not False
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
        raise PilotExactTaskIntegrationReadinessError(
            "readiness requires one live inert ADR-DC-045 mechanical evaluation"
        )

    inputs = evaluation_boundary._get_live_post_commit_integration_evaluation_inputs(
        value
    )
    if inputs is None:
        raise PilotExactTaskIntegrationReadinessError(
            "ADR-DC-045 live integration inputs are unavailable"
        )
    transaction = inputs.get("local_commit_transaction")
    identity = inputs.get("local_commit_object_identity")
    task = inputs.get("task")
    if (
        transaction is None
        or identity is None
        or type(task) is not DevelopmentTask
        or getattr(transaction, "sha256", None)
        != value.local_commit_transaction_sha256
        or getattr(identity, "sha256", None)
        != value.local_commit_object_identity_sha256
        or getattr(identity, "identity_authenticated", None) is not True
        or _development_task_sha256(task) != value.development_task_sha256
        or task.task_id != value.task_id
        or task.repository != value.repository
        or task.base_sha != value.base_sha
        or getattr(identity, "predicted_commit_sha", None)
        != value.predicted_commit_sha
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "ADR-DC-045 evaluation is not bound to its exact live task/commit"
        )
    if task.merge_authority is not MergeAuthority.HUMAN:
        raise PilotExactTaskIntegrationReadinessError(
            "merge authority must remain human"
        )
    return value, inputs, task


def _expected_assessment_hashes(task: DevelopmentTask) -> tuple[str, ...]:
    return tuple(_criterion_sha256(item) for item in task.acceptance_criteria)


def _validate_claim_binding(
    *,
    claim: PilotExactTaskSemanticAcceptanceClaim,
    evaluation: PilotExactTaskPostCommitIntegrationEvaluationReceipt,
    inputs: Mapping[str, Any],
    task: DevelopmentTask,
) -> None:
    identity = inputs["local_commit_object_identity"]
    expected_hashes = _expected_assessment_hashes(task)
    actual_hashes = tuple(
        item.criterion_sha256 for item in claim.criterion_assessments
    )
    if (
        claim.post_commit_integration_evaluation_sha256 != evaluation.sha256
        or claim.local_commit_transaction_sha256
        != evaluation.local_commit_transaction_sha256
        or claim.execution_nonce_sha256 != evaluation.execution_nonce_sha256
        or claim.development_task_sha256 != evaluation.development_task_sha256
        or claim.task_id != task.task_id
        or claim.repository != task.repository
        or claim.base_sha != task.base_sha
        or claim.predicted_commit_sha != evaluation.predicted_commit_sha
        or claim.candidate_patch_sha256
        != getattr(identity, "candidate_patch_sha256", None)
        or claim.acceptance_criteria_sha256
        != _acceptance_criteria_sha256(task.acceptance_criteria)
        or actual_hashes != expected_hashes
        or len(claim.criterion_assessments) != len(task.acceptance_criteria)
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance claim is not bound to the exact candidate/task"
        )


def build_pilot_exact_task_semantic_acceptance_payload(
    post_commit_integration_evaluation: PilotExactTaskPostCommitIntegrationEvaluationReceipt,
    criterion_assessments: Sequence[PilotExactTaskSemanticCriterionAssessment],
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
    reviewed_at_utc: str,
) -> bytes:
    """Build exact canonical bytes for an external semantic reviewer to sign."""
    evaluation, inputs, task = _require_live_evaluation(
        post_commit_integration_evaluation
    )
    assessments = tuple(criterion_assessments)
    claim = PilotExactTaskSemanticAcceptanceClaim(
        post_commit_integration_evaluation_sha256=evaluation.sha256,
        local_commit_transaction_sha256=evaluation.local_commit_transaction_sha256,
        execution_nonce_sha256=evaluation.execution_nonce_sha256,
        development_task_sha256=evaluation.development_task_sha256,
        task_id=evaluation.task_id,
        repository=evaluation.repository,
        base_sha=evaluation.base_sha,
        predicted_commit_sha=evaluation.predicted_commit_sha,
        candidate_patch_sha256=inputs[
            "local_commit_object_identity"
        ].candidate_patch_sha256,
        acceptance_criteria_sha256=_acceptance_criteria_sha256(
            task.acceptance_criteria
        ),
        semantic_acceptance_policy_sha256=(
            pilot_exact_task_semantic_acceptance_policy_sha256()
        ),
        criterion_assessments=assessments,
        reviewer_actor_id=reviewer_actor_id,
        reviewer_system_id=reviewer_system_id,
        reviewer_key_id=reviewer_key_id,
        reviewed_at_utc=reviewed_at_utc,
    )
    _validate_claim_binding(
        claim=claim,
        evaluation=evaluation,
        inputs=inputs,
        task=task,
    )
    payload = claim.canonical_json().encode("utf-8")
    if not payload or len(payload) > _MAX_CLAIM_BYTES:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance payload exceeds its byte bound"
        )
    return payload


def _parse_semantic_acceptance_payload(
    payload: bytes,
) -> PilotExactTaskSemanticAcceptanceClaim:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_CLAIM_BYTES
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance payload is invalid or oversized"
        )
    try:
        parsed = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance payload is not valid UTF-8 JSON"
        ) from exc
    claim = PilotExactTaskSemanticAcceptanceClaim.from_mapping(parsed)
    if payload != claim.canonical_json().encode("utf-8"):
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance payload is not canonical JSON"
        )
    return claim


def _parse_trusted_keyring_payload(
    payload: bytes,
) -> tuple[Ed25519AuthorityVerifier, str]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_KEYRING_BYTES
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance public-key keyring is invalid or oversized"
        )
    try:
        parsed = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance public-key keyring JSON is invalid"
        ) from exc
    if not isinstance(parsed, Mapping) or set(parsed) != {
        "schema",
        "minimum_keyring_epoch",
        "keys",
    }:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance public-key keyring fields mismatch"
        )
    if parsed["schema"] != PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_KEYRING_SCHEMA:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance public-key keyring schema is unsupported"
        )
    epoch = parsed["minimum_keyring_epoch"]
    keys_raw = parsed["keys"]
    if (
        isinstance(epoch, bool)
        or not isinstance(epoch, int)
        or epoch < 1
        or not isinstance(keys_raw, list)
        or not keys_raw
        or len(keys_raw) > 64
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance public-key keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for raw in keys_raw:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
        except Exception as exc:
            raise PilotExactTaskIntegrationReadinessError(
                "semantic acceptance trusted key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskIntegrationReadinessError(
                "semantic acceptance trusted key IDs are duplicated"
            )
        keys[key.key_id] = key
    canonical_payload = _canonical(
        {
            "schema": PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [key.to_dict() for key in keys.values()],
        }
    ).encode("utf-8")
    if payload != canonical_payload:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance public-key keyring is not canonical JSON"
        )
    try:
        verifier = Ed25519AuthorityVerifier(
            keys,
            minimum_keyring_epoch=epoch,
        )
    except Exception as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance public-key verifier construction failed"
        ) from exc
    return verifier, hashlib.sha256(payload).hexdigest()


def _read_host_keyring(path: Path) -> tuple[Ed25519AuthorityVerifier, str, Path, bytes]:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or _has_linkish_component(candidate)
        or not candidate.is_file()
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance keyring path is unsafe"
        )
    try:
        payload = candidate.read_bytes()
    except OSError as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance keyring cannot be read"
        ) from exc
    verifier, digest = _parse_trusted_keyring_payload(payload)
    return verifier, digest, candidate, payload


def _canonical_keyring() -> tuple[
    Ed25519AuthorityVerifier,
    str,
    Path,
    bytes,
]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_KEYRING
        elif os.name == "nt":
            path = _WINDOWS_KEYRING
        else:
            raise PilotExactTaskIntegrationReadinessError(
                "semantic acceptance keyring is unsupported on this platform"
            )
        _require_host_controlled_ledger_root(path.parent)
        return _read_host_keyring(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance keyring is not host-admin controlled"
        ) from exc


def _fresh_revalidate_post_commit(
    *,
    evaluation: PilotExactTaskPostCommitIntegrationEvaluationReceipt,
    inputs: Mapping[str, Any],
) -> None:
    transaction = inputs.get("local_commit_transaction")
    identity = inputs.get("local_commit_object_identity")
    if transaction is None or identity is None:
        raise PilotExactTaskIntegrationReadinessError(
            "live post-commit provenance is incomplete"
        )
    try:
        first = evaluation_boundary._observe_exact_post_commit_state(
            transaction,
            identity,
            inputs,
        )
        second = evaluation_boundary._observe_exact_post_commit_state(
            transaction,
            identity,
            inputs,
        )
    except Exception as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "fresh exact post-commit readiness revalidation failed"
        ) from exc
    if dict(first) != dict(second):
        raise PilotExactTaskIntegrationReadinessError(
            "post-commit state changed during readiness revalidation"
        )


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            str,
        ],
    ] = {}

    def mark(
        receipt: Any,
        evaluation: PilotExactTaskPostCommitIntegrationEvaluationReceipt,
        *,
        trusted_keyring_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(evaluation),
            trusted_keyring_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, evaluation_ref, keyring_digest = entry
        evaluation = evaluation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or evaluation is None
            or evaluation.evaluation_authenticated is not True
            or receipt.sha256 != digest
            or receipt.post_commit_integration_evaluation_sha256
            != evaluation.sha256
            or receipt.trusted_reviewer_keyring_sha256 != keyring_digest
        ):
            return None
        inputs = evaluation_boundary._get_live_post_commit_integration_evaluation_inputs(
            evaluation
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["post_commit_integration_evaluation"] = evaluation
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_integration_readiness_authenticated,
    _get_live_integration_readiness_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskIntegrationReadinessReceipt:
    post_commit_integration_evaluation_sha256: str
    local_commit_transaction_sha256: str
    local_commit_object_identity_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    local_head_ref: str
    predicted_commit_sha: str
    root_tree_sha: str
    commit_payload_sha256: str
    candidate_patch_sha256: str
    acceptance_criteria_sha256: str
    semantic_acceptance_policy_sha256: str
    semantic_acceptance_claim_sha256: str
    semantic_acceptance_signature_sha256: str
    trusted_reviewer_keyring_sha256: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    reviewed_at_utc: str
    readiness_evaluated_at_utc: str
    local_commit_created: bool = True
    mechanical_integration_evaluation_authenticated: bool = True
    mechanical_integration_evaluation_passed: bool = True
    integration_candidate_verified: bool = True
    semantic_acceptance_criteria_evaluated: bool = True
    semantic_acceptance_criteria_all_satisfied: bool = True
    trusted_external_semantic_review_verified: bool = True
    fresh_post_commit_state_revalidated: bool = True
    integration_ready: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    readiness_scope: str = PILOT_EXACT_TASK_INTEGRATION_READINESS_SCOPE
    authority: str = PILOT_EXACT_TASK_INTEGRATION_READINESS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_INTEGRATION_READINESS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_INTEGRATION_READINESS_SCHEMA:
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness schema is unsupported"
            )
        if self.readiness_scope != PILOT_EXACT_TASK_INTEGRATION_READINESS_SCOPE:
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness scope is unsupported"
            )
        for name in (
            "post_commit_integration_evaluation_sha256",
            "local_commit_transaction_sha256",
            "local_commit_object_identity_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "commit_payload_sha256",
            "candidate_patch_sha256",
            "acceptance_criteria_sha256",
            "semantic_acceptance_policy_sha256",
            "semantic_acceptance_claim_sha256",
            "semantic_acceptance_signature_sha256",
            "trusted_reviewer_keyring_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskIntegrationReadinessError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskIntegrationReadinessError("repository is invalid")
        if (
            not isinstance(self.reviewer_actor_id, str)
            or _ACTOR_ID.fullmatch(self.reviewer_actor_id) is None
        ):
            raise PilotExactTaskIntegrationReadinessError(
                "reviewer_actor_id is invalid"
            )
        for name in ("reviewer_system_id", "reviewer_key_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise PilotExactTaskIntegrationReadinessError(f"{name} is invalid")
        reviewed = _utc(self.reviewed_at_utc, name="reviewed_at_utc")
        ready = _utc(
            self.readiness_evaluated_at_utc,
            name="readiness_evaluated_at_utc",
        )
        if ready < reviewed:
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness predates semantic review"
            )
        required_true = (
            "local_commit_created",
            "mechanical_integration_evaluation_authenticated",
            "mechanical_integration_evaluation_passed",
            "integration_candidate_verified",
            "semantic_acceptance_criteria_evaluated",
            "semantic_acceptance_criteria_all_satisfied",
            "trusted_external_semantic_review_verified",
            "fresh_post_commit_state_revalidated",
            "integration_ready",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness evidence is incomplete"
            )
        forced_false = (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
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
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness cannot grant publication or activation authority"
            )
        if self.authority != PILOT_EXACT_TASK_INTEGRATION_READINESS_AUTHORITY:
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness authority is unsupported"
            )

    @property
    def readiness_authenticated(self) -> bool:
        return _get_live_integration_readiness_inputs(self) is not None

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
    ) -> "PilotExactTaskIntegrationReadinessReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskIntegrationReadinessReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskIntegrationReadinessError(
                "integration readiness JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_integration_readiness(
    *,
    post_commit_integration_evaluation: PilotExactTaskPostCommitIntegrationEvaluationReceipt,
    semantic_acceptance_payload: bytes,
    signature: DetachedEd25519AuthoritySignature,
    authority_verifier: Ed25519AuthorityVerifier,
    trusted_reviewer_keyring_sha256: str,
    now_provider,
) -> PilotExactTaskIntegrationReadinessReceipt:
    evaluation, inputs, task = _require_live_evaluation(
        post_commit_integration_evaluation
    )
    if not isinstance(authority_verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskIntegrationReadinessError(
            "Ed25519 semantic-review authority verifier is required"
        )
    _hex64(
        trusted_reviewer_keyring_sha256,
        name="trusted_reviewer_keyring_sha256",
    )
    claim = _parse_semantic_acceptance_payload(semantic_acceptance_payload)
    _validate_claim_binding(
        claim=claim,
        evaluation=evaluation,
        inputs=inputs,
        task=task,
    )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotExactTaskIntegrationReadinessError(
            "detached Ed25519 semantic acceptance signature is required"
        )
    if (
        signature.key_id != claim.reviewer_key_id
        or signature.issuer_actor_id != claim.reviewer_actor_id
        or signature.issuer_system_id != claim.reviewer_system_id
        or signature.signed_at_utc != claim.reviewed_at_utc
        or signature.custody_policy_sha256
        != asymmetric_authority_key_custody_policy_sha256()
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance signature identity does not match the claim"
        )

    readiness_at = now_provider()
    reviewed_time = _utc(claim.reviewed_at_utc, name="reviewed_at_utc")
    readiness_time = _utc(readiness_at, name="readiness_evaluated_at_utc")
    mechanically_evaluated = _utc(
        evaluation.evaluated_at_utc,
        name="ADR-DC-045 evaluated_at_utc",
    )
    if reviewed_time < mechanically_evaluated:
        raise PilotExactTaskIntegrationReadinessError(
            "semantic acceptance predates ADR-DC-045 mechanical evaluation"
        )
    if readiness_time < reviewed_time:
        raise PilotExactTaskIntegrationReadinessError(
            "system clock moved backwards after semantic acceptance"
        )

    try:
        authority_verifier.verify(
            payload=semantic_acceptance_payload,
            signature=signature,
            at_utc=readiness_at,
        )
    except Exception as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "trusted external semantic acceptance signature verification failed"
        ) from exc

    _fresh_revalidate_post_commit(
        evaluation=evaluation,
        inputs=inputs,
    )
    evaluation_again, inputs_again, task_again = _require_live_evaluation(evaluation)
    if (
        evaluation_again is not evaluation
        or task_again is not task
        or inputs_again["local_commit_object_identity"]
        is not inputs["local_commit_object_identity"]
    ):
        raise PilotExactTaskIntegrationReadinessError(
            "live integration candidate changed during semantic readiness"
        )

    identity = inputs["local_commit_object_identity"]
    receipt = PilotExactTaskIntegrationReadinessReceipt(
        post_commit_integration_evaluation_sha256=evaluation.sha256,
        local_commit_transaction_sha256=evaluation.local_commit_transaction_sha256,
        local_commit_object_identity_sha256=(
            evaluation.local_commit_object_identity_sha256
        ),
        execution_nonce_sha256=evaluation.execution_nonce_sha256,
        development_task_sha256=evaluation.development_task_sha256,
        task_id=evaluation.task_id,
        repository=evaluation.repository,
        base_sha=evaluation.base_sha,
        local_head_ref=evaluation.local_head_ref,
        predicted_commit_sha=evaluation.predicted_commit_sha,
        root_tree_sha=evaluation.root_tree_sha,
        commit_payload_sha256=evaluation.commit_payload_sha256,
        candidate_patch_sha256=identity.candidate_patch_sha256,
        acceptance_criteria_sha256=claim.acceptance_criteria_sha256,
        semantic_acceptance_policy_sha256=(
            claim.semantic_acceptance_policy_sha256
        ),
        semantic_acceptance_claim_sha256=claim.sha256,
        semantic_acceptance_signature_sha256=signature.sha256,
        trusted_reviewer_keyring_sha256=trusted_reviewer_keyring_sha256,
        reviewer_actor_id=claim.reviewer_actor_id,
        reviewer_system_id=claim.reviewer_system_id,
        reviewer_key_id=claim.reviewer_key_id,
        reviewed_at_utc=claim.reviewed_at_utc,
        readiness_evaluated_at_utc=readiness_at,
    )
    _mark_integration_readiness_authenticated(
        receipt,
        evaluation,
        trusted_keyring_sha256=trusted_reviewer_keyring_sha256,
    )
    if receipt.readiness_authenticated is not True:
        raise PilotExactTaskIntegrationReadinessError(
            "integration readiness lost live provenance"
        )
    return receipt


def evaluate_pilot_exact_task_integration_readiness(
    post_commit_integration_evaluation: PilotExactTaskPostCommitIntegrationEvaluationReceipt,
    semantic_acceptance_payload: bytes,
    signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskIntegrationReadinessReceipt:
    """Host-pinned ADR-DC-046 semantic acceptance and integration readiness."""
    try:
        verifier, keyring_sha256, _path, _payload = _canonical_keyring()
        return _evaluate_verified_pilot_exact_task_integration_readiness(
            post_commit_integration_evaluation=post_commit_integration_evaluation,
            semantic_acceptance_payload=semantic_acceptance_payload,
            signature=signature,
            authority_verifier=verifier,
            trusted_reviewer_keyring_sha256=keyring_sha256,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskIntegrationReadinessError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskIntegrationReadinessError(
            "host-controlled exact integration readiness failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_INTEGRATION_READINESS_SCHEMA",
    "PILOT_EXACT_TASK_INTEGRATION_READINESS_AUTHORITY",
    "PILOT_EXACT_TASK_INTEGRATION_READINESS_SCOPE",
    "PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_CLAIM_SCHEMA",
    "PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_KEYRING_SCHEMA",
    "PILOT_EXACT_TASK_SEMANTIC_ACCEPTANCE_POLICY",
    "PilotExactTaskIntegrationReadinessError",
    "PilotExactTaskSemanticCriterionAssessment",
    "PilotExactTaskSemanticAcceptanceClaim",
    "PilotExactTaskIntegrationReadinessReceipt",
    "pilot_exact_task_semantic_acceptance_policy_sha256",
    "build_pilot_exact_task_semantic_acceptance_payload",
    "evaluate_pilot_exact_task_integration_readiness",
]
