from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaliv_dev_control.commands import (
    CommandExecutionError,
    CommandExecutor,
    CommandPolicyError,
    CommandRegistry,
    CommandTemplate,
    default_registry,
)
from kaliv_dev_control.contract import ContractError, DevelopmentTask
from kaliv_dev_control.evidence import build_scope_receipt
from kaliv_dev_control.patch import PatchApplier, PatchError
from kaliv_dev_control.policy import PathPolicy, ScopeViolation
from kaliv_dev_control.workspace import (
    SubprocessRunner,
    WorkspaceError,
    WorkspaceManager,
)


BASE = {
    "schema": "kaliv-development-task/v1",
    "task_id": "SD-001",
    "repository": "Ternedal/ModelRig",
    "base_sha": "a" * 40,
    "goal": "Add a bounded policy primitive.",
    "acceptance_criteria": ["Policy rejects protected paths."],
    "risk": "low",
    "allowed_paths": ["devcontrol/**"],
    "protected_paths": [".github/**", "scripts/activation_readiness.py"],
    "allowed_command_ids": ["python.unittest"],
    "required_tests": ["python -m unittest discover -s devcontrol/tests -v"],
    "budget": {
        "max_changed_files": 10,
        "max_added_lines": 800,
        "max_deleted_lines": 100,
        "max_attempts": 3,
        "max_runtime_seconds": 900,
        "max_output_bytes": 1000000,
    },
    "merge_authority": "human",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _task_at(base_sha: str, *command_ids: str) -> DevelopmentTask:
    data = dict(BASE)
    data["base_sha"] = base_sha
    data["allowed_command_ids"] = list(command_ids) or ["python.unittest"]
    return DevelopmentTask.from_mapping(data)


class FakeWorkspaceGitRunner:
    def __init__(self, *, head: str, dirty: bool = False) -> None:
        self.head = head
        self.dirty = dirty
        self.calls: list[tuple[str, ...]] = []

    def run(self, args, *, cwd, timeout_seconds, maximum) -> bytes:
        del cwd, timeout_seconds, maximum
        call = tuple(args)
        self.calls.append(call)
        if call[:3] == ("worktree", "add", "--detach"):
            Path(call[-2]).mkdir(parents=True)
            return b"prepared\n"
        if call == ("rev-parse", "HEAD"):
            return (self.head + "\n").encode("ascii")
        if call == ("status", "--porcelain=v1"):
            return b"M file\n" if self.dirty else b""
        if call[:2] == ("worktree", "remove"):
            Path(call[-1]).rmdir()
            return b""
        raise RuntimeError("unsupported fake Git operation")


class RecordingRunner:
    def __init__(self) -> None:
        self.delegate = SubprocessRunner()
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args,
        *,
        cwd,
        timeout_seconds,
        max_output_bytes,
        env=None,
    ):
        self.calls.append(tuple(args))
        return self.delegate.run(
            args,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env=env,
        )


