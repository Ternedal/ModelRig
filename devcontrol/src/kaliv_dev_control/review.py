"""Independent structural review contracts and a draft-PR readiness gate."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Sequence

from .commands import CommandReceipt
from .contract import DevelopmentTask, MergeAuthority
from .patch import PatchReceipt

REQUEST_SCHEMA = "kaliv-development-review-request/v1"
VERDICT_SCHEMA = "kaliv-development-review-verdict/v1"
_ACTOR_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{1,127}$")


class ReviewError(ValueError):
    """Review evidence is incomplete, inconsistent, or not independent."""


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class CommandEvidence:
    command_id: str
    receipt_sha256: str
    passed: bool

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

        return cls(
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
        if verdict.review_request_sha256 != _sha256(request.canonical_json()):
            return False
        if verdict.developer_actor_id != request.developer_actor_id:
            return False
        if not verdict.independent or verdict.decision is not ReviewDecision.APPROVE:
            return False
        evidence = {item.command_id: item for item in request.command_evidence}
        return all(
            command_id in evidence and evidence[command_id].passed
            for command_id in task.allowed_command_ids
        )
