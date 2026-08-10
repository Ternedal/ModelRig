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
from app.agent4.service import CampaignNotFoundError, CampaignSchedulerService  # noqa: E402


def _snapshot(root: Path) -> tuple[tuple[str, str, str], ...]:
    if not root.exists():
        return ()
    values: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            values.append((relative, "directory", ""))
        elif path.is_file():
            values.append(
                (
                    relative,
                    "file",
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        else:
            values.append((relative, "other", ""))
    return tuple(values)


_LIFECYCLE_NAMES = (
    "recover",
    "submit",
    "dispatch_ready",
    "request_pause",
    "mark_paused",
    "resume",
    "request_cancel",
    "mark_cancelled",
    "complete",
)


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
            self.assertNotIsInstance(context.scheduler, CampaignSchedulerService)
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
                "recover",
                "reconcile_projections",
            ):
                self.assertFalse(
                    hasattr(context, forbidden),
                    f"production read context unexpectedly exposes {forbidden}",
                )
            for forbidden in _LIFECYCLE_NAMES:
                self.assertFalse(
                    hasattr(context.scheduler, forbidden),
                    f"campaign reader unexpectedly exposes {forbidden}",
                )

    def test_campaign_reader_has_only_reads_and_does_not_change_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4"
            root.mkdir()
            sentinel = root / "preexisting.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            context = self._context(root)
            before = _snapshot(root)

            self.assertEqual(context.scheduler.list(), ())
            with self.assertRaises(CampaignNotFoundError):
                context.scheduler.get("campaign-1")
            self.assertEqual(_snapshot(root), before)

            for forbidden in _LIFECYCLE_NAMES:
                with self.assertRaises(AttributeError):
                    getattr(context.scheduler, forbidden)
                self.assertEqual(_snapshot(root), before)

    def test_store_mutation_helpers_fail_before_filesystem_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4"
            context = self._context(root)
            self.assertFalse(root.exists())

            for mutate in (
                lambda: context.timeline.append(object()),
                lambda: context.evidence_records.append(object()),
            ):
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

    def test_narrow_context_constructs_no_scheduler_or_resource_manager(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "operator_read_context.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        base_names = {
            base.id
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for base in node.bases
            if isinstance(base, ast.Name)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertNotIn("CampaignSchedulerService", imported_names)
        self.assertNotIn("CampaignSchedulerService", base_names)
        self.assertNotIn("CampaignSchedulerService", called_names)
        for forbidden in (
            "ResourceAwareCampaignHandoffSchedulerService",
            "CampaignQueue",
            "InMemoryResourceLeaseManager",
            "CampaignCheckpointService",
            "CampaignFailureHandlingService",
        ):
            self.assertNotIn(forbidden, imported_names)
            self.assertNotIn(forbidden, base_names)
            self.assertNotIn(forbidden, called_names)


if __name__ == "__main__":
    unittest.main()
