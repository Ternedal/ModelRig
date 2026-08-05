from __future__ import annotations

import hashlib
import inspect
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import kaliv_dev_control.bounded_subprocess as bounded_module
import kaliv_dev_control.workspace as workspace_module
from kaliv_dev_control.bounded_subprocess import (
    BoundedSubprocessError,
    run_bounded_subprocess,
)
from kaliv_dev_control.commands import (
    CommandExecutionError,
    CommandExecutor,
    CommandRegistry,
    CommandTemplate,
)
from kaliv_dev_control.contract import DevelopmentTask
from kaliv_dev_control.patch import PatchApplier, PatchError
from kaliv_dev_control.workspace import SubprocessRunner, WorkspaceError


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_gone(*pids: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(not _alive(pid) for pid in pids):
            return
        time.sleep(0.05)
    raise AssertionError(f"process tree remained alive: {pids}")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _task_at(base_sha: str, *command_ids: str) -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "RESET-001",
            "repository": "Ternedal/ModelRig",
            "base_sha": base_sha,
            "goal": "Prove reset leaves an exact clean workspace.",
            "acceptance_criteria": ["All mutations are physically removed."],
            "risk": "low",
            "allowed_paths": ["devcontrol/**"],
            "protected_paths": [".github/**"],
            "allowed_command_ids": list(command_ids) or ["python.noop"],
            "required_tests": ["python -m unittest discover -s devcontrol/tests -v"],
            "budget": {
                "max_changed_files": 10,
                "max_added_lines": 800,
                "max_deleted_lines": 100,
                "max_attempts": 3,
                "max_runtime_seconds": 900,
                "max_output_bytes": 1_000_000,
            },
            "merge_authority": "human",
        }
    )


