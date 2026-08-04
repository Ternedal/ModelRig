"""Git-aware receipt orchestration for the sole verified Tier-A runtime path."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .contract import DevelopmentTask
from .runtime_closure_model import SignedRuntimeClosureManifest
from .tier_a_authority import TierAExecutionError, _has_linkish_component
from .tier_a_execution_v3 import (
    TierAExecutionTimeout,
    run_verified_tier_a_command,
)
from .tier_a_result import TierAExecutionResult

GIT_SNAPSHOT_SCHEMA = "kaliv-development-git-workspace-snapshot/v1"
TIER_A_COMMAND_RECEIPT_SCHEMA = "kaliv-development-tier-a-command-receipt/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_MAX_GIT_OUTPUT_BYTES = 32 * 1024 * 1024


class TierACommandReceiptError(TierAExecutionError):
    """Git evidence could not be joined to one verified Tier-A execution."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hex(name: str, value: Any, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise TierACommandReceiptError(f"{name} is invalid")
    return value


def _integer(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise TierACommandReceiptError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class GitWorkspaceSnapshot:
    head_sha: str
    staged_patch_sha256: str
    staged_patch_bytes: int
    unstaged_patch_sha256: str
    unstaged_patch_bytes: int
    untracked_paths_sha256: str
    untracked_path_count: int
    schema: str = GIT_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != GIT_SNAPSHOT_SCHEMA:
            raise TierACommandReceiptError("unsupported Git snapshot schema")
        _hex("Git snapshot head", self.head_sha, _HEX40)
        _hex("Git snapshot staged patch hash", self.staged_patch_sha256, _HEX64)
        _hex("Git snapshot unstaged patch hash", self.unstaged_patch_sha256, _HEX64)
        _hex("Git snapshot untracked paths hash", self.untracked_paths_sha256, _HEX64)
        _integer(
            "Git snapshot staged patch bytes",
            self.staged_patch_bytes,
            0,
            _MAX_GIT_OUTPUT_BYTES,
        )
        _integer(
            "Git snapshot unstaged patch bytes",
            self.unstaged_patch_bytes,
            0,
            _MAX_GIT_OUTPUT_BYTES,
        )
        _integer(
            "Git snapshot untracked path count",
            self.untracked_path_count,
            0,
            1_000_000,
        )

    @property
    def has_unstaged_or_untracked(self) -> bool:
        return self.unstaged_patch_bytes > 0 or self.untracked_path_count > 0

    @classmethod
    def from_mapping(cls, value: Any) -> "GitWorkspaceSnapshot":
        fields = {
            "schema",
            "head_sha",
            "staged_patch_sha256",
            "staged_patch_bytes",
            "unstaged_patch_sha256",
            "unstaged_patch_bytes",
            "untracked_paths_sha256",
            "untracked_path_count",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise TierACommandReceiptError("Git snapshot fields mismatch")
        return cls(
            schema=value["schema"],
            head_sha=value["head_sha"],
            staged_patch_sha256=value["staged_patch_sha256"],
            staged_patch_bytes=value["staged_patch_bytes"],
            unstaged_patch_sha256=value["unstaged_patch_sha256"],
            unstaged_patch_bytes=value["unstaged_patch_bytes"],
            untracked_paths_sha256=value["untracked_paths_sha256"],
            untracked_path_count=value["untracked_path_count"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "head_sha": self.head_sha,
            "staged_patch_sha256": self.staged_patch_sha256,
            "staged_patch_bytes": self.staged_patch_bytes,
            "unstaged_patch_sha256": self.unstaged_patch_sha256,
            "unstaged_patch_bytes": self.unstaged_patch_bytes,
            "untracked_paths_sha256": self.untracked_paths_sha256,
            "untracked_path_count": self.untracked_path_count,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TierACommandReceipt:
    task_id: str
    task_sha256: str
    base_sha: str
    command_id: str
    tier_a_result: TierAExecutionResult
    workspace_before: GitWorkspaceSnapshot
    workspace_after: GitWorkspaceSnapshot
    workspace_reset: GitWorkspaceSnapshot | None
    workspace_unchanged: bool
    workspace_reset_performed: bool
    passed: bool
    schema: str = TIER_A_COMMAND_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != TIER_A_COMMAND_RECEIPT_SCHEMA:
            raise TierACommandReceiptError("unsupported Tier-A command receipt schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise TierACommandReceiptError("receipt task id is invalid")
        if (
            not isinstance(self.command_id, str)
            or _COMMAND_ID.fullmatch(self.command_id) is None
        ):
            raise TierACommandReceiptError("receipt command id is invalid")
        _hex("receipt task hash", self.task_sha256, _HEX64)
        _hex("receipt base SHA", self.base_sha, _HEX40)
        if not isinstance(self.tier_a_result, TierAExecutionResult):
            raise TierACommandReceiptError("receipt Tier-A result is invalid")
        if not isinstance(self.workspace_before, GitWorkspaceSnapshot) or not isinstance(
            self.workspace_after, GitWorkspaceSnapshot
        ):
            raise TierACommandReceiptError("receipt workspace snapshots are invalid")
        if self.workspace_reset is not None and not isinstance(
            self.workspace_reset, GitWorkspaceSnapshot
        ):
            raise TierACommandReceiptError("receipt reset snapshot is invalid")
        for name, value in (
            ("workspace_unchanged", self.workspace_unchanged),
            ("workspace_reset_performed", self.workspace_reset_performed),
            ("passed", self.passed),
        ):
            if not isinstance(value, bool):
                raise TierACommandReceiptError(f"receipt {name} flag is invalid")
        if (
            self.tier_a_result.task_id,
            self.tier_a_result.task_sha256,
            self.tier_a_result.base_sha,
            self.tier_a_result.command_id,
        ) != (self.task_id, self.task_sha256, self.base_sha, self.command_id):
            raise TierACommandReceiptError(
                "receipt identity does not match the Tier-A result"
            )
        expected_unchanged = (
            self.workspace_before.sha256 == self.workspace_after.sha256
        )
        if self.workspace_unchanged != expected_unchanged:
            raise TierACommandReceiptError(
                "receipt workspace unchanged flag is inconsistent"
            )
        if self.workspace_reset_performed != (self.workspace_reset is not None):
            raise TierACommandReceiptError(
                "receipt reset flag does not match reset evidence"
            )
        if self.workspace_reset is not None:
            reset = self.workspace_reset
            if (
                reset.head_sha != self.base_sha
                or reset.staged_patch_bytes
                or reset.unstaged_patch_bytes
                or reset.untracked_path_count
            ):
                raise TierACommandReceiptError(
                    "receipt reset evidence is not exact-base clean"
                )
        expected_passed = (
            self.tier_a_result.passed
            and self.workspace_unchanged
            and not self.workspace_reset_performed
        )
        if self.passed != expected_passed:
            raise TierACommandReceiptError("receipt passed flag is inconsistent")

    @classmethod
    def create(
        cls,
        *,
        task: DevelopmentTask,
        result: TierAExecutionResult,
        before: GitWorkspaceSnapshot,
        after: GitWorkspaceSnapshot,
        reset: GitWorkspaceSnapshot | None,
    ) -> "TierACommandReceipt":
        task_sha256 = hashlib.sha256(
            task.canonical_json().encode("utf-8")
        ).hexdigest()
        unchanged = before.sha256 == after.sha256
        return cls(
            task_id=task.task_id,
            task_sha256=task_sha256,
            base_sha=task.base_sha,
            command_id=result.command_id,
            tier_a_result=result,
            workspace_before=before,
            workspace_after=after,
            workspace_reset=reset,
            workspace_unchanged=unchanged,
            workspace_reset_performed=reset is not None,
            passed=result.passed and unchanged and reset is None,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "TierACommandReceipt":
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "base_sha",
            "command_id",
            "tier_a_result",
            "workspace_before",
            "workspace_after",
            "workspace_reset",
            "workspace_unchanged",
            "workspace_reset_performed",
            "passed",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise TierACommandReceiptError("Tier-A command receipt fields mismatch")
        reset = value["workspace_reset"]
        return cls(
            schema=value["schema"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            base_sha=value["base_sha"],
            command_id=value["command_id"],
            tier_a_result=TierAExecutionResult.from_mapping(value["tier_a_result"]),
            workspace_before=GitWorkspaceSnapshot.from_mapping(
                value["workspace_before"]
            ),
            workspace_after=GitWorkspaceSnapshot.from_mapping(value["workspace_after"]),
            workspace_reset=(
                None if reset is None else GitWorkspaceSnapshot.from_mapping(reset)
            ),
            workspace_unchanged=value["workspace_unchanged"],
            workspace_reset_performed=value["workspace_reset_performed"],
            passed=value["passed"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "command_id": self.command_id,
            "tier_a_result": self.tier_a_result.to_dict(),
            "workspace_before": self.workspace_before.to_dict(),
            "workspace_after": self.workspace_after.to_dict(),
            "workspace_reset": (
                None if self.workspace_reset is None else self.workspace_reset.to_dict()
            ),
            "workspace_unchanged": self.workspace_unchanged,
            "workspace_reset_performed": self.workspace_reset_performed,
            "passed": self.passed,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class _GitWorkspaceEvidence:
    def __init__(self, workspace: Path, task: DevelopmentTask) -> None:
        if not isinstance(task, DevelopmentTask):
            raise TierACommandReceiptError(
                "Git receipt orchestration requires a validated task"
            )
        raw = Path(workspace)
        if not raw.is_absolute():
            raise TierACommandReceiptError("workspace must be absolute")
        self.workspace = Path(os.path.realpath(os.path.abspath(raw)))
        if (
            not self.workspace.is_dir()
            or _has_linkish_component(self.workspace)
            or not (self.workspace / ".git").exists()
        ):
            raise TierACommandReceiptError(
                "workspace must be an existing link-free Git worktree"
            )
        self.task = task
        top = self._git("rev-parse", "--show-toplevel").decode(
            "utf-8", errors="strict"
        ).strip()
        if os.path.normcase(os.path.realpath(top)) != os.path.normcase(
            os.fspath(self.workspace)
        ):
            raise TierACommandReceiptError(
                "Git top-level does not match the exact workspace"
            )

    def _git(self, *args: str, maximum: int = _MAX_GIT_OUTPUT_BYTES) -> bytes:
        command = [
            "git",
            "-c",
            "core.quotepath=false",
            "-c",
            "color.ui=false",
            *args,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TierACommandReceiptError(
                f"Git evidence command failed to complete: {args[0]}"
            ) from exc
        output_bytes = len(completed.stdout) + len(completed.stderr)
        if output_bytes > maximum:
            raise TierACommandReceiptError(
                f"Git evidence command exceeded its output bound: {args[0]}"
            )
        if completed.returncode != 0:
            raise TierACommandReceiptError(
                f"Git evidence command failed: {args[0]}"
            )
        return completed.stdout

    def snapshot(self) -> GitWorkspaceSnapshot:
        head = self._git("rev-parse", "HEAD", maximum=4096).decode(
            "ascii", errors="strict"
        ).strip()
        staged = self._git(
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        )
        unstaged = self._git(
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        )
        untracked = self._git(
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        )
        paths = tuple(path for path in untracked.split(b"\0") if path)
        return GitWorkspaceSnapshot(
            head_sha=head,
            staged_patch_sha256=hashlib.sha256(staged).hexdigest(),
            staged_patch_bytes=len(staged),
            unstaged_patch_sha256=hashlib.sha256(unstaged).hexdigest(),
            unstaged_patch_bytes=len(unstaged),
            untracked_paths_sha256=hashlib.sha256(untracked).hexdigest(),
            untracked_path_count=len(paths),
        )

    def reset_to_base(self) -> GitWorkspaceSnapshot:
        self._git("reset", "--hard", self.task.base_sha, maximum=2_000_000)
        self._git("clean", "-fd", maximum=2_000_000)
        snapshot = self.snapshot()
        if (
            snapshot.head_sha != self.task.base_sha
            or snapshot.staged_patch_bytes
            or snapshot.unstaged_patch_bytes
            or snapshot.untracked_path_count
        ):
            raise TierACommandReceiptError(
                "workspace could not be proven reset to the exact task base"
            )
        return snapshot


def _single_command_id(task: DevelopmentTask) -> str:
    if (
        len(task.allowed_command_ids) != 1
        or task.required_tests != task.allowed_command_ids
    ):
        raise TierACommandReceiptError(
            "Tier-A receipt orchestration requires one exact required command"
        )
    return task.allowed_command_ids[0]


def _runtime_closure_root(
    workspace: Path,
    signed: SignedRuntimeClosureManifest,
) -> Path:
    if not isinstance(signed, SignedRuntimeClosureManifest):
        raise TierACommandReceiptError(
            "Tier-A receipt orchestration requires a signed runtime closure"
        )
    manifest = signed.manifest
    relative = PurePosixPath(
        ".kaliv",
        "runtime-closures",
        manifest.tool_id,
        manifest.sha256,
    )
    root = workspace.joinpath(*relative.parts)
    try:
        root.relative_to(workspace)
    except ValueError as exc:
        raise TierACommandReceiptError(
            "runtime closure cleanup path escaped the workspace"
        ) from exc
    return root


def _cleanup_runtime_closure(workspace: Path, root: Path) -> None:
    if root.exists():
        if _has_linkish_component(root):
            raise TierACommandReceiptError(
                "runtime closure cleanup refuses a linked path"
            )
        shutil.rmtree(root)
    stop = workspace / ".kaliv"
    parent = root.parent
    while parent != workspace and parent != stop.parent:
        if parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
        if parent == stop:
            break
        parent = parent.parent
    if root.exists():
        raise TierACommandReceiptError(
            "runtime closure cleanup could not be proven complete"
        )


def run_single_verified_tier_a_command_with_receipt(
    task: DevelopmentTask,
    catalog: Any,
    toolchain: Any,
    attestation: Any,
    physical_verifier: Any,
    *,
    signed_runtime_closure: SignedRuntimeClosureManifest,
    runtime_closure_verifier: Any,
    trusted_runtime_root: Path,
    workspace_root: Path,
    control_plane_root: Path,
    source_env: Mapping[str, str] | None = None,
    executable_verifier: Any | None = None,
    process_memory_bytes: int = 512 * 1024 * 1024,
    active_process_limit: int = 8,
) -> TierACommandReceipt:
    """Run the task's sole command and join it to exact Git before/after/reset evidence."""

    command_id = _single_command_id(task)
    evidence = _GitWorkspaceEvidence(Path(workspace_root), task)
    before = evidence.snapshot()
    if before.head_sha != task.base_sha:
        raise TierACommandReceiptError(
            "workspace HEAD does not match the exact task base"
        )
    if before.has_unstaged_or_untracked:
        raise TierACommandReceiptError(
            "workspace must contain only an optional staged patch before execution"
        )
    runtime_root = _runtime_closure_root(
        evidence.workspace,
        signed_runtime_closure,
    )

    result: TierAExecutionResult | None = None
    execution_error: Exception | None = None
    try:
        try:
            result = run_verified_tier_a_command(
                task,
                catalog,
                toolchain,
                attestation,
                physical_verifier,
                command_id,
                signed_runtime_closure=signed_runtime_closure,
                runtime_closure_verifier=runtime_closure_verifier,
                trusted_runtime_root=trusted_runtime_root,
                workspace_root=evidence.workspace,
                control_plane_root=control_plane_root,
                source_env=source_env,
                executable_verifier=executable_verifier,
                process_memory_bytes=process_memory_bytes,
                active_process_limit=active_process_limit,
            )
        except TierAExecutionTimeout as exc:
            result = exc.result
        except Exception as exc:
            execution_error = exc
    finally:
        try:
            _cleanup_runtime_closure(evidence.workspace, runtime_root)
        except Exception as cleanup_exc:
            try:
                evidence.reset_to_base()
            except Exception as reset_exc:
                raise TierACommandReceiptError(
                    "runtime cleanup and exact-base reset both failed"
                ) from reset_exc
            raise TierACommandReceiptError(
                "runtime closure cleanup failed; workspace was reset"
            ) from cleanup_exc

    after = evidence.snapshot()
    reset: GitWorkspaceSnapshot | None = None
    if before.sha256 != after.sha256:
        reset = evidence.reset_to_base()

    if execution_error is not None:
        raise TierACommandReceiptError(
            "verified Tier-A execution failed before producing a result"
        ) from execution_error
    if not isinstance(result, TierAExecutionResult):
        raise TierACommandReceiptError(
            "verified Tier-A execution returned no canonical result"
        )
    return TierACommandReceipt.create(
        task=task,
        result=result,
        before=before,
        after=after,
        reset=reset,
    )