class FoundationTests(unittest.TestCase):
    def test_valid_contract_roundtrips_canonically(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        self.assertEqual(task.task_id, "SD-001")
        self.assertEqual(json.loads(task.canonical_json()), BASE)

    def test_unknown_field_fails_closed(self) -> None:
        with self.assertRaisesRegex(ContractError, "unknown"):
            DevelopmentTask.from_mapping(dict(BASE, auto_merge=True))

    def test_merge_authority_cannot_be_delegated(self) -> None:
        with self.assertRaisesRegex(ContractError, "human"):
            DevelopmentTask.from_mapping(dict(BASE, merge_authority="agent"))

    def test_noncanonical_path_is_rejected(self) -> None:
        for value in (
            "../main/**",
            "./worker/**",
            "devcontrol//x",
            "devcontrol/./x",
            "devcontrol/",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ContractError, "non-canonical"):
                    DevelopmentTask.from_mapping(
                        dict(BASE, allowed_paths=[value])
                    )

    def test_boolean_budget_is_rejected(self) -> None:
        value = dict(BASE)
        value["budget"] = dict(BASE["budget"], max_attempts=True)
        with self.assertRaisesRegex(ContractError, "integer"):
            DevelopmentTask.from_mapping(value)

    def test_allowed_change_passes(self) -> None:
        decision = PathPolicy(DevelopmentTask.from_mapping(BASE)).evaluate(
            ["devcontrol/src/kaliv_dev_control/policy.py"],
            added_lines=20,
            deleted_lines=2,
        )
        self.assertTrue(decision.passed)

    def test_protected_path_wins_over_broad_allowlist(self) -> None:
        task = DevelopmentTask.from_mapping(dict(BASE, allowed_paths=["**"]))
        decision = PathPolicy(task).evaluate(
            [".github/workflows/ci.yml"], added_lines=1, deleted_lines=0
        )
        self.assertIn(ScopeViolation.PROTECTED_PATH, decision.violations)

    def test_outside_scope_fails(self) -> None:
        decision = PathPolicy(DevelopmentTask.from_mapping(BASE)).evaluate(
            ["worker/app/agent3/api.py"], added_lines=1, deleted_lines=0
        )
        self.assertIn(ScopeViolation.OUTSIDE_ALLOWED_PATHS, decision.violations)

    def test_line_and_file_budgets_fail(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        decision = PathPolicy(task).evaluate(
            [f"devcontrol/f{i}.py" for i in range(11)],
            added_lines=801,
            deleted_lines=101,
        )
        self.assertEqual(
            set(decision.violations),
            {
                ScopeViolation.CHANGED_FILE_BUDGET,
                ScopeViolation.ADDED_LINE_BUDGET,
                ScopeViolation.DELETED_LINE_BUDGET,
            },
        )

    def test_receipt_is_deterministic(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        decision = PathPolicy(task).evaluate(
            ["devcontrol/README.md"], added_lines=5, deleted_lines=0
        )
        first = build_scope_receipt(task, decision, added_lines=5, deleted_lines=0)
        second = build_scope_receipt(task, decision, added_lines=5, deleted_lines=0)
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(len(first.task_sha256), 64)

    def test_default_registry_is_empty(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        with self.assertRaisesRegex(CommandPolicyError, "not registered"):
            default_registry().resolve(task, "python.unittest")

    def test_command_template_freezes_mutable_argv(self) -> None:
        source_argv = [sys.executable, "-c", "pass"]
        template = CommandTemplate(
            command_id="python.fixed",
            argv=source_argv,  # type: ignore[arg-type]
        )
        source_argv[1] = "-V"
        source_argv.append("mutated")
        self.assertIsInstance(template.argv, tuple)
        self.assertEqual(template.argv, (sys.executable, "-c", "pass"))

    def test_command_template_rejects_noncanonical_cwd(self) -> None:
        for cwd in (
            "./devcontrol",
            "devcontrol//tests",
            "devcontrol/.",
            "devcontrol/",
            "devcontrol/../worker",
        ):
            with self.subTest(cwd=cwd):
                with self.assertRaisesRegex(CommandPolicyError, "canonical"):
                    CommandTemplate(
                        command_id="python.fixed",
                        argv=(sys.executable, "-c", "pass"),
                        cwd=cwd,
                    )

    def test_workspace_requires_injected_git_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(WorkspaceError, "workspace Git runner"):
                WorkspaceManager(Path(tmp), git_runner=object())

    def test_workspace_verifies_exact_head_and_clean_state(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / ".git").mkdir()
            runner = FakeWorkspaceGitRunner(head=task.base_sha)
            manager = WorkspaceManager(root / "workspaces", git_runner=runner)
            target = manager.create(task, source_repo=source)
            self.assertEqual(target.name, task.task_id)
            self.assertEqual(runner.calls[0][:3], ("worktree", "add", "--detach"))
            self.assertTrue(all(call[0] != "git" for call in runner.calls))
            self.assertFalse(
                any(
                    call[0] in {"fetch", "pull", "push", "remote", "clone"}
                    for call in runner.calls
                )
            )

    def test_wrong_workspace_head_is_removed_and_rejected(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / ".git").mkdir()
            manager = WorkspaceManager(
                root / "workspaces",
                git_runner=FakeWorkspaceGitRunner(head="b" * 40),
            )
            with self.assertRaisesRegex(WorkspaceError, "HEAD"):
                manager.create(task, source_repo=source)
            self.assertFalse((root / "workspaces" / task.task_id).exists())

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "DC-L01 command containment is Linux-only",
    )
    def test_command_executor_rejects_wrong_workspace_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test")
            (repo / "devcontrol").mkdir()
            target = repo / "devcontrol" / "tracked.txt"
            target.write_text("base\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")
            target.write_text("other\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "other")
            command_id = "python.noop"
            template = CommandTemplate(
                command_id=command_id,
                argv=(sys.executable, "-c", "pass"),
            )
            with self.assertRaisesRegex(CommandExecutionError, "HEAD"):
                CommandExecutor(
                    registry=CommandRegistry((template,))
                ).execute(_task_at(base_sha, command_id), repo, command_id)
            self.assertEqual(
                _git(repo, "rev-parse", "HEAD"),
                _git(repo, "rev-parse", "HEAD"),
            )

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "DC-L01 command containment is Linux-only",
    )
    def test_command_executor_rejects_pre_staged_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test")
            (repo / "devcontrol").mkdir()
            target = repo / "devcontrol" / "tracked.txt"
            target.write_text("base\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")
            target.write_text("staged\n", encoding="utf-8")
            _git(repo, "add", "devcontrol/tracked.txt")
            marker = repo / "command-ran.txt"
            command_id = "python.marker"
            template = CommandTemplate(
                command_id=command_id,
                argv=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "Path('command-ran.txt').write_text('ran')",
                ),
            )
            with self.assertRaisesRegex(CommandExecutionError, "staged"):
                CommandExecutor(
                    registry=CommandRegistry((template,))
                ).execute(_task_at(base_sha, command_id), repo, command_id)
            self.assertFalse(marker.exists())
            self.assertIn(
                "devcontrol/tracked.txt",
                _git(repo, "diff", "--cached", "--name-only"),
            )

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "DC-L01 command containment is Linux-only",
    )
    def test_ignored_artifact_is_detected_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test")
            (repo / ".gitignore").write_text("ignored.tmp\n", encoding="utf-8")
            (repo / "devcontrol").mkdir()
            (repo / "devcontrol" / "tracked.txt").write_text("ok\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")
            command_id = "python.ignored-mutator"
            task = _task_at(base_sha, command_id)
            template = CommandTemplate(
                command_id=command_id,
                argv=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('ignored.tmp').write_text('x')",
                ),
            )
            receipt = CommandExecutor(
                registry=CommandRegistry((template,))
            ).execute(task, repo, command_id)
            self.assertFalse(receipt.passed)
            self.assertFalse(receipt.workspace_unchanged)
            self.assertTrue(receipt.workspace_reset)
            self.assertFalse((repo / "ignored.tmp").exists())
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "DC-L01 patch containment is Linux-only",
    )
    def test_patch_rejects_wrong_workspace_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test")
            (repo / "devcontrol").mkdir()
            target = repo / "devcontrol" / "target.txt"
            target.write_text("old\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")
            target.write_text("other\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "other")
            patch = """diff --git a/devcontrol/target.txt b/devcontrol/target.txt
--- a/devcontrol/target.txt
+++ b/devcontrol/target.txt
@@ -1 +1 @@
-other
+new
"""
            with self.assertRaisesRegex(PatchError, "HEAD"):
                PatchApplier().apply(_task_at(base_sha), repo, patch)
            self.assertEqual(target.read_text(encoding="utf-8"), "other\n")

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "DC-L01 patch containment is Linux-only",
    )
    def test_patch_rejects_pre_staged_workspace_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test")
            (repo / "devcontrol").mkdir()
            target = repo / "devcontrol" / "target.txt"
            target.write_text("old\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")
            target.write_text("pre\n", encoding="utf-8")
            _git(repo, "add", "devcontrol/target.txt")
            patch = """diff --git a/devcontrol/target.txt b/devcontrol/target.txt
--- a/devcontrol/target.txt
+++ b/devcontrol/target.txt
@@ -1 +1 @@
-pre
+new
"""
            runner = RecordingRunner()
            with self.assertRaisesRegex(PatchError, "staged"):
                PatchApplier(runner=runner).apply(
                    _task_at(base_sha),
                    repo,
                    patch,
                )
            self.assertFalse(
                any(call[:2] == ("git", "apply") for call in runner.calls)
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "DC-L01 patch containment is Linux-only",
    )
    def test_patch_rejects_and_removes_ignored_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test")
            (repo / ".gitignore").write_text("ignored.tmp\n", encoding="utf-8")
            (repo / "devcontrol").mkdir()
            target = repo / "devcontrol" / "target.txt"
            target.write_text("old\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")
            ignored = repo / "ignored.tmp"
            ignored.write_text("hidden\n", encoding="utf-8")
            patch = """diff --git a/devcontrol/target.txt b/devcontrol/target.txt
--- a/devcontrol/target.txt
+++ b/devcontrol/target.txt
@@ -1 +1 @@
-old
+new
"""
            with self.assertRaisesRegex(PatchError, "ignored"):
                PatchApplier().apply(_task_at(base_sha), repo, patch)
            self.assertFalse(ignored.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(_git(repo, "status", "--porcelain"), "")

    def test_foundation_tracks_landed_and_future_slice_imports(self) -> None:
        source = Path(__file__).resolve().parents[1] / "src" / "kaliv_dev_control"
        landed = {
            "runtime_staging.py",
            "streaming_publication.py",
            "runtime_closure.py",
            "runtime_closure_model.py",
            "runtime_closure_verify.py",
            "runtime_closure_staging.py",
            "tier_a_authority.py",
            "tier_a_plan.py",
            "tier_a_result.py",
            "_tier_a_legacy_runner.py",
            "tier_a_execution.py",
            "tier_a_execution_v3.py",
            "tier_a_command_receipt.py",
            "trusted_git_runtime.py",
            "trusted_git_runtime_h4.py",
            "trusted_git_runtime_model.py",
            "trusted_git_runtime_runner.py",
            "trusted_git_runtime_staging.py",
            "asymmetric_authority.py",
            "_semantic_review_core.py",
            "semantic_review.py",
            "draft_pr_readiness.py",
            "publisher_dry_run.py",
            "publisher_authorization.py",
            "publisher_authorization_chain_v2.py",
            "publisher_authorization_v2.py",
            "publisher_keyring_state.py",
            "publisher_recovery_authorization.py",
            "publisher_recovery_authorization_strict.py",
            "publisher_recovery_primary.py",
            "publisher_recovery_receipt_finalizer.py",
            "publisher_recovery_receipt_v3.py",
            "publisher_replay_h4.py",
        }
        self.assertTrue(landed <= {path.name for path in source.glob("*.py")})

        future = (
            "local_candidate_materialization",
            "local_candidate_materialization_h5c",
        )
        for path in source.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in future:
                self.assertNotIn(
                    f"from .{name}", text, f"future import in {path.name}"
                )
                self.assertNotIn(
                    f"import .{name}", text, f"future import in {path.name}"
                )
            self.assertNotIn(
                "from app.windows_job", text, f"product import in {path.name}"
            )

    def test_dc_l12_authority_remains_offline_and_non_root(self) -> None:
        import kaliv_dev_control

        public = importlib.import_module(
            "kaliv_dev_control.publisher_authorization"
        )
        keyring = importlib.import_module(
            "kaliv_dev_control.publisher_keyring_state"
        )
        self.assertTrue(callable(public.PublisherAuthorizationVerifierV2))
        self.assertTrue(callable(keyring.RollbackSafeEd25519AuthorityVerifier))
        for name in (
            "PublisherAuthorizationVerifierV2",
            "PublisherReplayLedgerV2",
            "RollbackSafeEd25519AuthorityVerifier",
        ):
            self.assertFalse(hasattr(kaliv_dev_control, name), name)
        self.assertIsNone(
            importlib.util.find_spec(
                "kaliv_dev_control.local_candidate_materialization"
            )
        )



if __name__ == "__main__":
    unittest.main()
