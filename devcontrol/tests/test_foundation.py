from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaliv_dev_control.contract import ContractError, DevelopmentTask
from kaliv_dev_control.evidence import build_scope_receipt
from kaliv_dev_control.policy import PathPolicy, ScopeViolation
from kaliv_dev_control.workspace import CommandResult, WorkspaceError, WorkspaceManager


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


class FakeRunner:
    def __init__(self, *, head: str, dirty: bool = False) -> None:
        self.head = head
        self.dirty = dirty
        self.calls: list[tuple[str, ...]] = []

    def run(self, args, *, cwd, timeout_seconds, max_output_bytes, env=None):
        call = tuple(args)
        self.calls.append(call)
        if call[:3] == ("git", "worktree", "add"):
            Path(call[-2]).mkdir(parents=True)
            return CommandResult(call, 0, "prepared", "")
        if call == ("git", "rev-parse", "HEAD"):
            return CommandResult(call, 0, self.head + "\n", "")
        if call == ("git", "status", "--porcelain=v1"):
            return CommandResult(call, 0, "M file\n" if self.dirty else "", "")
        if call[:3] == ("git", "worktree", "remove"):
            Path(call[-1]).rmdir()
            return CommandResult(call, 0, "", "")
        return CommandResult(call, 1, "", "unsupported")


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
        with self.assertRaisesRegex(ContractError, "non-canonical"):
            DevelopmentTask.from_mapping(dict(BASE, allowed_paths=["../main/**"]))

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

    def test_workspace_verifies_exact_head_and_clean_state(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / ".git").mkdir()
            manager = WorkspaceManager(
                root / "workspaces", runner=FakeRunner(head=task.base_sha)
            )
            target = manager.create(task, source_repo=source)
            self.assertEqual(target.name, task.task_id)

    def test_wrong_workspace_head_is_removed_and_rejected(self) -> None:
        task = DevelopmentTask.from_mapping(BASE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / ".git").mkdir()
            manager = WorkspaceManager(
                root / "workspaces", runner=FakeRunner(head="b" * 40)
            )
            with self.assertRaisesRegex(WorkspaceError, "HEAD"):
                manager.create(task, source_repo=source)
            self.assertFalse((root / "workspaces" / task.task_id).exists())


if __name__ == "__main__":
    unittest.main()
