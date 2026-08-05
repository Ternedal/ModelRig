"""Immutable development task contract.

The task contract is the authority boundary for a development campaign. It is
strict by design: unknown fields and ambiguous path or command declarations are
rejected instead of silently ignored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Mapping

SCHEMA = "kaliv-development-task/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_ALLOWED_FIELDS = {
    "schema",
    "task_id",
    "repository",
    "base_sha",
    "goal",
    "acceptance_criteria",
    "risk",
    "allowed_paths",
    "protected_paths",
    "allowed_command_ids",
    "required_tests",
    "budget",
    "merge_authority",
}


class ContractError(ValueError):
    """The task contract is malformed or grants ambiguous authority."""


class Risk(StrEnum):
    TRIVIAL = "trivial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MergeAuthority(StrEnum):
    HUMAN = "human"


def _strict_mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be an object")
    return value


def _clean_string(value: Any, *, name: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a string")
    if not value or value.strip() != value or "\x00" in value:
        raise ContractError(f"{name} is empty or not canonical")
    if len(value.encode("utf-8")) > maximum:
        raise ContractError(f"{name} exceeds {maximum} UTF-8 bytes")
    return value


def _string_list(
    value: Any,
    *,
    name: str,
    minimum: int = 1,
    maximum_items: int = 128,
    maximum_bytes: int = 1024,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractError(f"{name} must be an array")
    if not minimum <= len(value) <= maximum_items:
        raise ContractError(f"{name} must contain {minimum}..{maximum_items} items")
    result = tuple(
        _clean_string(item, name=f"{name}[{index}]", maximum=maximum_bytes)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise ContractError(f"{name} must not contain duplicates")
    return result


def normalize_repo_path(value: str, *, name: str) -> str:
    """Return a canonical repository-relative POSIX path or glob."""

    raw = _clean_string(value, name=name, maximum=512)
    if "\\" in raw:
        raise ContractError(f"{name} must use POSIX separators")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ContractError(f"{name} must be repository-relative")
    raw_parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ContractError(f"{name} contains a non-canonical path segment")
    path = PurePosixPath(raw)
    canonical = path.as_posix()
    if canonical != raw:
        raise ContractError(f"{name} is not canonical")
    return canonical


@dataclass(frozen=True, slots=True)
class TaskBudget:
    max_changed_files: int
    max_added_lines: int
    max_deleted_lines: int
    max_attempts: int
    max_runtime_seconds: int
    max_output_bytes: int

    @classmethod
    def from_mapping(cls, value: Any) -> "TaskBudget":
        data = _strict_mapping(value, name="budget")
        allowed = {
            "max_changed_files",
            "max_added_lines",
            "max_deleted_lines",
            "max_attempts",
            "max_runtime_seconds",
            "max_output_bytes",
        }
        unknown = sorted(set(data) - allowed)
        missing = sorted(allowed - set(data))
        if unknown or missing:
            raise ContractError(
                "budget fields mismatch"
                + (f"; unknown={unknown}" if unknown else "")
                + (f"; missing={missing}" if missing else "")
            )

        def integer(name: str, low: int, high: int) -> int:
            item = data[name]
            if isinstance(item, bool) or not isinstance(item, int):
                raise ContractError(f"budget.{name} must be an integer")
            if not low <= item <= high:
                raise ContractError(f"budget.{name} must be in {low}..{high}")
            return item

        return cls(
            max_changed_files=integer("max_changed_files", 1, 200),
            max_added_lines=integer("max_added_lines", 1, 50_000),
            max_deleted_lines=integer("max_deleted_lines", 0, 50_000),
            max_attempts=integer("max_attempts", 1, 10),
            max_runtime_seconds=integer("max_runtime_seconds", 10, 86_400),
            max_output_bytes=integer("max_output_bytes", 1_024, 100_000_000),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_changed_files": self.max_changed_files,
            "max_added_lines": self.max_added_lines,
            "max_deleted_lines": self.max_deleted_lines,
            "max_attempts": self.max_attempts,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_output_bytes": self.max_output_bytes,
        }


@dataclass(frozen=True, slots=True)
class DevelopmentTask:
    task_id: str
    repository: str
    base_sha: str
    goal: str
    acceptance_criteria: tuple[str, ...]
    risk: Risk
    allowed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    allowed_command_ids: tuple[str, ...]
    required_tests: tuple[str, ...]
    budget: TaskBudget
    merge_authority: MergeAuthority = MergeAuthority.HUMAN
    schema: str = SCHEMA

    @classmethod
    def from_mapping(cls, value: Any) -> "DevelopmentTask":
        data = _strict_mapping(value, name="task")
        unknown = sorted(set(data) - _ALLOWED_FIELDS)
        missing = sorted(_ALLOWED_FIELDS - set(data))
        if unknown or missing:
            raise ContractError(
                "task fields mismatch"
                + (f"; unknown={unknown}" if unknown else "")
                + (f"; missing={missing}" if missing else "")
            )
        if data["schema"] != SCHEMA:
            raise ContractError(f"schema must be {SCHEMA}")

        task_id = _clean_string(data["task_id"], name="task_id", maximum=64)
        if _TASK_ID.fullmatch(task_id) is None:
            raise ContractError("task_id has invalid syntax")
        repository = _clean_string(data["repository"], name="repository", maximum=200)
        parts = repository.split("/")
        if len(parts) != 2 or not all(part and part.strip() == part for part in parts):
            raise ContractError("repository must be owner/name")
        base_sha = _clean_string(data["base_sha"], name="base_sha", maximum=40)
        if _SHA40.fullmatch(base_sha) is None:
            raise ContractError("base_sha must be a lowercase 40-hex SHA")

        allowed_paths = tuple(
            normalize_repo_path(path, name=f"allowed_paths[{index}]")
            for index, path in enumerate(
                _string_list(data["allowed_paths"], name="allowed_paths")
            )
        )
        protected_paths = tuple(
            normalize_repo_path(path, name=f"protected_paths[{index}]")
            for index, path in enumerate(
                _string_list(data["protected_paths"], name="protected_paths")
            )
        )
        commands = _string_list(
            data["allowed_command_ids"], name="allowed_command_ids", maximum_bytes=64
        )
        for command in commands:
            if _COMMAND_ID.fullmatch(command) is None:
                raise ContractError(f"invalid allowed command id: {command}")

        try:
            risk = Risk(data["risk"])
        except (ValueError, TypeError) as exc:
            raise ContractError("risk is unsupported") from exc
        try:
            merge_authority = MergeAuthority(data["merge_authority"])
        except (ValueError, TypeError) as exc:
            raise ContractError("merge_authority must remain human") from exc

        return cls(
            task_id=task_id,
            repository=repository,
            base_sha=base_sha,
            goal=_clean_string(data["goal"], name="goal"),
            acceptance_criteria=_string_list(
                data["acceptance_criteria"], name="acceptance_criteria", maximum_items=64
            ),
            risk=risk,
            allowed_paths=allowed_paths,
            protected_paths=protected_paths,
            allowed_command_ids=commands,
            required_tests=_string_list(
                data["required_tests"], name="required_tests", maximum_items=128
            ),
            budget=TaskBudget.from_mapping(data["budget"]),
            merge_authority=merge_authority,
        )

    @classmethod
    def from_json(cls, text: str) -> "DevelopmentTask":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ContractError("task JSON is invalid") from exc
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "goal": self.goal,
            "acceptance_criteria": list(self.acceptance_criteria),
            "risk": self.risk.value,
            "allowed_paths": list(self.allowed_paths),
            "protected_paths": list(self.protected_paths),
            "allowed_command_ids": list(self.allowed_command_ids),
            "required_tests": list(self.required_tests),
            "budget": self.budget.to_dict(),
            "merge_authority": self.merge_authority.value,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
