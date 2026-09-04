#!/usr/bin/env python3
"""A4-15 production read-only bootstrap contracts."""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.domain import CampaignValidationError  # noqa: E402
from app.agent4.production_bootstrap import (  # noqa: E402
    ReadOnlyAgent4HandoffExecutor,
    compose_agent4_operator_context_from_environment,
)


class Agent4ProductionBootstrapTests(unittest.TestCase):
    def test_flag_off_is_inert_and_requires_no_dataroot(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KALIV_AGENT4_OPERATOR_API", None)
            os.environ.pop("KALIV_AGENT4_DATA_ROOT", None)
            before_threads = {
                (thread.ident, thread.name) for thread in threading.enumerate()
            }
            self.assertIsNone(compose_agent4_operator_context_from_environment())
            after_threads = {
                (thread.ident, thread.name) for thread in threading.enumerate()
            }
        self.assertEqual(before_threads, after_threads)

    def test_exact_opt_in_requires_absolute_dataroot(self) -> None:
        with patch.dict(
            os.environ,
            {"KALIV_AGENT4_OPERATOR_API": "1"},
            clear=False,
        ):
            os.environ.pop("KALIV_AGENT4_DATA_ROOT", None)
            with self.assertRaisesRegex(
                CampaignValidationError,
                "KALIV_AGENT4_DATA_ROOT is required",
            ):
                compose_agent4_operator_context_from_environment()

            os.environ["KALIV_AGENT4_DATA_ROOT"] = "relative-agent4-root"
            with self.assertRaisesRegex(
                CampaignValidationError,
                "must be an absolute filesystem path",
            ):
                compose_agent4_operator_context_from_environment()

    def test_composition_is_side_effect_free_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4-runtime"
            with patch.dict(
                os.environ,
                {
                    "KALIV_AGENT4_OPERATOR_API": "1",
                    "KALIV_AGENT4_DATA_ROOT": str(root),
                },
                clear=False,
            ):
                before_threads = {
                    (thread.ident, thread.name) for thread in threading.enumerate()
                }
                context = compose_agent4_operator_context_from_environment()
                after_threads = {
                    (thread.ident, thread.name) for thread in threading.enumerate()
                }

            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual(context.paths.root, root)
            self.assertFalse(root.exists())
            self.assertEqual(before_threads, after_threads)
            self.assertIs(context.operator.timeline, context.timeline)
            self.assertIs(context.operator.query, context.query)
            self.assertIs(context.evidence_operator.scheduler, context.scheduler)
            self.assertIs(context.evidence_operator.records, context.evidence_records)
            self.assertIs(context.evidence_operator.query, context.evidence_query)

    def test_second_context_for_same_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4-runtime"
            environment = {
                "KALIV_AGENT4_OPERATOR_API": "1",
                "KALIV_AGENT4_DATA_ROOT": str(root),
            }
            with patch.dict(os.environ, environment, clear=False):
                first = compose_agent4_operator_context_from_environment()
                self.assertIsNotNone(first)
                with self.assertRaisesRegex(
                    CampaignValidationError,
                    "already owns this canonical dataroot",
                ):
                    compose_agent4_operator_context_from_environment()

    def test_read_only_executor_rejects_every_handoff_operation(self) -> None:
        executor = ReadOnlyAgent4HandoffExecutor()
        for operation in (
            lambda: executor.dispatch(None),
            lambda: executor.signal(None),
            lambda: executor.query_outcome("dispatch-id"),
        ):
            with self.assertRaisesRegex(
                CampaignValidationError,
                "read-only production context forbids",
            ):
                operation()

    def test_entrypoint_bootstraps_before_mount_without_lifecycle_calls(self) -> None:
        source = (ROOT / "worker" / "app" / "entrypoint.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertEqual(
            calls.count("compose_agent4_operator_context_from_environment"),
            1,
        )
        self.assertEqual(calls.count("mount_agent4_operator"), 1)
        bootstrap_at = source.index(
            "compose_agent4_operator_context_from_environment(),"
        )
        for later_mount in (
            "mount_web_research(fastapi_app)",
            "mount_file_capabilities(fastapi_app)",
        ):
            self.assertLess(bootstrap_at, source.index(later_mount))
        for forbidden in (
            ".recover(",
            ".reconcile_projections(",
            ".dispatch_ready(",
            ".submit(",
            ".signal(",
        ):
            self.assertNotIn(forbidden, source)

    def test_bootstrap_source_contains_no_recovery_or_background_runtime(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "production_bootstrap.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertEqual(
            called_attributes
            & {
                "recover",
                "reconcile_projections",
                "dispatch_ready",
                "submit",
                "signal",
                "start",
            },
            set(),
        )
        for token in ("threading.Thread", "Timer(", "asyncio.create_task"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
