"""Independent authenticated semantic review over one immutable patch and Tier-A receipt."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contract import DevelopmentTask
from .tier_a_authority import tier_a_toolhost_sha256
from .tier_a_command_receipt import TierACommandReceipt

SEMANTIC_REVIEW_REQUEST_SCHEMA = "kaliv-development-semantic-review-request/v1"
SEMANTIC_REVIEW_VERDICT_SCHEMA = "kaliv-development-semantic-review-verdict/v1"
SIGNED_SEMANTIC_REVIEW_VERDICT_SCHEMA = (
    "kaliv-development-signed-semantic-review-verdict/v1"
)
SEMANTIC_REVIEW_SIGNATURE_ALGORITHM = "hmac-sha256"
_SEMANTIC_REVIEW_SIGNATURE_DOMAIN = b"kaliv-semantic-review-verdict-signature/v1\0"
_SEMANTIC_REVIEW_POLICY_DOMAIN = b"kaliv-semantic-review-policy/v1\0"
_CRITERION_DOMAIN = b"kaliv-semantic-review-criterion/v1\0"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_MAX_PATCH_BYTES = 32 * 1024 * 1024
_MAX_FINDINGS = 256
_MAX_CRITERIA = 256

SEMANTIC_REVIEW_POLICY = (
    "Use only the canonical semantic-review request; do not rely on mutable workspace state or unstated external facts.",
    "Evaluate every acceptance criterion against the exact staged patch and the complete Tier-A command receipt.",
    "Inspect correctness, security, regression risk, maintainability and evidence gaps that are material to the task.",
    "Treat uncertainty, missing evidence or contradictory evidence as not_satisfied or uncertain rather than approving.",
    "Approve only when every acceptance criterion is satisfied and no material finding remains.",
)


class SemanticReviewError(ValueError):
    """Semantic review evidence is malformed, unauthenticated or mismatched."""


class SemanticReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


class CriterionOutcome(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    UNCERTAIN = "uncertain"


class FindingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clean_text(value: Any, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise SemanticReviewError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise SemanticReviewError(f"{name} is invalid")
    return value


def _strict(value: Any, *, name: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise SemanticReviewError(f"{name} fields mismatch")
    return value


def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        is_junction = getattr(current, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        if current.parent == current:
            return False
        current = current.parent


def semantic_review_policy_sha256() -> str:
    payload = json.dumps(
        list(SEMANTIC_REVIEW_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(_SEMANTIC_REVIEW_POLICY_DOMAIN + payload)


def criterion_sha256(criterion: str) -> str:
    clean = _clean_text(
        criterion,
        name="acceptance criterion",
        maximum=1_024,
    )
    return _sha256_bytes(_CRITERION_DOMAIN + clean.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class SemanticReviewRequest:
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    developer_actor_id: str
    command_id: str
    execution_authority_sha256: str
    review_policy_sha256: str
    staged_patch: bytes
    staged_patch_sha256: str
    staged_patch_bytes: int
    acceptance_criteria: tuple[str, ...]
    receipt: TierACommandReceipt
    receipt_sha256: str
    schema: str = SEMANTIC_REVIEW_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SEMANTIC_REVIEW_REQUEST_SCHEMA:
            raise SemanticReviewError("unsupported semantic review request schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise SemanticReviewError("semantic review task id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise SemanticReviewError("semantic review repository is invalid")
        if (
            not isinstance(self.developer_actor_id, str)
            or _ACTOR_ID.fullmatch(self.developer_actor_id) is None
        ):
            raise SemanticReviewError("developer actor id is invalid")
        if (
            not isinstance(self.command_id, str)
            or _COMMAND_ID.fullmatch(self.command_id) is None
        ):
            raise SemanticReviewError("semantic review command id is invalid")
        _hex(self.task_sha256, name="semantic review task hash", pattern=_HEX64)
        _hex(self.base_sha, name="semantic review base SHA", pattern=_HEX40)
        _hex(
            self.execution_authority_sha256,
            name="execution authority hash",
            pattern=_HEX64,
        )
        _hex(
            self.review_policy_sha256,
            name="semantic review policy hash",
            pattern=_HEX64,
        )
        _hex(
            self.staged_patch_sha256,
            name="staged patch hash",
            pattern=_HEX64,
        )
        _hex(self.receipt_sha256, name="Tier-A receipt hash", pattern=_HEX64)
        if not isinstance(self.staged_patch, bytes):
            raise SemanticReviewError("staged patch must be exact bytes")
        if (
            isinstance(self.staged_patch_bytes, bool)
            or not isinstance(self.staged_patch_bytes, int)
            or not 1 <= self.staged_patch_bytes <= _MAX_PATCH_BYTES
        ):
            raise SemanticReviewError("staged patch byte count is invalid")
        if len(self.staged_patch) != self.staged_patch_bytes:
            raise SemanticReviewError("staged patch byte count does not match its bytes")
        if _sha256_bytes(self.staged_patch) != self.staged_patch_sha256:
            raise SemanticReviewError("staged patch bytes do not match their hash")
        if self.review_policy_sha256 != semantic_review_policy_sha256():
            raise SemanticReviewError("semantic review policy identity is unsupported")
        if (
            not isinstance(self.acceptance_criteria, tuple)
            or not self.acceptance_criteria
            or len(self.acceptance_criteria) > _MAX_CRITERIA
        ):
            raise SemanticReviewError(
                "semantic review acceptance criteria are invalid"
            )
        criteria = tuple(
            _clean_text(item, name="acceptance criterion", maximum=1_024)
            for item in self.acceptance_criteria
        )
        if criteria != self.acceptance_criteria or len(criteria) != len(set(criteria)):
            raise SemanticReviewError(
                "semantic review acceptance criteria are invalid or duplicated"
            )
        if not isinstance(self.receipt, TierACommandReceipt):
            raise SemanticReviewError("semantic review receipt is invalid")
        if self.receipt.sha256 != self.receipt_sha256:
            raise SemanticReviewError("semantic review receipt hash is inconsistent")
        self._verify_receipt_binding()

    def _verify_receipt_binding(self) -> None:
        receipt = self.receipt
        if (
            receipt.task_id != self.task_id
            or receipt.task_sha256 != self.task_sha256
            or receipt.base_sha != self.base_sha
            or receipt.command_id != self.command_id
        ):
            raise SemanticReviewError(
                "semantic review receipt is not bound to the request identity"
            )
        if (
            not receipt.passed
            or not receipt.workspace_unchanged
            or receipt.workspace_reset_performed
            or receipt.workspace_reset is not None
            or not receipt.tier_a_result.passed
        ):
            raise SemanticReviewError(
                "semantic review requires one completed passing Tier-A receipt"
            )
        before = receipt.workspace_before
        after = receipt.workspace_after
        if before.sha256 != after.sha256:
            raise SemanticReviewError(
                "semantic review receipt workspace snapshots are not identical"
            )
        for snapshot in (before, after):
            if (
                snapshot.head_sha != self.base_sha
                or snapshot.staged_patch_sha256 != self.staged_patch_sha256
                or snapshot.staged_patch_bytes != self.staged_patch_bytes
                or snapshot.unstaged_patch_bytes
                or snapshot.untracked_path_count
            ):
                raise SemanticReviewError(
                    "semantic review patch does not match the Tier-A Git evidence"
                )

    @classmethod
    def from_evidence(
        cls,
        *,
        task: DevelopmentTask,
        developer_actor_id: str,
        staged_patch: bytes,
        receipt: TierACommandReceipt,
        control_plane_root: Path,
    ) -> "SemanticReviewRequest":
        if not isinstance(task, DevelopmentTask):
            raise SemanticReviewError(
                "semantic review requires a validated development task"
            )
        if (
            not isinstance(developer_actor_id, str)
            or _ACTOR_ID.fullmatch(developer_actor_id) is None
        ):
            raise SemanticReviewError("developer actor id is invalid")
        if not isinstance(staged_patch, bytes):
            raise SemanticReviewError("staged patch must be exact bytes")
        task_sha = _sha256_bytes(task.canonical_json().encode("utf-8"))
        if (
            receipt.task_id != task.task_id
            or receipt.task_sha256 != task_sha
            or receipt.base_sha != task.base_sha
            or receipt.command_id not in task.allowed_command_ids
            or tuple(task.required_tests) != tuple(task.allowed_command_ids)
            or len(task.allowed_command_ids) != 1
            or receipt.command_id != task.allowed_command_ids[0]
        ):
            raise SemanticReviewError(
                "semantic review task and receipt identities do not match"
            )
        authority = tier_a_toolhost_sha256(Path(control_plane_root))
        return cls(
            task_id=task.task_id,
            task_sha256=task_sha,
            repository=task.repository,
            base_sha=task.base_sha,
            developer_actor_id=developer_actor_id,
            command_id=receipt.command_id,
            execution_authority_sha256=authority,
            review_policy_sha256=semantic_review_policy_sha256(),
            staged_patch=staged_patch,
            staged_patch_sha256=_sha256_bytes(staged_patch),
            staged_patch_bytes=len(staged_patch),
            acceptance_criteria=task.acceptance_criteria,
            receipt=receipt,
            receipt_sha256=receipt.sha256,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "SemanticReviewRequest":
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "repository",
            "base_sha",
            "developer_actor_id",
            "command_id",
            "execution_authority_sha256",
            "review_policy_sha256",
            "staged_patch_base64",
            "staged_patch_sha256",
            "staged_patch_bytes",
            "acceptance_criteria",
            "receipt",
            "receipt_sha256",
        }
        data = _strict(
            value,
            name="semantic review request",
            fields=fields,
        )
        encoded = data["staged_patch_base64"]
        if not isinstance(encoded, str):
            raise SemanticReviewError("staged patch base64 is invalid")
        try:
            staged_patch = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError) as exc:
            raise SemanticReviewError("staged patch base64 is invalid") from exc
        criteria = data["acceptance_criteria"]
        if not isinstance(criteria, list):
            raise SemanticReviewError(
                "semantic review acceptance criteria must be an array"
            )
        return cls(
            schema=data["schema"],
            task_id=data["task_id"],
            task_sha256=data["task_sha256"],
            repository=data["repository"],
            base_sha=data["base_sha"],
            developer_actor_id=data["developer_actor_id"],
            command_id=data["command_id"],
            execution_authority_sha256=data["execution_authority_sha256"],
            review_policy_sha256=data["review_policy_sha256"],
            staged_patch=staged_patch,
            staged_patch_sha256=data["staged_patch_sha256"],
            staged_patch_bytes=data["staged_patch_bytes"],
            acceptance_criteria=tuple(criteria),
            receipt=TierACommandReceipt.from_mapping(data["receipt"]),
            receipt_sha256=data["receipt_sha256"],
        )

    def verify_task(self, task: DevelopmentTask) -> None:
        if not isinstance(task, DevelopmentTask):
            raise SemanticReviewError(
                "semantic review requires a validated development task"
            )
        task_sha = _sha256_bytes(task.canonical_json().encode("utf-8"))
        if (
            self.task_id != task.task_id
            or self.task_sha256 != task_sha
            or self.repository != task.repository
            or self.base_sha != task.base_sha
            or self.command_id not in task.allowed_command_ids
            or len(task.allowed_command_ids) != 1
            or task.required_tests != task.allowed_command_ids
            or self.command_id != task.allowed_command_ids[0]
            or self.acceptance_criteria != task.acceptance_criteria
        ):
            raise SemanticReviewError(
                "semantic review request is not bound to the task"
            )

    def verify_execution_authority(self, control_plane_root: Path) -> None:
        current = tier_a_toolhost_sha256(Path(control_plane_root))
        if current != self.execution_authority_sha256:
            raise SemanticReviewError(
                "semantic review execution authority no longer matches"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "developer_actor_id": self.developer_actor_id,
            "command_id": self.command_id,
            "execution_authority_sha256": self.execution_authority_sha256,
            "review_policy_sha256": self.review_policy_sha256,
            "staged_patch_base64": base64.b64encode(self.staged_patch).decode("ascii"),
            "staged_patch_sha256": self.staged_patch_sha256,
            "staged_patch_bytes": self.staged_patch_bytes,
            "acceptance_criteria": list(self.acceptance_criteria),
            "receipt": self.receipt.to_dict(),
            "receipt_sha256": self.receipt_sha256,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class CriterionAssessment:
    criterion_sha256: str
    outcome: CriterionOutcome
    rationale: str

    def __post_init__(self) -> None:
        _hex(
            self.criterion_sha256,
            name="criterion assessment hash",
            pattern=_HEX64,
        )
        if not isinstance(self.outcome, CriterionOutcome):
            raise SemanticReviewError("criterion assessment outcome is invalid")
        _clean_text(self.rationale, name="criterion rationale", maximum=4_096)

    @classmethod
    def from_mapping(cls, value: Any) -> "CriterionAssessment":
        data = _strict(
            value,
            name="criterion assessment",
            fields={"criterion_sha256", "outcome", "rationale"},
        )
        try:
            outcome = CriterionOutcome(data["outcome"])
        except (TypeError, ValueError) as exc:
            raise SemanticReviewError(
                "criterion assessment outcome is unsupported"
            ) from exc
        return cls(
            criterion_sha256=data["criterion_sha256"],
            outcome=outcome,
            rationale=data["rationale"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_sha256": self.criterion_sha256,
            "outcome": self.outcome.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class SemanticFinding:
    severity: FindingSeverity
    title: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.severity, FindingSeverity):
            raise SemanticReviewError("semantic finding severity is invalid")
        _clean_text(self.title, name="semantic finding title", maximum=256)
        _clean_text(self.detail, name="semantic finding detail", maximum=4_096)

    @classmethod
    def from_mapping(cls, value: Any) -> "SemanticFinding":
        data = _strict(
            value,
            name="semantic finding",
            fields={"severity", "title", "detail"},
        )
        try:
            severity = FindingSeverity(data["severity"])
        except (TypeError, ValueError) as exc:
            raise SemanticReviewError(
                "semantic finding severity is unsupported"
            ) from exc
        return cls(
            severity=severity,
            title=data["title"],
            detail=data["detail"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class SemanticReviewVerdict:
    review_request_sha256: str
    receipt_sha256: str
    staged_patch_sha256: str
    execution_authority_sha256: str
    review_policy_sha256: str
    developer_actor_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    independent: bool
    decision: SemanticReviewDecision
    criterion_assessments: tuple[CriterionAssessment, ...]
    findings: tuple[SemanticFinding, ...]
    schema: str = SEMANTIC_REVIEW_VERDICT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SEMANTIC_REVIEW_VERDICT_SCHEMA:
            raise SemanticReviewError("unsupported semantic review verdict schema")
        for name, value in (
            ("semantic review request hash", self.review_request_sha256),
            ("semantic review receipt hash", self.receipt_sha256),
            ("semantic review patch hash", self.staged_patch_sha256),
            ("semantic review authority hash", self.execution_authority_sha256),
            ("semantic review policy hash", self.review_policy_sha256),
        ):
            _hex(value, name=name, pattern=_HEX64)
        if (
            not isinstance(self.developer_actor_id, str)
            or _ACTOR_ID.fullmatch(self.developer_actor_id) is None
            or not isinstance(self.reviewer_actor_id, str)
            or _ACTOR_ID.fullmatch(self.reviewer_actor_id) is None
            or self.reviewer_actor_id == self.developer_actor_id
        ):
            raise SemanticReviewError(
                "semantic review actor separation is invalid"
            )
        if (
            not isinstance(self.reviewer_system_id, str)
            or _IDENTIFIER.fullmatch(self.reviewer_system_id) is None
        ):
            raise SemanticReviewError("semantic reviewer system id is invalid")
        if self.independent is not True:
            raise SemanticReviewError("semantic review verdict is not independent")
        if not isinstance(self.decision, SemanticReviewDecision):
            raise SemanticReviewError("semantic review decision is invalid")
        if (
            not isinstance(self.criterion_assessments, tuple)
            or not self.criterion_assessments
            or len(self.criterion_assessments) > _MAX_CRITERIA
            or any(
                not isinstance(item, CriterionAssessment)
                for item in self.criterion_assessments
            )
        ):
            raise SemanticReviewError(
                "semantic review criterion assessments are invalid"
            )
        assessment_ids = tuple(
            item.criterion_sha256 for item in self.criterion_assessments
        )
        if len(assessment_ids) != len(set(assessment_ids)):
            raise SemanticReviewError(
                "semantic review criterion assessments are duplicated"
            )
        if (
            not isinstance(self.findings, tuple)
            or len(self.findings) > _MAX_FINDINGS
            or any(not isinstance(item, SemanticFinding) for item in self.findings)
        ):
            raise SemanticReviewError("semantic review findings are invalid")
        finding_ids = tuple(
            (item.severity, item.title, item.detail) for item in self.findings
        )
        if len(finding_ids) != len(set(finding_ids)):
            raise SemanticReviewError("semantic review findings are duplicated")
        all_satisfied = all(
            item.outcome is CriterionOutcome.SATISFIED
            for item in self.criterion_assessments
        )
        if self.decision is SemanticReviewDecision.APPROVE:
            if not all_satisfied or self.findings:
                raise SemanticReviewError(
                    "semantic approval requires satisfied criteria and no findings"
                )
        elif not self.findings and all_satisfied:
            raise SemanticReviewError(
                "non-approval requires a finding or non-satisfied criterion"
            )
        if self.decision is SemanticReviewDecision.REJECT and not self.findings:
            raise SemanticReviewError(
                "semantic rejection requires at least one finding"
            )

    @classmethod
    def create(
        cls,
        *,
        request: SemanticReviewRequest,
        reviewer_actor_id: str,
        reviewer_system_id: str,
        decision: SemanticReviewDecision,
        criterion_assessments: Sequence[CriterionAssessment],
        findings: Sequence[SemanticFinding],
    ) -> "SemanticReviewVerdict":
        if not isinstance(request, SemanticReviewRequest):
            raise SemanticReviewError(
                "semantic verdict requires a canonical review request"
            )
        verdict = cls(
            review_request_sha256=request.sha256,
            receipt_sha256=request.receipt_sha256,
            staged_patch_sha256=request.staged_patch_sha256,
            execution_authority_sha256=request.execution_authority_sha256,
            review_policy_sha256=request.review_policy_sha256,
            developer_actor_id=request.developer_actor_id,
            reviewer_actor_id=reviewer_actor_id,
            reviewer_system_id=reviewer_system_id,
            independent=True,
            decision=decision,
            criterion_assessments=tuple(criterion_assessments),
            findings=tuple(findings),
        )
        verdict.verify_request(request)
        return verdict

    @classmethod
    def from_mapping(cls, value: Any) -> "SemanticReviewVerdict":
        fields = {
            "schema",
            "review_request_sha256",
            "receipt_sha256",
            "staged_patch_sha256",
            "execution_authority_sha256",
            "review_policy_sha256",
            "developer_actor_id",
            "reviewer_actor_id",
            "reviewer_system_id",
            "independent",
            "decision",
            "criterion_assessments",
            "findings",
        }
        data = _strict(
            value,
            name="semantic review verdict",
            fields=fields,
        )
        assessments = data["criterion_assessments"]
        findings = data["findings"]
        if not isinstance(assessments, list) or not isinstance(findings, list):
            raise SemanticReviewError(
                "semantic review verdict arrays are invalid"
            )
        try:
            decision = SemanticReviewDecision(data["decision"])
        except (TypeError, ValueError) as exc:
            raise SemanticReviewError(
                "semantic review decision is unsupported"
            ) from exc
        return cls(
            schema=data["schema"],
            review_request_sha256=data["review_request_sha256"],
            receipt_sha256=data["receipt_sha256"],
            staged_patch_sha256=data["staged_patch_sha256"],
            execution_authority_sha256=data["execution_authority_sha256"],
            review_policy_sha256=data["review_policy_sha256"],
            developer_actor_id=data["developer_actor_id"],
            reviewer_actor_id=data["reviewer_actor_id"],
            reviewer_system_id=data["reviewer_system_id"],
            independent=data["independent"],
            decision=decision,
            criterion_assessments=tuple(
                CriterionAssessment.from_mapping(item) for item in assessments
            ),
            findings=tuple(SemanticFinding.from_mapping(item) for item in findings),
        )

    def verify_request(self, request: SemanticReviewRequest) -> None:
        if not isinstance(request, SemanticReviewRequest):
            raise SemanticReviewError(
                "semantic verdict requires a canonical review request"
            )
        if (
            self.review_request_sha256 != request.sha256
            or self.receipt_sha256 != request.receipt_sha256
            or self.staged_patch_sha256 != request.staged_patch_sha256
            or self.execution_authority_sha256
            != request.execution_authority_sha256
            or self.review_policy_sha256 != request.review_policy_sha256
            or self.developer_actor_id != request.developer_actor_id
            or self.reviewer_actor_id == request.developer_actor_id
        ):
            raise SemanticReviewError(
                "semantic verdict is not bound to the exact review request"
            )
        expected = tuple(
            criterion_sha256(item) for item in request.acceptance_criteria
        )
        actual = tuple(
            item.criterion_sha256 for item in self.criterion_assessments
        )
        if actual != expected:
            raise SemanticReviewError(
                "semantic verdict does not assess every criterion in order"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "review_request_sha256": self.review_request_sha256,
            "receipt_sha256": self.receipt_sha256,
            "staged_patch_sha256": self.staged_patch_sha256,
            "execution_authority_sha256": self.execution_authority_sha256,
            "review_policy_sha256": self.review_policy_sha256,
            "developer_actor_id": self.developer_actor_id,
            "reviewer_actor_id": self.reviewer_actor_id,
            "reviewer_system_id": self.reviewer_system_id,
            "independent": self.independent,
            "decision": self.decision.value,
            "criterion_assessments": [
                item.to_dict() for item in self.criterion_assessments
            ],
            "findings": [item.to_dict() for item in self.findings],
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class SignedSemanticReviewVerdict:
    verdict: SemanticReviewVerdict
    key_id: str
    signature_algorithm: str
    signature_sha256: str
    schema: str = SIGNED_SEMANTIC_REVIEW_VERDICT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SIGNED_SEMANTIC_REVIEW_VERDICT_SCHEMA:
            raise SemanticReviewError(
                "unsupported signed semantic review verdict schema"
            )
        if not isinstance(self.verdict, SemanticReviewVerdict):
            raise SemanticReviewError("signed semantic review verdict is invalid")
        if not isinstance(self.key_id, str) or _IDENTIFIER.fullmatch(self.key_id) is None:
            raise SemanticReviewError("semantic review key id is invalid")
        if self.signature_algorithm != SEMANTIC_REVIEW_SIGNATURE_ALGORITHM:
            raise SemanticReviewError(
                "semantic review signature algorithm is unsupported"
            )
        _hex(
            self.signature_sha256,
            name="semantic review signature",
            pattern=_HEX64,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "SignedSemanticReviewVerdict":
        data = _strict(
            value,
            name="signed semantic review verdict",
            fields={
                "schema",
                "verdict",
                "key_id",
                "signature_algorithm",
                "signature_sha256",
            },
        )
        return cls(
            schema=data["schema"],
            verdict=SemanticReviewVerdict.from_mapping(data["verdict"]),
            key_id=data["key_id"],
            signature_algorithm=data["signature_algorithm"],
            signature_sha256=data["signature_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "verdict": self.verdict.to_dict(),
            "key_id": self.key_id,
            "signature_algorithm": self.signature_algorithm,
            "signature_sha256": self.signature_sha256,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


class HmacSemanticReviewVerdictSigner:
    """Sign a semantic verdict with reviewer-only key material."""

    def __init__(
        self,
        *,
        key_id: str,
        reviewer_actor_id: str,
        secret: bytes,
    ) -> None:
        if not isinstance(key_id, str) or _IDENTIFIER.fullmatch(key_id) is None:
            raise SemanticReviewError("semantic review signing key id is invalid")
        if (
            not isinstance(reviewer_actor_id, str)
            or _ACTOR_ID.fullmatch(reviewer_actor_id) is None
        ):
            raise SemanticReviewError("semantic reviewer actor id is invalid")
        if not isinstance(secret, bytes) or not 32 <= len(secret) <= 4096:
            raise SemanticReviewError(
                "semantic review signing secret must contain 32..4096 bytes"
            )
        self.key_id = key_id
        self.reviewer_actor_id = reviewer_actor_id
        self._secret = secret

    def sign(
        self,
        verdict: SemanticReviewVerdict,
    ) -> SignedSemanticReviewVerdict:
        if not isinstance(verdict, SemanticReviewVerdict):
            raise SemanticReviewError(
                "only a canonical semantic review verdict can be signed"
            )
        if verdict.reviewer_actor_id != self.reviewer_actor_id:
            raise SemanticReviewError(
                "semantic review signing key is bound to another actor"
            )
        signature = hmac.new(
            self._secret,
            _SEMANTIC_REVIEW_SIGNATURE_DOMAIN
            + verdict.canonical_json().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SignedSemanticReviewVerdict(
            verdict=verdict,
            key_id=self.key_id,
            signature_algorithm=SEMANTIC_REVIEW_SIGNATURE_ALGORITHM,
            signature_sha256=signature,
        )


@dataclass(frozen=True, slots=True)
class TrustedSemanticReviewerKey:
    reviewer_actor_id: str
    secret: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reviewer_actor_id, str)
            or _ACTOR_ID.fullmatch(self.reviewer_actor_id) is None
        ):
            raise SemanticReviewError("trusted semantic reviewer actor is invalid")
        if not isinstance(self.secret, bytes) or not 32 <= len(self.secret) <= 4096:
            raise SemanticReviewError("trusted semantic reviewer key is invalid")


class SemanticReviewVerifier:
    """Verify exact request binding and one reviewer-authenticated verdict."""

    def __init__(
        self,
        keyring: Mapping[str, TrustedSemanticReviewerKey],
    ) -> None:
        clean: dict[str, TrustedSemanticReviewerKey] = {}
        for key_id, binding in keyring.items():
            if not isinstance(key_id, str) or _IDENTIFIER.fullmatch(key_id) is None:
                raise SemanticReviewError(
                    "trusted semantic review key id is invalid"
                )
            if not isinstance(binding, TrustedSemanticReviewerKey):
                raise SemanticReviewError(
                    "trusted semantic reviewer binding is invalid"
                )
            clean[key_id] = binding
        if not clean:
            raise SemanticReviewError(
                "semantic review verifier keyring must not be empty"
            )
        self.keyring = MappingProxyType(clean)

    def verify(
        self,
        *,
        task: DevelopmentTask,
        request: SemanticReviewRequest,
        signed_verdict: SignedSemanticReviewVerdict,
        control_plane_root: Path,
    ) -> SemanticReviewVerdict:
        if not isinstance(request, SemanticReviewRequest):
            raise SemanticReviewError(
                "semantic review verifier requires a canonical request"
            )
        if not isinstance(signed_verdict, SignedSemanticReviewVerdict):
            raise SemanticReviewError(
                "semantic review verifier requires a signed verdict"
            )
        request.verify_task(task)
        request.verify_execution_authority(control_plane_root)
        verdict = signed_verdict.verdict
        verdict.verify_request(request)
        try:
            binding = self.keyring[signed_verdict.key_id]
        except KeyError as exc:
            raise SemanticReviewError(
                "semantic review signing key is not trusted"
            ) from exc
        if (
            binding.reviewer_actor_id != verdict.reviewer_actor_id
            or verdict.reviewer_actor_id == request.developer_actor_id
        ):
            raise SemanticReviewError(
                "semantic review signing key actor does not match the verdict"
            )
        expected = hmac.new(
            binding.secret,
            _SEMANTIC_REVIEW_SIGNATURE_DOMAIN
            + verdict.canonical_json().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signed_verdict.signature_sha256):
            raise SemanticReviewError(
                "semantic review verdict signature is invalid"
            )
        return verdict


class SemanticReviewApprovalGate:
    """Return approval only for one fully verified semantic verdict."""

    @staticmethod
    def ready(
        *,
        task: DevelopmentTask,
        request: SemanticReviewRequest,
        signed_verdict: SignedSemanticReviewVerdict,
        verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> bool:
        try:
            verdict = verifier.verify(
                task=task,
                request=request,
                signed_verdict=signed_verdict,
                control_plane_root=control_plane_root,
            )
        except SemanticReviewError:
            return False
        return verdict.decision is SemanticReviewDecision.APPROVE


def _load_canonical_file(
    path: Path,
    *,
    maximum: int,
    parser: Any,
    name: str,
) -> Any:
    raw_path = Path(path)
    if (
        not raw_path.is_absolute()
        or _has_linkish_component(raw_path)
        or not raw_path.is_file()
    ):
        raise SemanticReviewError(f"{name} must be an absolute regular file")
    raw = raw_path.read_bytes()
    if not 2 <= len(raw) <= maximum:
        raise SemanticReviewError(f"{name} size is invalid")
    try:
        value = parser(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticReviewError(f"{name} JSON is invalid") from exc
    if raw != value.canonical_json().encode("utf-8"):
        raise SemanticReviewError(f"{name} is not canonical JSON")
    return value


def _write_canonical_file(path: Path, value: Any, *, prefix: str) -> str:
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or _has_linkish_component(output.parent)
        or not output.parent.is_dir()
    ):
        raise SemanticReviewError(
            "semantic review output path is unsafe or already exists"
        )
    payload = value.canonical_json().encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=prefix,
        suffix=".tmp",
        dir=output.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return _sha256_bytes(payload)


def load_semantic_review_request(path: Path) -> SemanticReviewRequest:
    return _load_canonical_file(
        path,
        maximum=48 * 1024 * 1024,
        parser=SemanticReviewRequest.from_mapping,
        name="semantic review request",
    )


def write_semantic_review_request(
    path: Path,
    request: SemanticReviewRequest,
) -> str:
    if not isinstance(request, SemanticReviewRequest):
        raise SemanticReviewError(
            "semantic review request output is invalid"
        )
    return _write_canonical_file(path, request, prefix=".semantic-request-")


def load_signed_semantic_review_verdict(
    path: Path,
) -> SignedSemanticReviewVerdict:
    return _load_canonical_file(
        path,
        maximum=4 * 1024 * 1024,
        parser=SignedSemanticReviewVerdict.from_mapping,
        name="signed semantic review verdict",
    )


def write_signed_semantic_review_verdict(
    path: Path,
    signed_verdict: SignedSemanticReviewVerdict,
) -> str:
    if not isinstance(signed_verdict, SignedSemanticReviewVerdict):
        raise SemanticReviewError(
            "signed semantic review verdict output is invalid"
        )
    return _write_canonical_file(
        path,
        signed_verdict,
        prefix=".semantic-verdict-",
    )
