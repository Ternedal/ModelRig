"""Deterministic evidence receipts for scope decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .contract import DevelopmentTask
from .policy import ScopeDecision

RECEIPT_SCHEMA = "kaliv-development-scope-receipt/v1"


@dataclass(frozen=True, slots=True)
class ScopeReceipt:
    task_id: str
    task_sha256: str
    base_sha: str
    passed: bool
    changed_paths: tuple[str, ...]
    violations: tuple[str, ...]
    details: tuple[str, ...]
    added_lines: int
    deleted_lines: int
    schema: str = RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "passed": self.passed,
            "changed_paths": list(self.changed_paths),
            "violations": list(self.violations),
            "details": list(self.details),
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


def build_scope_receipt(
    task: DevelopmentTask,
    decision: ScopeDecision,
    *,
    added_lines: int,
    deleted_lines: int,
) -> ScopeReceipt:
    task_hash = hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()
    return ScopeReceipt(
        task_id=task.task_id,
        task_sha256=task_hash,
        base_sha=task.base_sha,
        passed=decision.passed,
        changed_paths=decision.normalized_paths,
        violations=tuple(item.value for item in decision.violations),
        details=decision.details,
        added_lines=added_lines,
        deleted_lines=deleted_lines,
    )
