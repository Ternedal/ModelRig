#!/usr/bin/env python3
"""A4-25 guard contracts for future concurrent Agent 4 writer + read activation."""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.composition import Agent4RuntimeContext  # noqa: E402
from app.agent4.domain import CampaignValidationError  # noqa: E402
from app.agent4.operator_read_context import (  # noqa: E402
    compose_agent4_operator_read_context,
)
from app.agent4.production_mount import mount_agent4_operator  # noqa: E402


class Agent4SnapshotAuthorityGuardTests(unittest.TestCase):
    def test_production_mount_accepts_only_narrow_read_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = compose_agent4_operator_read_context(Path(directory))
            app = FastAPI()
            with patch.dict(
                os.environ,
                {"KALIV_AGENT4_OPERATOR_API": "1"},
                clear=False,
            ):
                self.assertTrue(mount_agent4_operator(app, context))

            self.assertTrue(app.state.agent4_operator_mounted)
            self.assertIs(app.state.agent4_runtime_context, context)

    def test_full_writer_runtime_is_rejected_before_attribute_access(self) -> None:
        # An uninitialized instance is deliberate: the production guard must
        # reject by authority type before touching any writer-runtime service.
        writer_context = object.__new__(Agent4RuntimeContext)
        app = FastAPI()
        with patch.dict(
            os.environ,
            {"KALIV_AGENT4_OPERATOR_API": "1"},
            clear=False,
        ):
            with self.assertRaisesRegex(
                CampaignValidationError,
                "requires the narrow read-only context",
            ):
                mount_agent4_operator(app, writer_context)  # type: ignore[arg-type]

        self.assertFalse(getattr(app.state, "agent4_operator_mounted", False))

    def test_mount_source_has_no_full_runtime_authority_escape_hatch(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "production_mount.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertNotIn("Agent4RuntimeContext", imported_names)
        self.assertNotIn("Agent4RuntimeContext", source)
        self.assertIn(
            "if not isinstance(context, Agent4OperatorReadContext):",
            source,
        )

    def test_entrypoint_cannot_bootstrap_full_runtime_for_operator_mount(self) -> None:
        source = (ROOT / "worker" / "app" / "entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "compose_agent4_operator_context_from_environment()",
            source,
        )
        self.assertNotIn("compose_agent4_runtime(", source)

    def test_decision_document_binds_future_activation_to_snapshot_authority(self) -> None:
        document = (
            ROOT / "docs" / "AGENT_4_A4_25_SERVER_SNAPSHOT_AUTHORITY.md"
        ).read_text(encoding="utf-8")
        for required in (
            "server-owned immutable operator snapshot projection",
            "atomic current-pointer replacement is the read commit point",
            "snapshot_id",
            "pending_projections()",
            "newest **256** root snapshots",
            "after **15 minutes**",
            "must not mount `Agent4RuntimeContext`",
            "production_activation=false",
        ):
            self.assertIn(required, document)


if __name__ == "__main__":
    unittest.main()
