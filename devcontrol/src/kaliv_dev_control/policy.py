"""Fail-closed path and diff-budget policy."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .contract import ContractError, DevelopmentTask, normalize_repo_path


class ScopeViolation(StrEnum):
    OUTSIDE_ALLOWED_PATHS = "outside_allowed_paths"
    PROTECTED_PATH = "protected_path"
    CHANGED_FILE_BUDGET = "changed_file_budget"
    ADDED_LINE_BUDGET = "added_line_budget"
    DELETED_LINE_BUDGET = "deleted_line_budget"


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    passed: bool
    normalized_paths: tuple[str, ...]
    violations: tuple[ScopeViolation, ...]
    details: tuple[str, ...]


class PathPolicy:
    """Evaluate candidate changes against one immutable task contract."""

    def __init__(self, task: DevelopmentTask) -> None:
        self.task = task

    @staticmethod
    def _matches(path: str, pattern: str) -> bool:
        return fnmatch.fnmatchcase(path, pattern) or path == pattern or path.startswith(
            pattern.rstrip("/") + "/"
        )

    def evaluate(
        self,
        changed_paths: Iterable[str],
        *,
        added_lines: int,
        deleted_lines: int,
    ) -> ScopeDecision:
        if isinstance(added_lines, bool) or not isinstance(added_lines, int) or added_lines < 0:
            raise ContractError("added_lines must be a non-negative integer")
        if (
            isinstance(deleted_lines, bool)
            or not isinstance(deleted_lines, int)
            or deleted_lines < 0
        ):
            raise ContractError("deleted_lines must be a non-negative integer")

        normalized: list[str] = []
        for index, raw in enumerate(changed_paths):
            normalized.append(normalize_repo_path(raw, name=f"changed_paths[{index}]"))
        if len(normalized) != len(set(normalized)):
            raise ContractError("changed_paths must not contain duplicates")

        violations: list[ScopeViolation] = []
        details: list[str] = []
        for path in normalized:
            if any(self._matches(path, item) for item in self.task.protected_paths):
                violations.append(ScopeViolation.PROTECTED_PATH)
                details.append(f"protected path changed: {path}")
                continue
            if not any(self._matches(path, item) for item in self.task.allowed_paths):
                violations.append(ScopeViolation.OUTSIDE_ALLOWED_PATHS)
                details.append(f"path outside task allowlist: {path}")

        if len(normalized) > self.task.budget.max_changed_files:
            violations.append(ScopeViolation.CHANGED_FILE_BUDGET)
            details.append(
                f"changed files {len(normalized)} exceed {self.task.budget.max_changed_files}"
            )
        if added_lines > self.task.budget.max_added_lines:
            violations.append(ScopeViolation.ADDED_LINE_BUDGET)
            details.append(
                f"added lines {added_lines} exceed {self.task.budget.max_added_lines}"
            )
        if deleted_lines > self.task.budget.max_deleted_lines:
            violations.append(ScopeViolation.DELETED_LINE_BUDGET)
            details.append(
                f"deleted lines {deleted_lines} exceed {self.task.budget.max_deleted_lines}"
            )

        unique_violations = tuple(dict.fromkeys(violations))
        return ScopeDecision(
            passed=not unique_violations,
            normalized_paths=tuple(normalized),
            violations=unique_violations,
            details=tuple(details),
        )