@unittest.skipUnless(
    sys.platform.startswith("linux"),
    "DC-L01 containment is Linux-only",
)
class BoundedSubprocessTests(unittest.TestCase):
    def test_success_streams_hashes_counts_and_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = b"x" * 100_000
            result = run_bounded_subprocess(
                (
                    sys.executable,
                    "-c",
                    "import sys; data=sys.stdin.buffer.read(); "
                    "sys.stdout.buffer.write(data); "
                    "sys.stderr.buffer.write(b'err')",
                ),
                cwd=Path(directory).resolve(),
                env=os.environ.copy(),
                stdin_bytes=payload,
                timeout_seconds=10,
                max_output_bytes=200_000,
                stdout_prefix_bytes=120_000,
                stderr_prefix_bytes=100,
            )
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.output_limit_exceeded)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.process_tree_terminated)
        self.assertEqual(result.stdout.prefix, payload)
        self.assertEqual(result.stdout.total_bytes, len(payload))
        self.assertEqual(
            result.stdout.sha256,
            hashlib.sha256(payload).hexdigest(),
        )
        self.assertEqual(result.stderr.prefix, b"err")
        self.assertEqual(result.total_output_bytes, len(payload) + 3)

    def test_output_limit_terminates_parent_and_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child_script = (
                "import os,time,sys; "
                "open(sys.argv[1], 'w').write(str(os.getpid())); "
                "time.sleep(60)"
            )
            parent_script = f"""
import os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / "parent.pid").write_text(str(os.getpid()))
subprocess.Popen([
    sys.executable,
    "-c",
    {child_script!r},
    str(root / "child.pid"),
])
for _ in range(400):
    if (root / "child.pid").exists():
        break
    time.sleep(0.005)
while True:
    sys.stdout.buffer.write(b"z" * 65536)
    sys.stdout.buffer.flush()
"""
            result = run_bounded_subprocess(
                (sys.executable, "-c", parent_script, str(root)),
                cwd=root,
                env=os.environ.copy(),
                timeout_seconds=10,
                max_output_bytes=100_000,
                stdout_prefix_bytes=4096,
                stderr_prefix_bytes=4096,
            )
            parent_pid = int((root / "parent.pid").read_text())
            child_pid = int((root / "child.pid").read_text())
            _wait_gone(parent_pid, child_pid)
        self.assertTrue(result.output_limit_exceeded)
        self.assertFalse(result.timed_out)
        self.assertTrue(result.process_tree_terminated)
        self.assertGreater(result.total_output_bytes, 100_000)
        self.assertLessEqual(result.total_output_bytes, 100_000 + 131_072)
        self.assertEqual(len(result.stdout.prefix), 4096)
        self.assertTrue(result.stdout.truncated)

    def test_timeout_terminates_parent_and_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child_script = (
                "import os,time,sys; "
                "open(sys.argv[1], 'w').write(str(os.getpid())); "
                "time.sleep(60)"
            )
            parent_script = f"""
import os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / "parent.pid").write_text(str(os.getpid()))
subprocess.Popen([
    sys.executable,
    "-c",
    {child_script!r},
    str(root / "child.pid"),
])
for _ in range(400):
    if (root / "child.pid").exists():
        break
    time.sleep(0.005)
time.sleep(60)
"""
            result = run_bounded_subprocess(
                (sys.executable, "-c", parent_script, str(root)),
                cwd=root,
                env=os.environ.copy(),
                timeout_seconds=2,
                max_output_bytes=4096,
            )
            parent_pid = int((root / "parent.pid").read_text())
            child_pid = int((root / "child.pid").read_text())
            _wait_gone(parent_pid, child_pid)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.output_limit_exceeded)
        self.assertTrue(result.process_tree_terminated)

    def test_timeout_terminates_descendant_in_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            child = root / "child.py"
            child.write_text(
                "import os,sys,time\n"
                "from pathlib import Path\n"
                "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            parent = root / "parent.py"
            parent.write_text(
                "import subprocess,sys,time\n"
                "from pathlib import Path\n"
                "root=Path(sys.argv[1])\n"
                "subprocess.Popen([sys.executable, str(root/'child.py'), "
                "str(root/'escaped.pid')], start_new_session=True)\n"
                "for _ in range(400):\n"
                "    if (root/'escaped.pid').exists(): break\n"
                "    time.sleep(0.005)\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            result = run_bounded_subprocess(
                (sys.executable, str(parent), str(root)),
                cwd=root,
                env=os.environ.copy(),
                timeout_seconds=2,
                max_output_bytes=4096,
            )
            escaped_pid = int((root / "escaped.pid").read_text())
            _wait_gone(escaped_pid)
        self.assertTrue(result.timed_out)
        self.assertTrue(result.process_tree_terminated)

    def test_unacknowledged_termination_fails_without_result(self) -> None:
        class FakeProcess:
            pid = 999_999
            stdin = None
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            returncode = 125

            def poll(self):
                return None

            def wait(self, timeout=None):
                del timeout
                return self.returncode

        fake = FakeProcess()
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(bounded_module, "_spawn", return_value=fake),
                mock.patch.object(
                    bounded_module,
                    "_terminate_tree",
                    return_value=False,
                ),
            ):
                with self.assertRaisesRegex(
                    BoundedSubprocessError,
                    "did not acknowledge",
                ):
                    run_bounded_subprocess(
                        (sys.executable, "-c", "pass"),
                        cwd=Path(directory).resolve(),
                        env=os.environ.copy(),
                        timeout_seconds=1,
                        max_output_bytes=4096,
                    )

    def test_workspace_runner_fails_closed_on_live_output_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = SubprocessRunner()
            with self.assertRaisesRegex(WorkspaceError, "output exceeded"):
                runner.run(
                    (
                        sys.executable,
                        "-c",
                        "import sys; "
                        "sys.stdout.buffer.write(b'x' * 1000000); "
                        "sys.stdout.buffer.flush()",
                    ),
                    cwd=Path(directory).resolve(),
                    timeout_seconds=10,
                    max_output_bytes=10_000,
                )


