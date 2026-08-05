from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaliv_dev_control.commands import (
    CommandExecutor,
    CommandPolicyError,
    CommandRegistry,
    CommandTemplate,
)
from kaliv_dev_control.contract import (
    DevelopmentTask,
    MergeAuthority,
    Risk,
    TaskBudget,
)
from kaliv_dev_control.files import FileAccessError, WorkspaceFiles
from kaliv_dev_control.patch import PatchApplier, PatchError


def run(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


class Slice2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

        run(self.repo, "git", "init")
        run(self.repo, "git", "config", "user.email", "test@example.com")
        run(self.repo, "git", "config", "user.name", "Test")

        (self.repo / "devcontrol/tests").mkdir(parents=True)
        (self.repo / "devcontrol/target.txt").write_text(
            "old\n",
            encoding="utf-8",
        )
        (self.repo / "devcontrol/tests/test_dummy.py").write_text(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self): self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (self.repo / ".github").mkdir()
        (self.repo / ".github/workflow.yml").write_text(
            "protected\n",
            encoding="utf-8",
        )

        run(self.repo, "git", "add", ".")
        run(self.repo, "git", "commit", "-m", "base")
        self.sha = run(self.repo, "git", "rev-parse", "HEAD")
        self.task = DevelopmentTask(
            task_id="SD-002",
            repository="Ternedal/ModelRig",
            base_sha=self.sha,
            goal="Change target.",
            acceptance_criteria=("Target changes.",),
            risk=Risk.LOW,
            allowed_paths=("devcontrol/**",),
            protected_paths=(".github/**",),
            allowed_command_ids=("python.unittest",),
            required_tests=(
                "python -m unittest discover -s devcontrol/tests -v",
            ),
            budget=TaskBudget(
                max_changed_files=5,
                max_added_lines=100,
                max_deleted_lines=100,
                max_attempts=3,
                max_runtime_seconds=300,
                max_output_bytes=1_000_000,
            ),
            merge_authority=MergeAuthority.HUMAN,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _task_for(self, command_id: str) -> DevelopmentTask:
        return DevelopmentTask(
            task_id=self.task.task_id,
            repository=self.task.repository,
            base_sha=self.task.base_sha,
            goal=self.task.goal,
            acceptance_criteria=self.task.acceptance_criteria,
            risk=self.task.risk,
            allowed_paths=self.task.allowed_paths,
            protected_paths=self.task.protected_paths,
            allowed_command_ids=(command_id,),
            required_tests=self.task.required_tests,
            budget=self.task.budget,
            merge_authority=self.task.merge_authority,
        )

    def test_read_and_literal_search_are_bounded_by_scope(self) -> None:
        files = WorkspaceFiles(self.task, self.repo)
        self.assertEqual(
            files.read_text("devcontrol/target.txt"),
            "old\n",
        )
        matches = files.search_text("old")
        self.assertEqual(
            [(match.path, match.line_number) for match in matches],
            [("devcontrol/target.txt", 1)],
        )
        with self.assertRaises(FileAccessError):
            files.read_text(".github/workflow.yml")

    def test_patch_is_scope_checked_applied_and_staged(self) -> None:
        patch = """diff --git a/devcontrol/target.txt b/devcontrol/target.txt
--- a/devcontrol/target.txt
+++ b/devcontrol/target.txt
@@ -1 +1 @@
-old
+new
"""
        receipt = PatchApplier().apply(self.task, self.repo, patch)
        self.assertTrue(receipt.applied)
        self.assertTrue(receipt.scope.passed)
        self.assertEqual(
            (self.repo / "devcontrol/target.txt").read_text(encoding="utf-8"),
            "new\n",
        )
        self.assertEqual(
            run(self.repo, "git", "diff", "--cached", "--name-only"),
            "devcontrol/target.txt",
        )

    def test_protected_patch_is_rejected_without_mutation(self) -> None:
        patch = """diff --git a/.github/workflow.yml b/.github/workflow.yml
--- a/.github/workflow.yml
+++ b/.github/workflow.yml
@@ -1 +1 @@
-protected
+weakened
"""
        with self.assertRaises(PatchError):
            PatchApplier().apply(self.task, self.repo, patch)
        self.assertEqual(
            (self.repo / ".github/workflow.yml").read_text(encoding="utf-8"),
            "protected\n",
        )
        self.assertEqual(run(self.repo, "git", "status", "--porcelain"), "")

    def test_rename_and_binary_patch_are_rejected(self) -> None:
        with self.assertRaises(PatchError):
            PatchApplier().parse(
                self.task,
                "diff --git a/devcontrol/a b/devcontrol/b\n"
                "rename from devcontrol/a\n"
                "rename to devcontrol/b\n",
            )
        with self.assertRaises(PatchError):
            PatchApplier().parse(
                self.task,
                "diff --git a/devcontrol/a b/devcontrol/a\n"
                "GIT binary patch\n",
            )

    def test_git_metadata_is_protected_even_with_broad_scope(self) -> None:
        broad = DevelopmentTask(
            task_id=self.task.task_id,
            repository=self.task.repository,
            base_sha=self.task.base_sha,
            goal=self.task.goal,
            acceptance_criteria=self.task.acceptance_criteria,
            risk=self.task.risk,
            allowed_paths=("**",),
            protected_paths=(),
            allowed_command_ids=self.task.allowed_command_ids,
            required_tests=self.task.required_tests,
            budget=self.task.budget,
            merge_authority=self.task.merge_authority,
        )
        with self.assertRaises(FileAccessError):
            WorkspaceFiles(broad, self.repo).read_text(".git/config")
        patch = """diff --git a/.git/config b/.git/config
--- a/.git/config
+++ b/.git/config
@@ -1 +1 @@
-old
+new
"""
        with self.assertRaises(PatchError):
            PatchApplier().parse(broad, patch)

    def test_patch_counts_content_that_looks_like_header(self) -> None:
        patch = """diff --git a/devcontrol/target.txt b/devcontrol/target.txt
--- a/devcontrol/target.txt
+++ b/devcontrol/target.txt
@@ -1 +1 @@
-old
+++ b/not-a-header
"""
        summary = PatchApplier().parse(self.task, patch)
        self.assertEqual(
            (summary.added_lines, summary.deleted_lines),
            (1, 1),
        )

    def test_submodule_or_symlink_file_modes_are_rejected(self) -> None:
        for mode in ("120000", "160000"):
            patch = (
                "diff --git a/devcontrol/new b/devcontrol/new\n"
                f"new file mode {mode}\n"
                "--- /dev/null\n"
                "+++ b/devcontrol/new\n"
                "@@ -0,0 +1 @@\n"
                "+x\n"
            )
            with self.assertRaises(PatchError):
                PatchApplier().parse(self.task, patch)

    def test_command_template_rejects_parent_cwd_and_duplicate_id(self) -> None:
        with self.assertRaises(CommandPolicyError):
            CommandTemplate(
                command_id="python.bad",
                argv=(sys.executable, "-V"),
                cwd="../outside",
            )
        template = CommandTemplate(
            command_id="python.same",
            argv=(sys.executable, "-V"),
        )
        with self.assertRaises(CommandPolicyError):
            CommandRegistry((template, template))

    def test_registered_command_passes_and_keeps_workspace_unchanged(self) -> None:
        template = CommandTemplate(
            command_id="python.unittest",
            argv=(
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "devcontrol/tests",
                "-p",
                "test_dummy.py",
                "-v",
            ),
        )
        receipt = CommandExecutor(
            registry=CommandRegistry((template,))
        ).execute(
            self.task,
            self.repo,
            "python.unittest",
        )
        self.assertTrue(receipt.passed)
        self.assertTrue(receipt.workspace_unchanged)
        self.assertFalse(receipt.workspace_reset)

    def test_command_sandbox_hides_source_and_rejects_metadata_mutation(self) -> None:
        config = self.repo / ".git" / "config"
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        outside_marker = self.root / "outside-marker.txt"
        config_before = config.read_bytes()
        command_id = "python.sandbox-metadata"
        child_script = (
            "import os; from pathlib import Path; "
            "Path(os.environ['OUTSIDE_MARKER']).write_text('escaped')"
        )
        script = (
            "import os, subprocess, sys; from pathlib import Path; "
            "root=Path(os.environ['HOME']).parent; "
            "assert 'GITHUB_WORKSPACE' not in os.environ; "
            "assert not (root/'original-dot-git').exists(); "
            "assert not (root/'source.bundle').exists(); "
            "assert not Path('.git/objects/info/alternates').exists(); "
            "assert subprocess.run(['git','remote'], check=True, "
            "text=True, capture_output=True).stdout.strip()==''; "
            "assert 'source.bundle' not in Path('.git/config').read_text(); "
            f"child=subprocess.run([sys.executable,'-c',{child_script!r}],"
            "text=True,capture_output=True); "
            "assert child.returncode!=0; "
            "assert not Path(os.environ['OUTSIDE_MARKER']).exists(); "
            "subprocess.run(['git','remote','add','injected',"
            "'https://example.invalid/repo.git'], check=True); "
            "h=Path('.git/hooks/pre-commit'); "
            "h.write_text('#!/bin/sh\\nexit 1\\n'); h.chmod(0o755)"
        )
        template = CommandTemplate(
            command_id=command_id,
            argv=(sys.executable, "-c", script),
            env={"OUTSIDE_MARKER": str(outside_marker)},
        )
        receipt = CommandExecutor(
            registry=CommandRegistry((template,))
        ).execute(self._task_for(command_id), self.repo, command_id)
        self.assertEqual(receipt.returncode, 0)
        self.assertFalse(receipt.passed)
        self.assertFalse(receipt.workspace_unchanged)
        self.assertTrue(receipt.workspace_reset)
        self.assertFalse(outside_marker.exists())
        self.assertEqual(config.read_bytes(), config_before)
        self.assertFalse(hook.exists())
        self.assertEqual(run(self.repo, "git", "remote"), "")
        self.assertEqual(run(self.repo, "git", "status", "--porcelain"), "")

    def test_command_rejects_literal_source_workspace_argument(self) -> None:
        command_id = "python.source-path"
        template = CommandTemplate(
            command_id=command_id,
            argv=(sys.executable, "-c", "pass", str(self.repo)),
        )
        with self.assertRaisesRegex(CommandPolicyError, "source workspace"):
            CommandExecutor(
                registry=CommandRegistry((template,))
            ).execute(self._task_for(command_id), self.repo, command_id)

    def test_unregistered_or_undeclared_command_fails_closed(self) -> None:
        with self.assertRaises(CommandPolicyError):
            CommandExecutor().execute(
                self.task,
                self.repo,
                "python.compileall",
            )

    def test_mutating_command_resets_workspace_to_exact_base(self) -> None:
        template = CommandTemplate(
            command_id="python.mutator",
            argv=(
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "Path('devcontrol/target.txt').write_text('bad\\n')",
            ),
        )
        receipt = CommandExecutor(
            registry=CommandRegistry((template,))
        ).execute(
            self._task_for("python.mutator"),
            self.repo,
            "python.mutator",
        )
        self.assertFalse(receipt.passed)
        self.assertTrue(receipt.workspace_reset)
        self.assertEqual(
            (self.repo / "devcontrol/target.txt").read_text(encoding="utf-8"),
            "old\n",
        )
        self.assertEqual(run(self.repo, "git", "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
