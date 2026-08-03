"""Ephemeral detached-worktree management.

The runner never invokes a shell. The first slice only prepares and verifies a
workspace; it does not edit files or run project commands.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .contract import ContractError, DevelopmentTask

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
    """Bounded no-shell subprocess runner."""

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
    """Create exact-SHA detached worktrees under one controlled root."""

    def __init__(self, root: Path, runner: Runner | None = None) -> None:
        self.root = root.resolve()
        self.runner = runner or SubprocessRunner()

    def workspace_path(self, task: DevelopmentTask) -> Path:
        if "/" in task.task_id or "\\" in task.task_id:
            raise ContractError("task_id cannot contain path separators")
        target = (self.root / task.task_id).resolve()
        if target.parent != self.root:
            raise WorkspaceError("workspace path escaped the configured root")
        return target

    def create(self, task: DevelopmentTask, *, source_repo: Path) -> Path:
        source = source_repo.resolve()
        if shutil.which("git") is None:
            raise WorkspaceError("git is required")
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

        result = self.runner.run(
            ["git", "worktree", "add", "--detach", str(target), task.base_sha],
            cwd=source,
            timeout_seconds=min(task.budget.max_runtime_seconds, 300),
            max_output_bytes=task.budget.max_output_bytes,
        )
        if result.returncode != 0:
            raise WorkspaceError("git could not create the detached worktree")
        try:
            self._verify(task, target)
        except Exception:
            self.destroy(task, source_repo=source, allow_dirty=True)
            raise
        return target

    def _verify(self, task: DevelopmentTask, target: Path) -> None:
        head = self.runner.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            timeout_seconds=30,
            max_output_bytes=64_000,
        )
        if head.returncode != 0 or head.stdout.strip() != task.base_sha:
            raise WorkspaceError("workspace HEAD does not match task base SHA")
        status = self.runner.run(
            ["git", "status", "--porcelain=v1"],
            cwd=target,
            timeout_seconds=30,
            max_output_bytes=64_000,
        )
        if status.returncode != 0 or status.stdout.strip():
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
        args = ["git", "worktree", "remove"]
        if allow_dirty:
            args.append("--force")
        args.append(str(target))
        result = self.runner.run(
            args,
            cwd=source,
            timeout_seconds=120,
            max_output_bytes=1_000_000,
        )
        if result.returncode != 0:
            raise WorkspaceError("git could not remove the worktree")
