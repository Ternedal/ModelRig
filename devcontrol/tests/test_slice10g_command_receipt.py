from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kaliv_dev_control.contract import DevelopmentTask
from kaliv_dev_control.runtime_closure import (
    HmacRuntimeClosureSigner,
    RuntimeClosureFile,
    RuntimeClosureManifest,
)
from kaliv_dev_control.tier_a_command_receipt import (
    TierACommandReceipt,
    TierACommandReceiptError,
    run_single_verified_tier_a_command_with_receipt,
)
from kaliv_dev_control.tier_a_execution import TierAExecutionError, TierAExecutionTimeout
from kaliv_dev_control.tier_a_result import TierAExecutionResult, TierAOutputStream
from kaliv_dev_control.trusted_git_runtime import (
    TrustedGitRunner,
    TrustedGitRuntimeError,
    TrustedGitRuntimeEvidence,
)

COMMAND_ID = "modelrig.receipt.check"
KEY_ID = "slice-10g-test-key"
SECRET = b"slice-10g-test-secret-0000000001"


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed.stdout.strip()


def git_runtime_evidence() -> TrustedGitRuntimeEvidence:
    return TrustedGitRuntimeEvidence(
        runtime_manifest_sha256="8" * 64,
        runtime_file_count=3,
        runtime_bytes=4096,
        executable_sha256="9" * 64,
        version="git version test-fixture",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core"),
        library_relative_directories=("lib",),
    )


class SystemGitRunner(TrustedGitRunner):
    """Test double with the production runner type and absolute system Git."""

    def __init__(self) -> None:
        executable = shutil.which("git")
        if executable is None:
            raise unittest.SkipTest("Git executable is unavailable")
        self.executable = str(Path(executable).resolve())
        self._evidence = git_runtime_evidence()

    def run(
        self,
        args,
        *,
        cwd,
        stdin=None,
        maximum=64 * 1024 * 1024,
        timeout_seconds=120,
        expected_codes=(0,),
        extra_env=None,
    ):
        completed = subprocess.run(
            [self.executable, *args],
            cwd=cwd,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
        if len(completed.stdout) + len(completed.stderr) > maximum:
            raise TrustedGitRuntimeError("test Git output exceeded its bound")
        if completed.returncode not in expected_codes:
            raise TrustedGitRuntimeError(
                completed.stderr.decode("utf-8", errors="replace")
            )
        return completed.stdout

    def evidence(self) -> TrustedGitRuntimeEvidence:
        return self._evidence


def make_repo(root: Path) -> tuple[Path, str]:
    workspace = root / "workspace"
    workspace.mkdir()
    git(workspace, "init")
    git(workspace, "config", "user.name", "Slice 10G")
    git(workspace, "config", "user.email", "slice10g@example.invalid")
    (workspace / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(workspace, "add", "tracked.txt")
    git(workspace, "commit", "-m", "base")
    return workspace.resolve(), git(workspace, "rev-parse", "HEAD")


def make_task(base_sha: str, *, commands: tuple[str, ...] = (COMMAND_ID,)) -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "A10G_RECEIPT",
            "repository": "Ternedal/ModelRig",
            "base_sha": base_sha,
            "goal": "Join one verified Tier-A result to exact Git evidence.",
            "acceptance_criteria": [
                "The sole reviewed command produces one canonical receipt."
            ],
            "risk": "low",
            "allowed_paths": ["tracked.txt"],
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": list(commands),
            "required_tests": list(commands),
            "budget": {
                "max_changed_files": 10,
                "max_added_lines": 100,
                "max_deleted_lines": 100,
                "max_attempts": 2,
                "max_runtime_seconds": 120,
                "max_output_bytes": 4096,
            },
            "merge_authority": "human",
        }
    )


def make_closure(task: DevelopmentTask):
    entry = RuntimeClosureFile(
        relative_path="helper.exe",
        sha256=hashlib.sha256(b"helper").hexdigest(),
        size_bytes=len(b"helper"),
    )
    manifest = RuntimeClosureManifest(
        task_id=task.task_id,
        task_sha256=hashlib.sha256(
            task.canonical_json().encode("utf-8")
        ).hexdigest(),
        repository=task.repository,
        base_sha=task.base_sha,
        command_id=COMMAND_ID,
        tool_id="receipt-helper",
        catalog_sha256="1" * 64,
        toolchain_sha256="2" * 64,
        lease_sha256="3" * 64,
        workspace_root_sha256="4" * 64,
        trusted_runtime_root_sha256="5" * 64,
        entrypoint_relative_path="helper.exe",
        working_directory=".",
        files=(entry,),
        total_bytes=entry.size_bytes,
    )
    return HmacRuntimeClosureSigner(KEY_ID, SECRET).sign(manifest)


