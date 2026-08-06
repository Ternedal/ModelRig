"""Ephemeral detached-worktree management for the DC-L01 foundation.

This slice defines the exact-SHA workspace contract but deliberately provides no
Git executable, remote, credential or transport implementation. A later reviewed
slice may inject a runner that satisfies ``WorkspaceGitRunner``. The generic
subprocess runner remains limited to separately reviewed fixed project commands.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .contract import ContractError, DevelopmentTask

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SAFE_EXPLICIT_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")


class WorkspaceError(RuntimeError):
    """The requested workspace operation could not be proven safe."""


class RawEvidenceText(str):
    """Decoded display text that retains the exact bytes used for evidence.

    ``CommandExecutor`` historically hashes ``CommandResult.stdout.encode()``.
    Keeping the original bytes behind the UTF-8 encode operation preserves that
    interface for injected runners while preventing lossy replacement decoding
    from changing hashes or byte counts for real subprocess output.
    """

    __slots__ = ("_raw_bytes",)

    def __new__(
        cls,
        value: str,
        raw_bytes: bytes | None = None,
    ) -> "RawEvidenceText":
        if not isinstance(value, str):
            raise WorkspaceError("command output text is invalid")
        raw = value.encode("utf-8") if raw_bytes is None else raw_bytes
        if not isinstance(raw, bytes):
            raise WorkspaceError("command output bytes are invalid")
        instance = super().__new__(cls, value)
        instance._raw_bytes = raw
        return instance

    @classmethod
    def from_bytes(cls, raw: bytes) -> "RawEvidenceText":
        if not isinstance(raw, bytes):
            raise WorkspaceError("command output bytes are invalid")
        return cls(raw.decode("utf-8", errors="replace"), raw)

    @property
    def raw_bytes(self) -> bytes:
        return self._raw_bytes

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        normalized = encoding.replace("_", "-").lower()
        if normalized in {"utf-8", "utf8"}:
            return self._raw_bytes
        return super().encode(encoding, errors)


@dataclass(frozen=True, slots=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def __post_init__(self) -> None:
        for field in ("stdout", "stderr"):
            value = getattr(self, field)
            if isinstance(value, RawEvidenceText):
                continue
            if not isinstance(value, str):
                raise WorkspaceError("command output must be text")
            object.__setattr__(self, field, RawEvidenceText(value))


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
    """Streaming no-shell runner for separately reviewed project commands."""

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
        if env is None:
            merged_env = os.environ.copy()
            for key in tuple(merged_env):
                if key.startswith("GIT_") or key.startswith("LD_"):
                    merged_env.pop(key, None)
        else:
            if any(key.startswith("LD_") for key in env):
                raise WorkspaceError(
                    "command environment cannot install dynamic-loader hooks"
                )
            merged_env = {
                key: os.environ[key]
                for key in _SAFE_EXPLICIT_ENV_KEYS
                if key in os.environ
            }
            merged_env.setdefault("PATH", os.defpath)
            merged_env.update(env)
        merged_env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            result = run_bounded_subprocess(
                tuple(args),
                cwd=Path(cwd).resolve(),
                env=merged_env,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
                stdout_prefix_bytes=max_output_bytes,
                stderr_prefix_bytes=max_output_bytes,
            )
        except BoundedSubprocessError as exc:
            raise WorkspaceError(f"command failed to complete: {args[0]}") from exc
        if result.output_limit_exceeded:
            raise WorkspaceError("command output exceeded the task budget")
        if result.timed_out:
            raise WorkspaceError(f"command timed out: {args[0]}")
        if result.stdout.truncated or result.stderr.truncated:
            raise WorkspaceError("command output evidence is incomplete")
        return CommandResult(
            args=tuple(args),
            returncode=result.returncode,
            stdout=RawEvidenceText.from_bytes(result.stdout.prefix),
            stderr=RawEvidenceText.from_bytes(result.stderr.prefix),
        )


@runtime_checkable
class WorkspaceGitRunner(Protocol):
    """Injected local-Git seam; DC-L01 intentionally ships no implementation."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        maximum: int,
    ) -> bytes: ...


class WorkspaceManager:
    """Create and remove exact-SHA detached worktrees through an injected seam."""

    def __init__(self, root: Path, *, git_runner: WorkspaceGitRunner) -> None:
        if not isinstance(git_runner, WorkspaceGitRunner):
            raise WorkspaceError("workspace manager requires a workspace Git runner")
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
        except Exception as exc:
            operation = args[0] if args else "unknown"
            raise WorkspaceError(f"workspace Git operation failed: {operation}") from exc

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
