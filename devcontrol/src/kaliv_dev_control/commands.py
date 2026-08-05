"""Allowlisted development commands and deterministic execution receipts.

Command arguments come from the registry, never from a model or task payload.
The executor verifies the exact task base SHA and runs each command in a fully
disposable local Git sandbox. The source workspace and its Git metadata are never
exposed through sandbox configuration, alternates or explicit command environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contract import DevelopmentTask
from .workspace import Runner, SubprocessRunner, WorkspaceError

_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
RECEIPT_SCHEMA = "kaliv-development-command-receipt/v1"
_SANDBOX_MAX_FILES = 250_000
_SANDBOX_MAX_BYTES = 1_000_000_000
_RESERVED_ENV = {"HOME", "XDG_CONFIG_HOME", "TMPDIR", "PWD"}


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
        if isinstance(self.argv, (str, bytes)) or not isinstance(self.argv, Sequence):
            raise CommandPolicyError("argv must be a sequence of strings")
        immutable_argv = tuple(self.argv)
        if not immutable_argv or any(
            not isinstance(item, str) or not item or "\x00" in item
            for item in immutable_argv
        ):
            raise CommandPolicyError(
                "argv must contain canonical non-empty strings"
            )
        object.__setattr__(self, "argv", immutable_argv)
        if not isinstance(self.cwd, str) or not self.cwd or "\x00" in self.cwd:
            raise CommandPolicyError("command cwd must be repository-relative")
        if self.cwd != ".":
            raw_parts = self.cwd.split("/")
            path = PurePosixPath(self.cwd)
            if (
                self.cwd.startswith("/")
                or "\\" in self.cwd
                or any(part in {"", ".", ".."} for part in raw_parts)
                or path.as_posix() != self.cwd
            ):
                raise CommandPolicyError(
                    "command cwd must be canonical and repository-relative"
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
            if key.startswith("GIT_") or key in _RESERVED_ENV:
                raise CommandPolicyError(
                    "command environment cannot override Git isolation"
                )
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
    """Return an empty registry until templates are separately reviewed."""

    return CommandRegistry(())


class _CommandSandbox:
    """Build and destroy an independent exact-HEAD Git repository."""

    def __init__(
        self,
        executor: "CommandExecutor",
        task: DevelopmentTask,
        source: Path,
    ) -> None:
        self.executor = executor
        self.task = task
        self.source = source
        self.root: Path | None = None
        self.repository: Path | None = None
        self.home: Path | None = None
        self.xdg: Path | None = None
        self.tmp: Path | None = None
        self.disabled_hooks: Path | None = None

    @staticmethod
    def _chmod_for_removal(path: Path) -> None:
        try:
            if not path.is_symlink():
                path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass

    def cleanup(self) -> None:
        if self.root is None or not self.root.exists():
            return
        for path in sorted(
            self.root.rglob("*"),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            self._chmod_for_removal(path)
        self._chmod_for_removal(self.root)
        try:
            shutil.rmtree(self.root)
        except OSError as exc:
            raise CommandExecutionError(
                "command sandbox could not be destroyed"
            ) from exc
        finally:
            self.root = None
            self.repository = None

    @staticmethod
    def _bounded_fingerprint(root: Path) -> str:
        if root.is_symlink() or not root.is_dir():
            raise CommandExecutionError("sandbox Git metadata is missing or unsafe")
        digest = hashlib.sha256()
        files = 0
        total = 0
        for path in sorted(
            root.rglob("*"),
            key=lambda item: item.relative_to(root).as_posix(),
        ):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            if path.is_symlink():
                raise CommandExecutionError(
                    "command created a Git metadata symlink"
                )
            if path.is_dir():
                digest.update(b"D\0" + relative + b"\0")
                continue
            if not path.is_file():
                raise CommandExecutionError(
                    "command created unsupported Git metadata"
                )
            file_stat = path.stat()
            files += 1
            total += file_stat.st_size
            if files > _SANDBOX_MAX_FILES or total > _SANDBOX_MAX_BYTES:
                raise CommandExecutionError(
                    "command exceeded Git metadata bounds"
                )
            digest.update(b"F\0" + relative + b"\0")
            digest.update(
                str(stat.S_IMODE(file_stat.st_mode)).encode("ascii") + b"\0"
            )
            with path.open("rb") as handle:
                while chunk := handle.read(131_072):
                    digest.update(chunk)
            digest.update(b"\0")
        return digest.hexdigest()

    def _assert_no_source_disclosure(self) -> None:
        if self.repository is None or self.root is None:
            raise CommandExecutionError("command sandbox is not prepared")
        needles = (
            str(self.source).encode("utf-8"),
            str(self.root / "source.bundle").encode("utf-8"),
        )
        candidates = [self.repository / ".git" / "config"]
        logs = self.repository / ".git" / "logs"
        if logs.exists():
            candidates.extend(path for path in logs.rglob("*") if path.is_file())
        for candidate in candidates:
            data = candidate.read_bytes()
            if any(needle in data for needle in needles):
                raise CommandExecutionError(
                    "command sandbox disclosed the source repository path"
                )
        alternates = self.repository / ".git" / "objects" / "info" / "alternates"
        if alternates.exists():
            raise CommandExecutionError(
                "command sandbox must not use object alternates"
            )

    def create(self) -> tuple[str, str]:
        self.root = Path(
            tempfile.mkdtemp(prefix=".kaliv-command-sandbox-")
        ).resolve()
        if self.root.is_symlink():
            raise CommandExecutionError("command sandbox root is unsafe")
        self.repository = self.root / "repository"
        bundle = self.root / "source.bundle"
        self.home = self.root / "home"
        self.xdg = self.root / "xdg"
        self.tmp = self.root / "tmp"
        self.disabled_hooks = self.root / "disabled-hooks"
        for directory in (self.home, self.xdg, self.tmp, self.disabled_hooks):
            directory.mkdir()

        try:
            self.executor._run_git(
                self.source,
                "bundle",
                "create",
                str(bundle),
                "HEAD",
                timeout_seconds=300,
                max_output_bytes=4_000_000,
            )
            if (
                bundle.is_symlink()
                or not bundle.is_file()
                or bundle.stat().st_size > _SANDBOX_MAX_BYTES
            ):
                raise CommandExecutionError(
                    "command sandbox bundle is unsafe or too large"
                )
            self.executor._run_git(
                self.root,
                "clone",
                "--no-checkout",
                "--no-tags",
                "--quiet",
                str(bundle),
                str(self.repository),
                timeout_seconds=300,
                max_output_bytes=4_000_000,
            )
            self.executor._run_git(
                self.repository,
                "checkout",
                "--quiet",
                "--detach",
                self.task.base_sha,
                timeout_seconds=300,
                max_output_bytes=4_000_000,
            )
            self.executor._run_git(
                self.repository,
                "remote",
                "remove",
                "origin",
                max_output_bytes=1_000_000,
            )
            self.executor._run_git(
                self.repository,
                "config",
                "--local",
                "core.hooksPath",
                str(self.disabled_hooks),
                max_output_bytes=1_000_000,
            )
            self.executor._run_git(
                self.repository,
                "config",
                "--local",
                "core.logAllRefUpdates",
                "false",
                max_output_bytes=1_000_000,
            )
            self.executor._run_git(
                self.repository,
                "config",
                "--local",
                "gc.auto",
                "0",
                max_output_bytes=1_000_000,
            )
            logs = self.repository / ".git" / "logs"
            if logs.exists():
                shutil.rmtree(logs)
            for name in ("FETCH_HEAD", "ORIG_HEAD"):
                (self.repository / ".git" / name).unlink(missing_ok=True)
            bundle.unlink()
            self.executor._verify_head(self.task, self.repository)
            worktree, clean = self.executor._snapshot(self.repository)
            if not clean:
                raise CommandExecutionError(
                    "new command sandbox is not clean"
                )
            metadata = self._bounded_fingerprint(
                self.repository / ".git"
            )
            self._assert_no_source_disclosure()
            self.executor._verify_source_clean(self.task, self.source)
            return worktree, metadata
        except Exception:
            self.cleanup()
            raise

    def environment(
        self,
        template_env: Mapping[str, str],
        cwd: Path,
    ) -> dict[str, str]:
        if any(
            value is None
            for value in (
                self.root,
                self.home,
                self.xdg,
                self.tmp,
                self.disabled_hooks,
            )
        ):
            raise CommandExecutionError("command sandbox is not prepared")
        environment = dict(template_env)
        environment.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.xdg),
                "TMPDIR": str(self.tmp),
                "PWD": str(cwd),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.hooksPath",
                "GIT_CONFIG_VALUE_0": str(self.disabled_hooks),
            }
        )
        source_text = str(self.source)
        if any(source_text in value for value in environment.values()):
            raise CommandExecutionError(
                "command environment disclosed the source repository path"
            )
        return environment

    def metadata_fingerprint(self) -> str:
        if self.repository is None:
            raise CommandExecutionError("command sandbox is not prepared")
        return self._bounded_fingerprint(self.repository / ".git")


class CommandExecutor:
    """Execute a fixed command and prove it did not alter repository state."""

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

    @staticmethod
    def _combined_fingerprint(worktree: str, metadata: str) -> str:
        return hashlib.sha256(
            (worktree + "\x00" + metadata).encode("ascii")
        ).hexdigest()

    def _run_git(
        self,
        workspace: Path,
        *args: str,
        max_output_bytes: int = 4_000_000,
        timeout_seconds: int = 60,
    ) -> str:
        result = self.runner.run(
            ["git", *args],
            cwd=workspace,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env={
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
            },
        )
        if result.returncode != 0:
            raise CommandExecutionError(f"git operation failed: {args[0]}")
        return result.stdout

    def _verify_head(self, task: DevelopmentTask, workspace: Path) -> None:
        head = self._run_git(workspace, "rev-parse", "HEAD").strip()
        if head != task.base_sha:
            raise CommandExecutionError(
                "workspace HEAD does not match task base SHA"
            )

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
        ignored = self._run_git(
            workspace,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        )
        fingerprint = self._sha256(cached.encode("utf-8", errors="replace"))
        return fingerprint, not bool(cached or unstaged or untracked or ignored)

    def _verify_source_clean(
        self,
        task: DevelopmentTask,
        workspace: Path,
        expected_fingerprint: str | None = None,
    ) -> str:
        self._verify_head(task, workspace)
        fingerprint, clean = self._snapshot(workspace)
        if not clean:
            raise CommandExecutionError(
                "source workspace has staged, unstaged, untracked or ignored changes"
            )
        if (
            expected_fingerprint is not None
            and fingerprint != expected_fingerprint
        ):
            raise CommandExecutionError(
                "source workspace fingerprint changed during command execution"
            )
        return fingerprint

    @staticmethod
    def _cwd(workspace: Path, relative: str) -> Path:
        root = workspace.resolve()
        target = (
            root
            if relative == "."
            else (root / PurePosixPath(relative)).resolve()
        )
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
        source = workspace.resolve()
        source_text = str(source)
        if any(source_text in argument for argument in template.argv):
            raise CommandPolicyError(
                "command arguments cannot disclose the source workspace"
            )
        source_before = self._verify_source_clean(task, source)
        self._cwd(source, template.cwd)

        sandbox = _CommandSandbox(self, task, source)
        result = None
        duration_ms = 0
        before_worktree = ""
        before_metadata = ""
        after_worktree = ""
        after_metadata = ""
        after_clean = False
        try:
            before_worktree, before_metadata = sandbox.create()
            if sandbox.repository is None:
                raise CommandExecutionError("command sandbox was not created")
            cwd = self._cwd(sandbox.repository, template.cwd)
            command_env = sandbox.environment(template.env, cwd)
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
                    env=command_env,
                )
            except WorkspaceError as exc:
                raise CommandExecutionError(
                    "command execution did not complete safely"
                ) from exc
            duration_ms = max(
                0,
                int((time.monotonic() - started) * 1_000),
            )
            try:
                self._verify_head(task, sandbox.repository)
                after_worktree, after_clean = self._snapshot(
                    sandbox.repository
                )
                after_metadata = sandbox.metadata_fingerprint()
            except (WorkspaceError, CommandExecutionError) as exc:
                raise CommandExecutionError(
                    "post-command workspace verification failed"
                ) from exc
        finally:
            cleanup_error: Exception | None = None
            source_error: Exception | None = None
            try:
                sandbox.cleanup()
            except Exception as exc:
                cleanup_error = exc
            try:
                self._verify_source_clean(
                    task,
                    source,
                    expected_fingerprint=source_before,
                )
            except Exception as exc:
                source_error = exc
            if source_error is not None:
                raise CommandExecutionError(
                    "source workspace integrity could not be verified"
                ) from source_error
            if cleanup_error is not None:
                raise CommandExecutionError(
                    "command sandbox cleanup failed"
                ) from cleanup_error

        if result is None:
            raise CommandExecutionError("command returned no result")
        before_sha = self._combined_fingerprint(
            before_worktree,
            before_metadata,
        )
        after_sha = self._combined_fingerprint(
            after_worktree,
            after_metadata,
        )
        unchanged = before_sha == after_sha and after_clean
        reset = not unchanged

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
