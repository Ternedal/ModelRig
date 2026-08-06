"""Independent structural review contracts and a draft-PR readiness gate."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from .commands import CommandReceipt
from .contract import DevelopmentTask, MergeAuthority
from .patch import PatchReceipt

REQUEST_SCHEMA = "kaliv-development-review-request/v1"
VERDICT_SCHEMA = "kaliv-development-review-verdict/v1"
_ACTOR_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{1,127}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class ReviewError(ValueError):
    """Review evidence is incomplete, inconsistent, or not independent."""


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_string(value: Any, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise ReviewError(f"{name} is invalid")
    return value


def _strict_fields(value: Any, *, name: str, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != allowed:
        raise ReviewError(f"{name} fields mismatch")
    return value


@dataclass(frozen=True, slots=True)
class CommandEvidence:
    command_id: str
    receipt_sha256: str
    passed: bool

    @classmethod
    def from_mapping(cls, value: Any) -> "CommandEvidence":
        data = _strict_fields(
            value,
            name="command evidence",
            allowed={"command_id", "receipt_sha256", "passed"},
        )
        command_id = _canonical_string(
            data["command_id"], name="command id", maximum=64
        )
        if _COMMAND_ID.fullmatch(command_id) is None:
            raise ReviewError("command id is invalid")
        if not isinstance(data["passed"], bool):
            raise ReviewError("command evidence passed must be boolean")
        if not isinstance(data["receipt_sha256"], str) or _SHA64.fullmatch(
            data["receipt_sha256"]
        ) is None:
            raise ReviewError("command receipt hash is invalid")
        return cls(
            command_id=command_id,
            receipt_sha256=data["receipt_sha256"],
            passed=data["passed"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "receipt_sha256": self.receipt_sha256,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    task_id: str
    task_sha256: str
    base_sha: str
    developer_actor_id: str
    patch_receipt_sha256: str
    index_diff_sha256: str
    required_command_ids: tuple[str, ...]
    command_evidence: tuple[CommandEvidence, ...]
    acceptance_criteria: tuple[str, ...]
    schema: str = REQUEST_SCHEMA

    @classmethod
    def from_evidence(
        cls,
        *,
        task: DevelopmentTask,
        developer_actor_id: str,
        patch: PatchReceipt,
        commands: Sequence[CommandReceipt],
    ) -> "ReviewRequest":
        if _ACTOR_ID.fullmatch(developer_actor_id) is None:
            raise ReviewError("developer actor id is invalid")
        task_hash = _sha256(task.canonical_json())
        if (
            patch.task_id != task.task_id
            or patch.task_sha256 != task_hash
            or patch.base_sha != task.base_sha
            or not patch.applied
            or not patch.scope.passed
        ):
            raise ReviewError("patch receipt is not bound to the task")

        evidence: list[CommandEvidence] = []
        seen: set[str] = set()
        for receipt in commands:
            if receipt.command_id in seen:
                raise ReviewError("command receipt is duplicated")
            seen.add(receipt.command_id)
            if receipt.command_id not in task.allowed_command_ids:
                raise ReviewError("command receipt is outside task authority")
            if (
                receipt.task_id != task.task_id
                or receipt.task_sha256 != task_hash
                or receipt.base_sha != task.base_sha
            ):
                raise ReviewError("command receipt is not bound to the task")
            evidence.append(
                CommandEvidence(
                    command_id=receipt.command_id,
                    receipt_sha256=_sha256(receipt.canonical_json()),
                    passed=receipt.passed,
                )
            )

        missing = sorted(set(task.allowed_command_ids) - seen)
        if missing:
            raise ReviewError(f"required command receipts are missing: {missing}")

        request = cls(
            task_id=task.task_id,
            task_sha256=task_hash,
            base_sha=task.base_sha,
            developer_actor_id=developer_actor_id,
            patch_receipt_sha256=_sha256(patch.canonical_json()),
            index_diff_sha256=patch.index_diff_sha256,
            required_command_ids=task.allowed_command_ids,
            command_evidence=tuple(sorted(evidence, key=lambda item: item.command_id)),
            acceptance_criteria=task.acceptance_criteria,
        )
        request.verify_task(task)
        return request

    @classmethod
    def from_mapping(cls, value: Any) -> "ReviewRequest":
        data = _strict_fields(
            value,
            name="review request",
            allowed={
                "schema",
                "task_id",
                "task_sha256",
                "base_sha",
                "developer_actor_id",
                "patch_receipt_sha256",
                "index_diff_sha256",
                "required_command_ids",
                "command_evidence",
                "acceptance_criteria",
            },
        )
        if data["schema"] != REQUEST_SCHEMA:
            raise ReviewError("review request schema is unsupported")
        task_id = _canonical_string(data["task_id"], name="task id", maximum=64)
        actor = _canonical_string(
            data["developer_actor_id"], name="developer actor id", maximum=128
        )
        if _ACTOR_ID.fullmatch(actor) is None:
            raise ReviewError("developer actor id is invalid")
        for name, pattern in (
            ("task_sha256", _SHA64),
            ("base_sha", _SHA40),
            ("patch_receipt_sha256", _SHA64),
            ("index_diff_sha256", _SHA64),
        ):
            if not isinstance(data[name], str) or pattern.fullmatch(data[name]) is None:
                raise ReviewError(f"{name} is invalid")

        raw_required = data["required_command_ids"]
        raw_evidence = data["command_evidence"]
        raw_criteria = data["acceptance_criteria"]
        if not isinstance(raw_required, list) or not raw_required:
            raise ReviewError("required command ids must be a non-empty array")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ReviewError("command evidence must be a non-empty array")
        if not isinstance(raw_criteria, list) or not raw_criteria:
            raise ReviewError("acceptance criteria must be a non-empty array")

        required = tuple(
            _canonical_string(item, name="required command id", maximum=64)
            for item in raw_required
        )
        if len(required) != len(set(required)) or any(
            _COMMAND_ID.fullmatch(item) is None for item in required
        ):
            raise ReviewError("required command ids are invalid or duplicated")
        evidence = tuple(CommandEvidence.from_mapping(item) for item in raw_evidence)
        evidence_ids = tuple(item.command_id for item in evidence)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ReviewError("command evidence is duplicated")
        if tuple(sorted(evidence_ids)) != tuple(sorted(required)):
            raise ReviewError("command evidence does not match required commands")
        criteria = tuple(
            _canonical_string(item, name="acceptance criterion", maximum=1_024)
            for item in raw_criteria
        )
        if len(criteria) != len(set(criteria)):
            raise ReviewError("acceptance criteria must not contain duplicates")

        return cls(
            task_id=task_id,
            task_sha256=data["task_sha256"],
            base_sha=data["base_sha"],
            developer_actor_id=actor,
            patch_receipt_sha256=data["patch_receipt_sha256"],
            index_diff_sha256=data["index_diff_sha256"],
            required_command_ids=required,
            command_evidence=tuple(sorted(evidence, key=lambda item: item.command_id)),
            acceptance_criteria=criteria,
        )

    def verify_task(self, task: DevelopmentTask) -> None:
        task_hash = _sha256(task.canonical_json())
        if (
            self.task_id != task.task_id
            or self.task_sha256 != task_hash
            or self.base_sha != task.base_sha
            or self.required_command_ids != task.allowed_command_ids
            or self.acceptance_criteria != task.acceptance_criteria
        ):
            raise ReviewError("review request is not bound to the task contract")
        evidence_ids = tuple(item.command_id for item in self.command_evidence)
        if tuple(sorted(evidence_ids)) != tuple(sorted(self.required_command_ids)):
            raise ReviewError("review request command evidence is incomplete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "developer_actor_id": self.developer_actor_id,
            "patch_receipt_sha256": self.patch_receipt_sha256,
            "index_diff_sha256": self.index_diff_sha256,
            "required_command_ids": list(self.required_command_ids),
            "command_evidence": [item.to_dict() for item in self.command_evidence],
            "acceptance_criteria": list(self.acceptance_criteria),
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReviewVerdict:
    review_request_sha256: str
    developer_actor_id: str
    reviewer_actor_id: str
    independent: bool
    decision: ReviewDecision
    findings: tuple[str, ...]
    schema: str = VERDICT_SCHEMA

    @classmethod
    def from_mapping(cls, value: Any) -> "ReviewVerdict":
        data = _strict_fields(
            value,
            name="review verdict",
            allowed={
                "schema",
                "review_request_sha256",
                "developer_actor_id",
                "reviewer_actor_id",
                "independent",
                "decision",
                "findings",
            },
        )
        if data["schema"] != VERDICT_SCHEMA:
            raise ReviewError("review verdict schema is unsupported")
        if not isinstance(data["review_request_sha256"], str) or _SHA64.fullmatch(
            data["review_request_sha256"]
        ) is None:
            raise ReviewError("review request hash is invalid")
        developer = _canonical_string(
            data["developer_actor_id"], name="developer actor id", maximum=128
        )
        reviewer = _canonical_string(
            data["reviewer_actor_id"], name="reviewer actor id", maximum=128
        )
        if (
            _ACTOR_ID.fullmatch(developer) is None
            or _ACTOR_ID.fullmatch(reviewer) is None
            or developer == reviewer
        ):
            raise ReviewError("review actor separation is invalid")
        if data["independent"] is not True:
            raise ReviewError("review verdict is not independent")
        try:
            decision = ReviewDecision(data["decision"])
        except (TypeError, ValueError) as exc:
            raise ReviewError("review decision is unsupported") from exc
        if not isinstance(data["findings"], list):
            raise ReviewError("review findings must be an array")
        findings = tuple(
            _canonical_string(item, name="review finding", maximum=2_048)
            for item in data["findings"]
        )
        if len(findings) != len(set(findings)):
            raise ReviewError("review findings must not contain duplicates")
        return cls(
            review_request_sha256=data["review_request_sha256"],
            developer_actor_id=developer,
            reviewer_actor_id=reviewer,
            independent=True,
            decision=decision,
            findings=findings,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "review_request_sha256": self.review_request_sha256,
            "developer_actor_id": self.developer_actor_id,
            "reviewer_actor_id": self.reviewer_actor_id,
            "independent": self.independent,
            "decision": self.decision.value,
            "findings": list(self.findings),
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class IndependentPolicyReviewer:
    """Perform structural review without pretending to review code semantics."""

    def review(
        self,
        request: ReviewRequest,
        *,
        reviewer_actor_id: str,
    ) -> ReviewVerdict:
        if _ACTOR_ID.fullmatch(reviewer_actor_id) is None:
            raise ReviewError("reviewer actor id is invalid")
        if reviewer_actor_id == request.developer_actor_id:
            raise ReviewError("developer and reviewer must be independent")

        by_id = {item.command_id: item for item in request.command_evidence}
        if set(by_id) != set(request.required_command_ids):
            raise ReviewError("review request command evidence is incomplete")
        findings = tuple(
            f"required command failed: {command_id}"
            for command_id in request.required_command_ids
            if not by_id[command_id].passed
        )
        decision = (
            ReviewDecision.APPROVE
            if not findings
            else ReviewDecision.REQUEST_CHANGES
        )
        return ReviewVerdict(
            review_request_sha256=_sha256(request.canonical_json()),
            developer_actor_id=request.developer_actor_id,
            reviewer_actor_id=reviewer_actor_id,
            independent=True,
            decision=decision,
            findings=findings,
        )


class DraftPrGate:
    """Check structural readiness; human merge authority remains unchanged."""

    @staticmethod
    def ready(
        task: DevelopmentTask,
        request: ReviewRequest,
        verdict: ReviewVerdict,
    ) -> bool:
        if task.merge_authority is not MergeAuthority.HUMAN:
            return False
        try:
            request.verify_task(task)
        except ReviewError:
            return False
        if verdict.review_request_sha256 != _sha256(request.canonical_json()):
            return False
        if verdict.developer_actor_id != request.developer_actor_id:
            return False
        if verdict.reviewer_actor_id == request.developer_actor_id:
            return False
        if not verdict.independent or verdict.decision is not ReviewDecision.APPROVE:
            return False
        evidence = {item.command_id: item for item in request.command_evidence}
        return all(
            command_id in evidence and evidence[command_id].passed
            for command_id in task.allowed_command_ids
        )
