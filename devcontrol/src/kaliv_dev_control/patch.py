"""Fail-closed unified-diff application with staged diff evidence."""

from __future__ import annotations

import hashlib
import json
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contract import DevelopmentTask, normalize_repo_path
from .evidence import ScopeReceipt, build_scope_receipt
from .policy import PathPolicy
from .workspace import Runner, SubprocessRunner

PATCH_SCHEMA = "kaliv-development-patch-receipt/v1"
_REGULAR_FILE_MODES = {"100644", "100755"}


class PatchError(RuntimeError):
    """A patch is malformed, out of scope, or cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class PatchSummary:
    changed_paths: tuple[str, ...]
    added_lines: int
    deleted_lines: int


@dataclass(frozen=True, slots=True)
class PatchReceipt:
    task_id: str
    task_sha256: str
    base_sha: str
    patch_sha256: str
    index_diff_sha256: str
    scope: ScopeReceipt
    applied: bool
    schema: str = PATCH_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "patch_sha256": self.patch_sha256,
            "index_diff_sha256": self.index_diff_sha256,
            "scope": self.scope.to_dict(),
            "applied": self.applied,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class PatchApplier:
    """Apply one non-binary, non-rename patch to the ephemeral index."""

    _FORBIDDEN_PREFIXES = (
        "GIT binary patch",
        "Binary files ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
        "similarity index ",
        "dissimilarity index ",
        "old mode ",
        "new mode ",
    )

    def __init__(self, runner: Runner | None = None) -> None:
        self.runner = runner or SubprocessRunner()

    def parse(
        self,
        task: DevelopmentTask,
        patch_text: str,
    ) -> PatchSummary:
        if (
            not isinstance(patch_text, str)
            or not patch_text
            or "\x00" in patch_text
        ):
            raise PatchError("patch must be non-empty UTF-8 text")
        if len(patch_text.encode("utf-8")) > min(
            task.budget.max_output_bytes,
            10_000_000,
        ):
            raise PatchError("patch exceeds task output budget")

        paths: list[str] = []
        added_lines = 0
        deleted_lines = 0
        in_hunk = False

        for line in patch_text.splitlines():
            if line.startswith(self._FORBIDDEN_PREFIXES):
                raise PatchError("patch contains an unsupported operation")
            if line.startswith(("new file mode ", "deleted file mode ")):
                mode = line.rsplit(" ", 1)[-1]
                if mode not in _REGULAR_FILE_MODES:
                    raise PatchError("patch file mode is unsupported")

            if line.startswith("diff --git "):
                in_hunk = False
                try:
                    parts = shlex.split(line)
                except ValueError as exc:
                    raise PatchError("patch header quoting is invalid") from exc
                if (
                    len(parts) != 4
                    or parts[:2] != ["diff", "--git"]
                    or not parts[2].startswith("a/")
                    or not parts[3].startswith("b/")
                ):
                    raise PatchError("patch has a malformed diff header")

                left = normalize_repo_path(parts[2][2:], name="patch path")
                right = normalize_repo_path(parts[3][2:], name="patch path")
                if left != right:
                    raise PatchError("renames and copies are not supported")
                if left in paths:
                    raise PatchError("patch repeats a changed path")
                if left == ".git" or left.startswith(".git/"):
                    raise PatchError("git metadata is always protected")
                paths.append(left)
            elif line.startswith("@@"):
                in_hunk = True
            elif in_hunk and line.startswith("+"):
                added_lines += 1
            elif in_hunk and line.startswith("-"):
                deleted_lines += 1

        if not paths:
            raise PatchError("patch contains no diff entries")

        decision = PathPolicy(task).evaluate(
            paths,
            added_lines=added_lines,
            deleted_lines=deleted_lines,
        )
        if not decision.passed:
            raise PatchError(
                "; ".join(decision.details) or "patch violates task scope"
            )
        return PatchSummary(
            changed_paths=tuple(sorted(paths)),
            added_lines=added_lines,
            deleted_lines=deleted_lines,
        )

    def _run(
        self,
        workspace: Path,
        args: list[str],
        task: DevelopmentTask,
        max_output_bytes: int | None = None,
    ) -> str:
        result = self.runner.run(
            ["git", *args],
            cwd=workspace,
            timeout_seconds=min(task.budget.max_runtime_seconds, 300),
            max_output_bytes=max_output_bytes or task.budget.max_output_bytes,
        )
        if result.returncode != 0:
            raise PatchError(f"git {args[0]} failed")
        return result.stdout

    def _verify_head(self, task: DevelopmentTask, workspace: Path) -> None:
        head = self._run(workspace, ["rev-parse", "HEAD"], task, 64_000).strip()
        if head != task.base_sha:
            raise PatchError("workspace HEAD does not match task base SHA")

    def _workspace_state(
        self,
        task: DevelopmentTask,
        workspace: Path,
    ) -> tuple[str, str, str, str]:
        return (
            self._run(
                workspace,
                ["diff", "--cached", "--name-only", "-z", "--"],
                task,
                2_000_000,
            ),
            self._run(
                workspace,
                ["diff", "--name-only", "-z", "--"],
                task,
                2_000_000,
            ),
            self._run(
                workspace,
                ["ls-files", "--others", "--exclude-standard", "-z"],
                task,
                2_000_000,
            ),
            self._run(
                workspace,
                [
                    "ls-files",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "-z",
                ],
                task,
                2_000_000,
            ),
        )

    def _reset(self, task: DevelopmentTask, workspace: Path) -> None:
        for args in (
            ["reset", "--hard", task.base_sha],
            ["clean", "-ffdx"],
        ):
            self._run(workspace, args, task, 2_000_000)
        self._verify_head(task, workspace)
        if any(self._workspace_state(task, workspace)):
            raise PatchError("workspace reset did not produce a clean state")

    def _reject_dirty_workspace(
        self,
        task: DevelopmentTask,
        workspace: Path,
    ) -> None:
        if not any(self._workspace_state(task, workspace)):
            return
        self._reset(task, workspace)
        raise PatchError(
            "workspace has staged, unstaged, untracked or ignored changes"
        )

    @staticmethod
    def _verify_paths_are_regular(
        workspace: Path,
        paths: tuple[str, ...],
    ) -> None:
        root = workspace.resolve()
        for relative in paths:
            candidate = root / PurePosixPath(relative)
            cursor = candidate
            while cursor != root:
                if cursor.is_symlink():
                    raise PatchError("patch path contains a symlink")
                cursor = cursor.parent
            resolved = candidate.resolve(strict=False)
            if not resolved.is_relative_to(root):
                raise PatchError("patch path escaped workspace")
            if candidate.exists() and not candidate.is_file():
                raise PatchError("patch target is not a regular file")

    def _inspect_index(
        self,
        task: DevelopmentTask,
        workspace: Path,
    ) -> tuple[tuple[str, ...], int, int, Any, str]:
        numstat = self._run(
            workspace,
            ["diff", "--cached", "--numstat", "-z", "--no-renames", "--"],
            task,
        )
        paths: list[str] = []
        added_lines = 0
        deleted_lines = 0
        for record in numstat.split("\x00"):
            if not record:
                continue
            fields = record.split("\t", 2)
            if len(fields) != 3 or fields[0] == "-" or fields[1] == "-":
                raise PatchError(
                    "binary or malformed staged diff is not supported"
                )
            try:
                added = int(fields[0])
                deleted = int(fields[1])
            except ValueError as exc:
                raise PatchError("staged diff statistics are invalid") from exc
            path = normalize_repo_path(fields[2], name="staged path")
            paths.append(path)
            added_lines += added
            deleted_lines += deleted

        unstaged = self._run(
            workspace,
            ["diff", "--name-only", "-z", "--"],
            task,
        )
        untracked = self._run(
            workspace,
            ["ls-files", "--others", "--exclude-standard", "-z"],
            task,
        )
        ignored = self._run(
            workspace,
            [
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
            ],
            task,
        )
        if unstaged or untracked or ignored:
            raise PatchError(
                "patch left unstaged, untracked or ignored changes"
            )

        decision = PathPolicy(task).evaluate(
            paths,
            added_lines=added_lines,
            deleted_lines=deleted_lines,
        )
        if not decision.passed:
            raise PatchError(
                "; ".join(decision.details)
                or "staged diff violates task scope"
            )
        diff = self._run(
            workspace,
            ["diff", "--cached", "--binary", "--no-ext-diff", "--"],
            task,
        )
        return (
            tuple(sorted(paths)),
            added_lines,
            deleted_lines,
            decision,
            diff,
        )

    def apply(
        self,
        task: DevelopmentTask,
        workspace: Path,
        patch_text: str,
    ) -> PatchReceipt:
        root = workspace.resolve()
        self._verify_head(task, root)
        self._reject_dirty_workspace(task, root)
        summary = self.parse(task, patch_text)
        self._verify_paths_are_regular(root, summary.changed_paths)

        patch_bytes = patch_text.encode("utf-8")
        patch_sha = hashlib.sha256(patch_bytes).hexdigest()
        applied = False
        root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=root.parent,
            prefix=".kaliv-patch-",
            suffix=".diff",
            delete=False,
        ) as handle:
            handle.write(patch_bytes)
            patch_path = Path(handle.name)

        try:
            self._run(
                root,
                [
                    "apply",
                    "--check",
                    "--index",
                    "--whitespace=error-all",
                    str(patch_path),
                ],
                task,
            )
            self._run(
                root,
                [
                    "apply",
                    "--index",
                    "--whitespace=error-all",
                    str(patch_path),
                ],
                task,
            )
            applied = True

            paths, added, deleted, decision, diff = self._inspect_index(
                task,
                root,
            )
            if (
                paths != summary.changed_paths
                or added != summary.added_lines
                or deleted != summary.deleted_lines
            ):
                raise PatchError(
                    "staged diff does not match parsed patch authority"
                )

            scope = build_scope_receipt(
                task,
                decision,
                added_lines=added,
                deleted_lines=deleted,
            )
            task_sha = hashlib.sha256(
                task.canonical_json().encode("utf-8")
            ).hexdigest()
            return PatchReceipt(
                task_id=task.task_id,
                task_sha256=task_sha,
                base_sha=task.base_sha,
                patch_sha256=patch_sha,
                index_diff_sha256=hashlib.sha256(
                    diff.encode("utf-8")
                ).hexdigest(),
                scope=scope,
                applied=True,
            )
        except Exception:
            if applied:
                self._reset(task, root)
            raise
        finally:
            patch_path.unlink(missing_ok=True)
