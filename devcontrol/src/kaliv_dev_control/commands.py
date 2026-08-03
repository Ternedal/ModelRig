"""Allowlisted development commands and deterministic execution receipts.

Command arguments come from the registry, never from a model or task payload.
The executor snapshots the staged patch before and after the command. Any
repository mutation resets the ephemeral workspace to the task's exact base SHA.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contract import DevelopmentTask
from .workspace import Runner, SubprocessRunner, WorkspaceError

_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
RECEIPT_SCHEMA = "kaliv-development-command-receipt/v1"


class CommandPolicyError(ValueError):
    """A command template or requested command grants ambiguous authority."""


class CommandExecutionError(RuntimeError):
    """A command could not complete while preserving workspace integrity."""


@dataclass(frozen=True, slots=True)
class CommandTemplate:
    command_id: str
    argv: tuple[str, ...]
    cwd: str = "."
    max_timeout_seconds: int = 900
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _COMMAND_ID.fullmatch(self.command_id) is None:
            raise CommandPolicyError("invalid command id")
        if not self.argv or any(
            not isinstance(item, str) or not item or "\x00" in item
            for item in self.argv
        ):
            raise CommandPolicyError(
                "argv must contain canonical non-empty strings"
            )
        if self.cwd != ".":
            path = PurePosixPath(self.cwd)
            if (
                self.cwd.startswith("/")
                or "\\" in self.cwd
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise CommandPolicyError(
                    "command cwd must be repository-relative"
                )
        if not 1 <= self.max_timeout_seconds <= 86_400:
            raise CommandPolicyError("command timeout is outside bounds")

        immutable_env: dict[str, str] = {}
        for key, value in self.env.items():
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or "\x00" in key + value
            ):
                raise CommandPolicyError("command environment is invalid")
            immutable_env[key] = value
        object.__setattr__(self, "env", MappingProxyType(immutable_env))


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    task_id: str
    task_sha256: str
    base_sha: str
    command_id: str
    argv_sha256: str
    cwd: str
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    output_bytes: int
    duration_ms: int
    workspace_before_sha256: str
    workspace_after_sha256: str
    workspace_unchanged: bool
    workspace_reset: bool
    passed: bool
    schema: str = RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "command_id": self.command_id,
            "argv_sha256": self.argv_sha256,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "output_bytes": self.output_bytes,
            "duration_ms": self.duration_ms,
            "workspace_before_sha256": self.workspace_before_sha256,
            "workspace_after_sha256": self.workspace_after_sha256,
            "workspace_unchanged": self.workspace_unchanged,
            "workspace_reset": self.workspace_reset,
            "passed": self.passed,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class CommandRegistry:
    """Resolve fixed command templates by immutable command id."""

    def __init__(self, templates: Sequence[CommandTemplate]) -> None:
        values: dict[str, CommandTemplate] = {}
        for template in templates:
            if template.command_id in values:
                raise CommandPolicyError(
                    f"duplicate command id: {template.command_id}"
                )
            values[template.command_id] = template
        self._templates = MappingProxyType(values)

    def resolve(
        self,
        task: DevelopmentTask,
        command_id: str,
    ) -> CommandTemplate:
        if command_id not in task.allowed_command_ids:
            raise CommandPolicyError(
                "command is not allowed by the task contract"
            )
        try:
            return self._templates[command_id]
        except KeyError as exc:
            raise CommandPolicyError("command id is not registered") from exc


def default_registry() -> CommandRegistry:
    """Return the deliberately small read-only command registry."""

    return CommandRegistry(
        (
            CommandTemplate(
                command_id="python.unittest",
                argv=(
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "devcontrol/tests",
                    "-v",
                ),
                max_timeout_seconds=1_800,
                env={"PYTHONHASHSEED": "0", "NO_COLOR": "1"},
            ),
        )
    )


class CommandExecutor:
    """Execute a fixed command and prove it did not alter the workspace."""

    def __init__(
        self,
        registry: CommandRegistry | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.runner = runner or SubprocessRunner()

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _run_git(
        self,
        workspace: Path,
        *args: str,
        max_output_bytes: int = 4_000_000,
    ) -> str:
        result = self.runner.run(
            ["git", *args],
            cwd=workspace,
            timeout_seconds=60,
            max_output_bytes=max_output_bytes,
        )
        if result.returncode != 0:
            raise CommandExecutionError(f"git snapshot failed: {args[0]}")
        return result.stdout

    def _snapshot(self, workspace: Path) -> tuple[str, bool]:
        cached = self._run_git(
            workspace,
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--",
        )
        unstaged = self._run_git(
            workspace,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--",
        )
        untracked = self._run_git(
            workspace,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        )
        fingerprint = self._sha256(cached.encode("utf-8", errors="replace"))
        return fingerprint, not bool(unstaged or untracked)

    def _reset(self, task: DevelopmentTask, workspace: Path) -> None:
        for args in (
            ("reset", "--hard", task.base_sha),
            ("clean", "-fd"),
        ):
            result = self.runner.run(
                ["git", *args],
                cwd=workspace,
                timeout_seconds=120,
                max_output_bytes=2_000_000,
            )
            if result.returncode != 0:
                raise CommandExecutionError(
                    "workspace mutation could not be reset"
                )

    @staticmethod
    def _cwd(workspace: Path, relative: str) -> Path:
        root = workspace.resolve()
        target = root if relative == "." else (root / PurePosixPath(relative)).resolve()
        if not target.is_relative_to(root) or not target.is_dir():
            raise CommandExecutionError(
                "command cwd escaped or does not exist"
            )
        cursor = target
        while cursor != root:
            if cursor.is_symlink():
                raise CommandExecutionError("command cwd contains a symlink")
            cursor = cursor.parent
        return target

    def execute(
        self,
        task: DevelopmentTask,
        workspace: Path,
        command_id: str,
    ) -> CommandReceipt:
        template = self.registry.resolve(task, command_id)
        root = workspace.resolve()
        cwd = self._cwd(root, template.cwd)

        before_sha, before_clean = self._snapshot(root)
        if not before_clean:
            raise CommandExecutionError(
                "workspace has unstaged or untracked changes before command"
            )

        started = time.monotonic()
        try:
            result = self.runner.run(
                template.argv,
                cwd=cwd,
                timeout_seconds=min(
                    task.budget.max_runtime_seconds,
                    template.max_timeout_seconds,
                ),
                max_output_bytes=task.budget.max_output_bytes,
                env=template.env,
            )
        except WorkspaceError as exc:
            self._reset(task, root)
            raise CommandExecutionError(
                "command execution did not complete safely"
            ) from exc
        duration_ms = max(0, int((time.monotonic() - started) * 1_000))

        after_sha, after_clean = self._snapshot(root)
        unchanged = before_sha == after_sha and after_clean
        reset = False
        if not unchanged:
            self._reset(task, root)
            reset = True

        task_sha = self._sha256(task.canonical_json().encode("utf-8"))
        stdout = result.stdout.encode("utf-8")
        stderr = result.stderr.encode("utf-8")
        argv = json.dumps(
            list(template.argv),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        return CommandReceipt(
            task_id=task.task_id,
            task_sha256=task_sha,
            base_sha=task.base_sha,
            command_id=command_id,
            argv_sha256=self._sha256(argv),
            cwd=template.cwd,
            returncode=result.returncode,
            stdout_sha256=self._sha256(stdout),
            stderr_sha256=self._sha256(stderr),
            output_bytes=len(stdout) + len(stderr),
            duration_ms=duration_ms,
            workspace_before_sha256=before_sha,
            workspace_after_sha256=after_sha,
            workspace_unchanged=unchanged,
            workspace_reset=reset,
            passed=result.returncode == 0 and unchanged,
        )