@unittest.skipUnless(
    sys.platform.startswith("linux"),
    "DC-L01 reset regressions require Linux containment",
)
class WorkspaceResetRegressionTests(unittest.TestCase):
    @staticmethod
    def _repo(directory: str) -> tuple[Path, Path, str]:
        repo = Path(directory) / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        (repo / "devcontrol").mkdir()
        target = repo / "devcontrol" / "target.txt"
        target.write_text("base\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "base")
        return repo, target, _git(repo, "rev-parse", "HEAD")

    def test_command_reset_removes_nested_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, _, base_sha = self._repo(directory)
            command_id = "python.nested-repo"
            template = CommandTemplate(
                command_id=command_id,
                argv=(
                    sys.executable,
                    "-c",
                    "import subprocess; "
                    "subprocess.run(['git','init','nested'], check=True)",
                ),
            )
            receipt = CommandExecutor(
                registry=CommandRegistry((template,))
            ).execute(_task_at(base_sha, command_id), repo, command_id)
            self.assertFalse(receipt.passed)
            self.assertTrue(receipt.workspace_reset)
            self.assertFalse((repo / "nested").exists())
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    def test_command_git_metadata_mutation_is_isolated_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, _, base_sha = self._repo(directory)
            config = repo / ".git" / "config"
            hook = repo / ".git" / "hooks" / "pre-commit"
            config_before = config.read_bytes()
            command_id = "python.git-metadata-mutator"
            script = (
                "import subprocess; from pathlib import Path; "
                "subprocess.run(['git','remote','add','injected',"
                "'https://example.invalid/repo.git'], check=True); "
                "hook=Path('.git/hooks/pre-commit'); "
                "hook.write_text('#!/bin/sh\\nexit 1\\n'); "
                "hook.chmod(0o755)"
            )
            template = CommandTemplate(
                command_id=command_id,
                argv=(sys.executable, "-c", script),
            )
            receipt = CommandExecutor(
                registry=CommandRegistry((template,))
            ).execute(_task_at(base_sha, command_id), repo, command_id)
            self.assertFalse(receipt.passed)
            self.assertFalse(receipt.workspace_unchanged)
            self.assertTrue(receipt.workspace_reset)
            self.assertEqual(config.read_bytes(), config_before)
            self.assertFalse(hook.exists())
            self.assertEqual(_git(repo, "remote"), "")
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    def test_patch_reset_removes_nested_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, target, base_sha = self._repo(directory)
            _git(repo, "init", "nested")
            patch = """diff --git a/devcontrol/target.txt b/devcontrol/target.txt
--- a/devcontrol/target.txt
+++ b/devcontrol/target.txt
@@ -1 +1 @@
-base
+changed
"""
            with self.assertRaisesRegex(PatchError, "untracked"):
                PatchApplier().apply(_task_at(base_sha), repo, patch)
            self.assertFalse((repo / "nested").exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "base\n")
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    def test_post_command_snapshot_failure_resets_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, target, base_sha = self._repo(directory)
            command_id = "python.large-mutation"
            template = CommandTemplate(
                command_id=command_id,
                argv=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "Path('devcontrol/target.txt').write_text('x' * 5000000)",
                ),
            )
            with self.assertRaisesRegex(
                CommandExecutionError,
                "post-command workspace verification failed",
            ):
                CommandExecutor(
                    registry=CommandRegistry((template,))
                ).execute(_task_at(base_sha, command_id), repo, command_id)
            self.assertEqual(target.read_text(encoding="utf-8"), "base\n")
            self.assertEqual(_git(repo, "status", "--porcelain"), "")


class BoundedSubprocessSourceTests(unittest.TestCase):
    def test_authority_runners_use_linux_subreaper_without_future_import(self) -> None:
        for module in (bounded_module, workspace_module):
            source = inspect.getsource(module)
            self.assertNotIn("subprocess.run(", source)
            self.assertNotIn("capture_output=True", source)
        source = inspect.getsource(bounded_module)
        self.assertNotIn("app.windows_job", source)
        self.assertIn("_PR_SET_CHILD_SUBREAPER", source)
        self.assertIn("_linux_descendants", source)
        self.assertIn("start_new_session=True", source)
        self.assertIn("did not acknowledge process-tree quiescence", source)
        self.assertIn("Windows containment is deferred to DC-L05", source)


if __name__ == "__main__":
    unittest.main()
