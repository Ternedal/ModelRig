"""Allowlisted development commands and deterministic execution receipts.

Command arguments come from the registry, never from a model or task payload.
The executor verifies the exact task base SHA, isolates repository metadata and
snapshots the workspace before and after the command. Any mutation resets the
ephemeral workspace to the exact base SHA.
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
_METADATA_MAX_FILES = 100_000
_METADATA_MAX_BYTES = 64_000_000
_RESERVED_ENV = {"HOME", "XDG_CONFIG_HOME"}


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


class _GitMetadataOverlay:
    """Hide real Git metadata behind a bounded disposable command overlay."""

    def __init__(self, executor: "CommandExecutor", workspace: Path) -> None:
        self.executor = executor
        self.workspace = workspace
        self.dot_git = workspace / ".git"
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._root: Path | None = None
        self._backup: Path | None = None
        self._staged_overlay: Path | None = None
        self._active = False
        self._copied_files = 0
        self._copied_bytes = 0

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    @staticmethod
    def _resolve_git_path(workspace: Path, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = workspace / path
        return path.resolve()

    def _account(self, size: int) -> None:
        self._copied_files += 1
        self._copied_bytes += size
        if (
            self._copied_files > _METADATA_MAX_FILES
            or self._copied_bytes > _METADATA_MAX_BYTES
        ):
            raise CommandExecutionError("Git metadata exceeds overlay bounds")

    def _copy_file(self, source: Path, target: Path) -> None:
        if source.is_symlink() or not source.is_file():
            raise CommandExecutionError("Git metadata contains an unsafe entry")
        size = source.stat().st_size
        self._account(size)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    def _copy_tree(self, source: Path, target: Path) -> None:
        if not source.exists():
            return
        if source.is_symlink() or not source.is_dir():
            raise CommandExecutionError("Git metadata tree is unsafe")
        target.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir(), key=lambda path: path.name):
            destination = target / item.name
            if item.is_symlink():
                raise CommandExecutionError("Git metadata contains a symlink")
            if item.is_dir():
                self._copy_tree(item, destination)
            elif item.is_file():
                self._copy_file(item, destination)
            else:
                raise CommandExecutionError("Git metadata entry is unsupported")

    def _prepare(self, target: Path) -> None:
        if self._backup is None:
            raise CommandExecutionError("Git metadata backup path is unavailable")
        git_dir = self._resolve_git_path(
            self.workspace,
            self.executor._run_git(
                self.workspace,
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
                max_output_bytes=64_000,
            ).strip(),
        )
        common_dir = self._resolve_git_path(
            self.workspace,
            self.executor._run_git(
                self.workspace,
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
                max_output_bytes=64_000,
            ).strip(),
        )
        object_format = self.executor._run_git(
            self.workspace,
            "rev-parse",
            "--show-object-format",
            max_output_bytes=64_000,
        ).strip()
        if object_format not in {"sha1", "sha256"}:
            raise CommandExecutionError("Git object format is unsupported")
        source_objects = common_dir / "objects"
        if not source_objects.is_dir() or source_objects.is_symlink():
            raise CommandExecutionError("Git object directory is unsafe")
        alternate_objects = (
            self._backup / "objects"
            if common_dir == self.dot_git.resolve()
            else source_objects
        )
        if "\n" in str(alternate_objects) or "\r" in str(alternate_objects):
            raise CommandExecutionError("Git object directory path is unsafe")

        target.mkdir(parents=True)
        for name in ("HEAD", "index", "ORIG_HEAD"):
            source = git_dir / name
            if source.exists():
                self._copy_file(source, target / name)
        if not (target / "HEAD").is_file():
            raise CommandExecutionError("Git metadata overlay has no HEAD")
        for source in sorted(git_dir.glob("sharedindex.*")):
            self._copy_file(source, target / source.name)

        self._copy_tree(common_dir / "refs", target / "refs")
        for name in ("packed-refs", "shallow"):
            source = common_dir / name
            if source.exists():
                self._copy_file(source, target / name)
        for name in ("exclude", "attributes"):
            source = common_dir / "info" / name
            if source.exists():
                self._copy_file(source, target / "info" / name)

        config = [
            "[core]",
            f"\trepositoryformatversion = {1 if object_format == 'sha256' else 0}",
            "\tfilemode = true",
            "\tbare = false",
            "\tlogallrefupdates = false",
        ]
        if object_format == "sha256":
            config.extend(("[extensions]", "\tobjectFormat = sha256"))
        config_bytes = ("\n".join(config) + "\n").encode("utf-8")
        self._account(len(config_bytes))
        (target / "config").write_bytes(config_bytes)
        alternates = target / "objects" / "info" / "alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternate_bytes = (str(alternate_objects) + "\n").encode("utf-8")
        self._account(len(alternate_bytes))
        alternates.write_bytes(alternate_bytes)
        (target / "hooks").mkdir()

    @staticmethod
    def _fingerprint(root: Path) -> str:
        if root.is_symlink() or not root.is_dir():
            raise CommandExecutionError("Git metadata overlay is missing or unsafe")
        digest = hashlib.sha256()
        files = 0
        total = 0
        for path in sorted(
            root.rglob("*"),
            key=lambda item: item.relative_to(root).as_posix(),
        ):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            if path.is_symlink():
                raise CommandExecutionError("command created a Git metadata symlink")
            if path.is_dir():
                digest.update(b"D\0" + relative + b"\0")
                continue
            if not path.is_file():
                raise CommandExecutionError("command created unsupported Git metadata")
            file_stat = path.stat()
            size = file_stat.st_size
            files += 1
            total += size
            if files > _METADATA_MAX_FILES or total > _METADATA_MAX_BYTES:
                raise CommandExecutionError("command exceeded Git metadata bounds")
            digest.update(b"F\0" + relative + b"\0")
            digest.update(str(stat.S_IMODE(file_stat.st_mode)).encode("ascii") + b"\0")
            with path.open("rb") as handle:
                while chunk := handle.read(131_072):
                    digest.update(chunk)
            digest.update(b"\0")
        return digest.hexdigest()

    def activate(self, template_env: Mapping[str, str]) -> tuple[str, dict[str, str]]:
        if self.dot_git.is_symlink() or not self.dot_git.exists():
            raise CommandExecutionError("workspace Git metadata entry is unsafe")
        self._temporary = tempfile.TemporaryDirectory(
            prefix=".kaliv-git-overlay-",
            dir=self.workspace.parent,
        )
        self._root = Path(self._temporary.name)
        self._backup = self._root / "original-dot-git"
        self._staged_overlay = self._root / "staged-overlay"
        real_moved = False
        try:
            self._prepare(self._staged_overlay)
            before = self._fingerprint(self._staged_overlay)
            os.replace(self.dot_git, self._backup)
            real_moved = True
            os.replace(self._staged_overlay, self.dot_git)
            self._active = True
            home = self._root / "home"
            xdg = self._root / "xdg"
            disabled_hooks = self._root / "disabled-hooks"
            home.mkdir()
            xdg.mkdir()
            disabled_hooks.mkdir()
            environment = dict(template_env)
            environment.update(
                {
                    "HOME": str(home),
                    "XDG_CONFIG_HOME": str(xdg),
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_OPTIONAL_LOCKS": "0",
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "core.hooksPath",
                    "GIT_CONFIG_VALUE_0": str(disabled_hooks),
                }
            )
            return before, environment
        except Exception:
            try:
                if self._active:
                    self.deactivate()
                elif real_moved and self._backup.exists():
                    if self.dot_git.exists() or self.dot_git.is_symlink():
                        self._remove(self.dot_git)
                    os.replace(self._backup, self.dot_git)
                    if self._temporary is not None:
                        self._temporary.cleanup()
                elif self._temporary is not None:
                    self._temporary.cleanup()
            except Exception as restore_exc:
                raise CommandExecutionError(
                    "Git metadata activation rollback failed"
                ) from restore_exc
            raise

    def deactivate(self) -> str:
        if not self._active or self._root is None or self._backup is None:
            raise CommandExecutionError("Git metadata overlay is not active")
        try:
            after = self._fingerprint(self.dot_git)
        except CommandExecutionError as exc:
            after = hashlib.sha256(
                ("invalid:" + str(exc)).encode("utf-8")
            ).hexdigest()
        restore_error: Exception | None = None
        quarantine = self._root / "discarded-overlay"
        try:
            if self.dot_git.exists() or self.dot_git.is_symlink():
                os.replace(self.dot_git, quarantine)
            os.replace(self._backup, self.dot_git)
            self._active = False
        except Exception as exc:
            restore_error = exc
        try:
            self._remove(quarantine)
            if self._temporary is not None:
                self._temporary.cleanup()
        finally:
            self._temporary = None
        if restore_error is not None:
            raise CommandExecutionError(
                "real Git metadata could not be restored"
            ) from restore_error
        return after


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

    def _reset(self, task: DevelopmentTask, workspace: Path) -> None:
        for args in (
            ("reset", "--hard", task.base_sha),
            ("clean", "-ffdx"),
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
        self._verify_head(task, workspace)
        try:
            _, clean = self._snapshot(workspace)
        except (WorkspaceError, CommandExecutionError) as exc:
            raise CommandExecutionError(
                "workspace reset could not be verified"
            ) from exc
        if not clean:
            raise CommandExecutionError(
                "workspace reset did not produce a clean state"
            )

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
        root = workspace.resolve()
        cwd = self._cwd(root, template.cwd)
        self._verify_head(task, root)
        before_worktree, before_clean = self._snapshot(root)
        if not before_clean:
            raise CommandExecutionError(
                "workspace has staged, unstaged, untracked or ignored changes before command"
            )

        overlay = _GitMetadataOverlay(self, root)
        before_metadata, command_env = overlay.activate(template.env)
        started = time.monotonic()
        try:
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
            finally:
                after_metadata = overlay.deactivate()
        except WorkspaceError as exc:
            self._reset(task, root)
            raise CommandExecutionError(
                "command execution did not complete safely"
            ) from exc
        duration_ms = max(0, int((time.monotonic() - started) * 1_000))

        try:
            self._verify_head(task, root)
            after_worktree, after_clean = self._snapshot(root)
        except (WorkspaceError, CommandExecutionError) as exc:
            self._reset(task, root)
            raise CommandExecutionError(
                "post-command workspace verification failed"
            ) from exc

        before_sha = self._combined_fingerprint(before_worktree, before_metadata)
        after_sha = self._combined_fingerprint(after_worktree, after_metadata)
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
