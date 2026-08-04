"""Ephemeral detached-worktree management.

Workspace Git operations use only an explicitly supplied ``TrustedGitRunner``.
The generic subprocess runner remains available for separately reviewed project
commands, but it is no longer a Git-selection boundary.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .contract import ContractError, DevelopmentTask
from .trusted_git_runtime import TrustedGitRunner, TrustedGitRuntimeError

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class WorkspaceError(RuntimeError):
    """The requested workspace operation could not be proven safe."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        max_output_bytes: int,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    """Bounded no-shell subprocess runner for non-Git project commands."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        max_output_bytes: int,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        if not args or any(not isinstance(item, str) or not item for item in args):
            raise WorkspaceError("command arguments must be non-empty strings")
        if timeout_seconds <= 0 or max_output_bytes <= 0:
            raise WorkspaceError("command bounds must be positive")
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        merged_env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                list(args),
                cwd=cwd,
                env=merged_env,
                shell=False,
                text=False,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceError(f"command failed to complete: {args[0]}") from exc
        stdout_raw = completed.stdout or b""
        stderr_raw = completed.stderr or b""
        if len(stdout_raw) + len(stderr_raw) > max_output_bytes:
            raise WorkspaceError("command output exceeded the task budget")
        return CommandResult(
            args=tuple(args),
            returncode=completed.returncode,
            stdout=stdout_raw.decode("utf-8", errors="replace"),
            stderr=stderr_raw.decode("utf-8", errors="replace"),
        )


class WorkspaceManager:
    """Create exact-SHA detached worktrees through one trusted Git runtime."""

    def __init__(
        self,
        root: Path,
        *,
        git_runner: TrustedGitRunner,
    ) -> None:
        if not isinstance(git_runner, TrustedGitRunner):
            raise WorkspaceError("workspace manager requires a trusted Git runner")
        self.root = root.resolve()
        self.git_runner = git_runner

    def workspace_path(self, task: DevelopmentTask) -> Path:
        if "/" in task.task_id or "\\" in task.task_id:
            raise ContractError("task_id cannot contain path separators")
        target = (self.root / task.task_id).resolve()
        if target.parent != self.root:
            raise WorkspaceError("workspace path escaped the configured root")
        return target

    def _git(
        self,
        cwd: Path,
        *args: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> bytes:
        try:
            return self.git_runner.run(
                tuple(args),
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                maximum=max_output_bytes,
            )
        except TrustedGitRuntimeError as exc:
            operation = args[0] if args else "unknown"
            raise WorkspaceError(
                f"trusted Git operation failed: {operation}"
            ) from exc

    def create(self, task: DevelopmentTask, *, source_repo: Path) -> Path:
        source = source_repo.resolve()
        if not source.is_dir() or not (source / ".git").exists():
            raise WorkspaceError("source_repo must be a local git checkout")
        if _SHA40.fullmatch(task.base_sha) is None:
            raise WorkspaceError("task base SHA is invalid")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise WorkspaceError("workspace root must not be a symlink")
        target = self.workspace_path(task)
        if target.exists():
            raise WorkspaceError("workspace already exists")

        self._git(
            source,
            "worktree",
            "add",
            "--detach",
            str(target),
            task.base_sha,
            timeout_seconds=min(task.budget.max_runtime_seconds, 300),
            max_output_bytes=task.budget.max_output_bytes,
        )
        try:
            self._verify(task, target)
        except Exception:
            self.destroy(task, source_repo=source, allow_dirty=True)
            raise
        return target

    def _verify(self, task: DevelopmentTask, target: Path) -> None:
        head = self._git(
            target,
            "rev-parse",
            "HEAD",
            timeout_seconds=30,
            max_output_bytes=64_000,
        ).decode("ascii", errors="strict").strip()
        if head != task.base_sha:
            raise WorkspaceError("workspace HEAD does not match task base SHA")
        status = self._git(
            target,
            "status",
            "--porcelain=v1",
            timeout_seconds=30,
            max_output_bytes=64_000,
        )
        if status.strip():
            raise WorkspaceError("new workspace is not clean")

    def destroy(
        self,
        task: DevelopmentTask,
        *,
        source_repo: Path,
        allow_dirty: bool = False,
    ) -> None:
        source = source_repo.resolve()
        target = self.workspace_path(task)
        if not target.exists():
            return
        args = ["worktree", "remove"]
        if allow_dirty:
            args.append("--force")
        args.append(str(target))
        self._git(
            source,
            *args,
            timeout_seconds=120,
            max_output_bytes=1_000_000,
        )
