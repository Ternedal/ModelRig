#!/usr/bin/env python3
"""A4-21 adversarial contracts for the production Agent 4 read context."""

from __future__ import annotations

import ast
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.composition import Agent4RuntimeContext, compose_agent4_runtime  # noqa: E402
from app.agent4.domain import CampaignValidationError  # noqa: E402
from app.agent4.operator_read_context import Agent4OperatorReadContext  # noqa: E402
from app.agent4.production_bootstrap import (  # noqa: E402
    ReadOnlyAgent4HandoffExecutor,
    compose_agent4_operator_context_from_environment,
)


def _snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    if not root.exists():
        return ()
    values: list[tuple[str, str]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        values.append(
            (
                path.relative_to(root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return tuple(values)


class Agent4ProductionReadMutationBoundaryTests(unittest.TestCase):
    def _context(self, root: Path) -> Agent4OperatorReadContext:
        with patch.dict(
            os.environ,
            {
                "KALIV_AGENT4_OPERATOR_API": "1",
                "KALIV_AGENT4_DATA_ROOT": str(root),
            },
            clear=False,
        ):
            context = compose_agent4_operator_context_from_environment()
        self.assertIsInstance(context, Agent4OperatorReadContext)
        assert isinstance(context, Agent4OperatorReadContext)
        return context

    def test_production_context_is_narrow_and_exposes_no_mutation_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = self._context(Path(directory) / "agent4")

            self.assertNotIsInstance(context, Agent4RuntimeContext)
            for forbidden in (
                "repository",
                "checkpoint_store",
                "evidence_recorder",
                "event_recorder",
                "reconciliation",
                "projections",
                "delivery_cursor_store",
                "queue",
                "resources",
                "checkpoints",
                "retry_planner",
                "failures",
                "health_fail_closed",
                "delivery_flights",
                "delivery",
                "guarded_delivery",
                "batches",
            ):
                self.assertFalse(
                    hasattr(context, forbidden),
                    f"production read context unexpectedly exposes {forbidden}",
                )
            self.assertEqual(context.scheduler.queued_count, 0)

    def test_every_scheduler_mutation_fails_before_filesystem_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4"
            root.mkdir()
            sentinel = root / "preexisting.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            context = self._context(root)
            before = _snapshot(root)

            mutations = (
                lambda: context.scheduler.recover(),
                lambda: context.scheduler.submit(object()),
                lambda: context.scheduler.dispatch_ready(),
                lambda: context.scheduler.request_pause("campaign-1"),
                lambda: context.scheduler.mark_paused("campaign-1"),
                lambda: context.scheduler.resume("campaign-1"),
                lambda: context.scheduler.request_cancel("campaign-1"),
                lambda: context.scheduler.mark_cancelled("campaign-1"),
                lambda: context.scheduler.complete(
                    "campaign-1",
                    succeeded=True,
                ),
            )
            for mutate in mutations:
                with self.assertRaisesRegex(
                    CampaignValidationError,
                    "read-only production context forbids",
                ):
                    mutate()
                self.assertEqual(_snapshot(root), before)

    def test_store_and_context_mutation_helpers_fail_before_filesystem_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4"
            context = self._context(root)
            self.assertFalse(root.exists())

            mutations = (
                lambda: context.timeline.append(object()),
                lambda: context.evidence_records.append(object()),
                lambda: context.recover(),
                lambda: context.reconcile_projections(),
            )
            for mutate in mutations:
                with self.assertRaisesRegex(
                    CampaignValidationError,
                    "read-only production context forbids",
                ):
                    mutate()
                self.assertFalse(root.exists())

    def test_read_context_and_full_runtime_share_single_root_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4"
            context = self._context(root)
            self.assertIsNotNone(context)

            with self.assertRaisesRegex(
                CampaignValidationError,
                "already owns this canonical dataroot",
            ):
                compose_agent4_runtime(
                    root,
                    executor=ReadOnlyAgent4HandoffExecutor(),
                    resource_capacities={"test": 1},
                    resource_resolver=lambda _spec: {"test": 1},
                )
            self.assertFalse(root.exists())

    def test_bootstrap_source_has_no_full_runtime_or_resource_admission_workaround(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "production_bootstrap.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertNotIn("compose_agent4_runtime", source)
        self.assertNotIn("resource_capacities", source)
        self.assertNotIn("resource_resolver", source)
        self.assertNotIn("operator-read", source)
        self.assertNotIn("ReadOnlyAgent4HandoffExecutor", called_names)
        self.assertIn("compose_agent4_operator_read_context", called_names)

    def test_narrow_context_module_constructs_no_scheduler_or_resource_manager(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "operator_read_context.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        for forbidden in (
            "ResourceAwareCampaignHandoffSchedulerService",
            "CampaignQueue",
            "InMemoryResourceLeaseManager",
            "CampaignCheckpointService",
            "CampaignFailureHandlingService",
        ):
            self.assertNotIn(forbidden, called_names)


if __name__ == "__main__":
    unittest.main()