def output(payload: bytes = b"") -> TierAOutputStream:
    return TierAOutputStream(
        captured=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        total_bytes=len(payload),
        truncated=False,
    )


def result(task: DevelopmentTask, *, returncode: int = 0, timed_out: bool = False):
    return TierAExecutionResult.create(
        task_id=task.task_id,
        task_sha256=hashlib.sha256(
            task.canonical_json().encode("utf-8")
        ).hexdigest(),
        base_sha=task.base_sha,
        command_id=COMMAND_ID,
        plan_sha256="6" * 64,
        lease_sha256="3" * 64,
        signed_report_sha256="7" * 64,
        returncode=returncode,
        duration_ms=25,
        timed_out=timed_out,
        max_output_bytes=4096,
        stdout=output(b"ok\n" if not timed_out else b"before timeout\n"),
        stderr=output(),
    )


def run_receipt(task, workspace, signed, *, git_runner=None):
    return run_single_verified_tier_a_command_with_receipt(
        task,
        object(),
        object(),
        object(),
        object(),
        git_runner=git_runner or SystemGitRunner(),
        signed_runtime_closure=signed,
        runtime_closure_verifier=object(),
        trusted_runtime_root=workspace.parent / "trusted",
        workspace_root=workspace,
        control_plane_root=workspace.parent / "control",
    )


class TierACommandReceiptTests(unittest.TestCase):
    def test_preserves_exact_staged_patch_and_cleans_runtime_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, base_sha = make_repo(Path(directory))
            task = make_task(base_sha)
            signed = make_closure(task)
            (workspace / "tracked.txt").write_text("staged\n", encoding="utf-8")
            git(workspace, "add", "tracked.txt")

            def execute(*args, **kwargs):
                self.assertEqual(args[5], COMMAND_ID)
                runtime = (
                    workspace
                    / ".kaliv"
                    / "runtime-closures"
                    / signed.manifest.tool_id
                    / signed.manifest.sha256
                )
                runtime.mkdir(parents=True)
                (runtime / "helper.exe").write_bytes(b"helper")
                return result(task)

            with patch(
                "kaliv_dev_control.tier_a_command_receipt.run_verified_tier_a_command",
                side_effect=execute,
            ) as mocked:
                receipt = run_receipt(task, workspace, signed)

            self.assertEqual(mocked.call_count, 1)
            self.assertTrue(receipt.passed)
            self.assertEqual(receipt.git_runtime.sha256, git_runtime_evidence().sha256)
            self.assertTrue(receipt.workspace_unchanged)
            self.assertFalse(receipt.workspace_reset_performed)
            self.assertGreater(receipt.workspace_before.staged_patch_bytes, 0)
            self.assertEqual(
                receipt.workspace_before.sha256,
                receipt.workspace_after.sha256,
            )
            self.assertFalse((workspace / ".kaliv").exists())
            self.assertIn("M  tracked.txt", git(workspace, "status", "--short"))
            reloaded = TierACommandReceipt.from_mapping(receipt.to_dict())
            self.assertEqual(reloaded.canonical_json(), receipt.canonical_json())
            self.assertEqual(reloaded.sha256, receipt.sha256)

    def test_mutation_is_recorded_then_reset_to_exact_base(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, base_sha = make_repo(Path(directory))
            task = make_task(base_sha)
            signed = make_closure(task)
            (workspace / "tracked.txt").write_text("staged\n", encoding="utf-8")
            git(workspace, "add", "tracked.txt")

            def execute(*args, **kwargs):
                (workspace / "tracked.txt").write_text("mutated\n", encoding="utf-8")
                (workspace / "injected.txt").write_text("injected\n", encoding="utf-8")
                return result(task)

            with patch(
                "kaliv_dev_control.tier_a_command_receipt.run_verified_tier_a_command",
                side_effect=execute,
            ):
                receipt = run_receipt(task, workspace, signed)

            self.assertFalse(receipt.passed)
            self.assertFalse(receipt.workspace_unchanged)
            self.assertTrue(receipt.workspace_reset_performed)
            self.assertIsNotNone(receipt.workspace_reset)
            self.assertEqual(receipt.workspace_reset.head_sha, base_sha)
            self.assertEqual(receipt.workspace_reset.staged_patch_bytes, 0)
            self.assertEqual(receipt.workspace_reset.unstaged_patch_bytes, 0)
            self.assertEqual(receipt.workspace_reset.untracked_path_count, 0)
            self.assertEqual(
                (workspace / "tracked.txt").read_text(encoding="utf-8"),
                "base\n",
            )
            self.assertFalse((workspace / "injected.txt").exists())
            self.assertEqual(git(workspace, "status", "--short"), "")

    def test_timeout_returns_nonpassing_receipt_with_workspace_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, base_sha = make_repo(Path(directory))
            task = make_task(base_sha)
            signed = make_closure(task)
            timed_out = result(task, returncode=1, timed_out=True)

            with patch(
                "kaliv_dev_control.tier_a_command_receipt.run_verified_tier_a_command",
                side_effect=TierAExecutionTimeout(timed_out),
            ):
                receipt = run_receipt(task, workspace, signed)

            self.assertTrue(receipt.tier_a_result.timed_out)
            self.assertFalse(receipt.passed)
            self.assertTrue(receipt.workspace_unchanged)
            self.assertFalse(receipt.workspace_reset_performed)

    def test_rejects_more_than_one_command_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, base_sha = make_repo(Path(directory))
            task = make_task(base_sha, commands=(COMMAND_ID, "modelrig.other.check"))
            signed = make_closure(task)

            with patch(
                "kaliv_dev_control.tier_a_command_receipt.run_verified_tier_a_command"
            ) as mocked:
                with self.assertRaisesRegex(
                    TierACommandReceiptError, "one exact required command"
                ):
                    run_receipt(task, workspace, signed)
            mocked.assert_not_called()

    def test_rejects_unstaged_or_untracked_input(self):
        for name in ("unstaged", "untracked"):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    workspace, base_sha = make_repo(Path(directory))
                    task = make_task(base_sha)
                    signed = make_closure(task)
                    if name == "unstaged":
                        (workspace / "tracked.txt").write_text(
                            "unstaged\n", encoding="utf-8"
                        )
                    else:
                        (workspace / "untracked.txt").write_text(
                            "untracked\n", encoding="utf-8"
                        )

                    with patch(
                        "kaliv_dev_control.tier_a_command_receipt.run_verified_tier_a_command"
                    ) as mocked:
                        with self.assertRaisesRegex(
                            TierACommandReceiptError,
                            "only an optional staged patch",
                        ):
                            run_receipt(task, workspace, signed)
                    mocked.assert_not_called()

    def test_execution_error_still_resets_observed_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, base_sha = make_repo(Path(directory))
            task = make_task(base_sha)
            signed = make_closure(task)
            (workspace / "tracked.txt").write_text("staged\n", encoding="utf-8")
            git(workspace, "add", "tracked.txt")

            def execute(*args, **kwargs):
                (workspace / "tracked.txt").write_text("mutated\n", encoding="utf-8")
                raise TierAExecutionError("failed after launch")

            with patch(
                "kaliv_dev_control.tier_a_command_receipt.run_verified_tier_a_command",
                side_effect=execute,
            ):
                with self.assertRaisesRegex(
                    TierACommandReceiptError,
                    "failed before producing a result",
                ):
                    run_receipt(task, workspace, signed)

            self.assertEqual(
                (workspace / "tracked.txt").read_text(encoding="utf-8"),
                "base\n",
            )
            self.assertEqual(git(workspace, "status", "--short"), "")

    def test_requires_trusted_git_and_detects_runtime_identity_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace, base_sha = make_repo(Path(directory))
            task = make_task(base_sha)
            signed = make_closure(task)
            with self.assertRaisesRegex(TierACommandReceiptError, "trusted Git"):
                run_single_verified_tier_a_command_with_receipt(
                    task,
                    object(),
                    object(),
                    object(),
                    object(),
                    git_runner=object(),
                    signed_runtime_closure=signed,
                    runtime_closure_verifier=object(),
                    trusted_runtime_root=workspace.parent / "trusted",
                    workspace_root=workspace,
                    control_plane_root=workspace.parent / "control",
                )

            runner = SystemGitRunner()
            first = runner.evidence()
            drift = TrustedGitRuntimeEvidence(
                runtime_manifest_sha256="a" * 64,
                runtime_file_count=first.runtime_file_count,
                runtime_bytes=first.runtime_bytes,
                executable_sha256=first.executable_sha256,
                version=first.version,
                exec_path_relative_path=first.exec_path_relative_path,
                path_relative_directories=first.path_relative_directories,
                library_relative_directories=first.library_relative_directories,
            )
            calls = 0

            def changing_evidence():
                nonlocal calls
                calls += 1
                return first if calls == 1 else drift

            runner.evidence = changing_evidence
            with patch(
                "kaliv_dev_control.tier_a_command_receipt.run_verified_tier_a_command",
                return_value=result(task),
            ):
                with self.assertRaisesRegex(
                    TierACommandReceiptError,
                    "identity changed",
                ):
                    run_receipt(task, workspace, signed, git_runner=runner)


if __name__ == "__main__":
    unittest.main()
