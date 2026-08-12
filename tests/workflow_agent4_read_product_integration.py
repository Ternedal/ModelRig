#!/usr/bin/env python3
"""Cross-layer contracts for the dormant Agent 4 read product path."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Agent4ReadProductIntegrationTests(unittest.TestCase):
    def test_worker_and_android_share_exact_operator_protocol(self) -> None:
        worker_source = (
            ROOT / "worker" / "app" / "agent4" / "operator_api.py"
        ).read_text(encoding="utf-8")
        worker_tree = ast.parse(worker_source)
        worker_constants: dict[str, str] = {}
        for node in worker_tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id not in {"OPERATOR_API_SCHEMA", "OPERATOR_MEDIA_TYPE"}:
                continue
            worker_constants[target.id] = ast.literal_eval(node.value)

        android_source = (
            ROOT
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "dk"
            / "ternedal"
            / "modelrig"
            / "net"
            / "Agent4OperatorClient.kt"
        ).read_text(encoding="utf-8")
        android_schema = re.search(
            r'const val SCHEMA = "([^"]+)"', android_source
        )
        android_media_type = re.search(
            r'const val MEDIA_TYPE = "([^"]+)"', android_source
        )

        self.assertIsNotNone(android_schema)
        self.assertIsNotNone(android_media_type)
        assert android_schema is not None
        assert android_media_type is not None
        self.assertEqual(
            worker_constants["OPERATOR_API_SCHEMA"],
            android_schema.group(1),
        )
        self.assertEqual(
            worker_constants["OPERATOR_MEDIA_TYPE"],
            android_media_type.group(1),
        )

    def test_grant_name_and_denial_contract_are_identical(self) -> None:
        operator_source = (
            ROOT / "backend" / "internal" / "httpapi" / "agent4_operator.go"
        ).read_text(encoding="utf-8")
        grant_source = (
            ROOT / "backend" / "internal" / "store" / "agent4_grants.go"
        ).read_text(encoding="utf-8")
        android_source = (
            ROOT
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "dk"
            / "ternedal"
            / "modelrig"
            / "net"
            / "Agent4OperatorClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn('const agent4ReadGrant = "agent4:read"', operator_source)
        self.assertIn('const agent4ReadGrant = "agent4:read"', grant_source)
        self.assertIn('detail == "agent4 read grant required"', android_source)
        self.assertIn("agent4:read", android_source)

    def test_all_activation_surfaces_are_exact_and_default_off(self) -> None:
        entrypoint = (ROOT / "worker" / "app" / "entrypoint.py").read_text(
            encoding="utf-8"
        )
        bootstrap = (
            ROOT / "worker" / "app" / "agent4" / "production_bootstrap.py"
        ).read_text(encoding="utf-8")
        backend_routes = (
            ROOT / "backend" / "internal" / "httpapi" / "server.go"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'os.getenv("KALIV_AGENT4_OPERATOR_API", "0") == "1"',
            entrypoint,
        )
        self.assertIn(
            '_AGENT4_OPERATOR_FLAG = "KALIV_AGENT4_OPERATOR_API"',
            bootstrap,
        )
        self.assertIn(
            '_AGENT4_DATA_ROOT = "KALIV_AGENT4_DATA_ROOT"',
            bootstrap,
        )
        self.assertIn(
            'const agent4GrantAdminFlag = "KALIV_AGENT4_GRANT_ADMIN"',
            (
                ROOT
                / "backend"
                / "internal"
                / "httpapi"
                / "agent4_grants_admin.go"
            ).read_text(encoding="utf-8"),
        )
        self.assertIn(
            'os.Getenv(agent4GrantAdminFlag) == "1"',
            backend_routes,
        )
        self.assertIn(
            'os.Getenv("KALIV_AGENT4_OPERATOR_API") == "1"',
            backend_routes,
        )

    def test_android_surface_is_get_only_and_backend_only(self) -> None:
        android_source = (
            ROOT
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "dk"
            / "ternedal"
            / "modelrig"
            / "net"
            / "Agent4OperatorClient.kt"
        ).read_text(encoding="utf-8")
        screen_source = (
            ROOT
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "dk"
            / "ternedal"
            / "modelrig"
            / "ui"
            / "Agent4OperatorScreen.kt"
        ).read_text(encoding="utf-8")
        detail_source = (
            ROOT
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "dk"
            / "ternedal"
            / "modelrig"
            / "ui"
            / "Agent4CampaignDetailScreen.kt"
        ).read_text(encoding="utf-8")

        self.assertIn(".get()", android_source)
        for forbidden in (
            ".post(",
            ".put(",
            ".delete(",
            "localhost:8099",
            "127.0.0.1:8099",
        ):
            self.assertNotIn(forbidden, android_source)
        self.assertIn(
            'private const val OPERATOR_PATH = "api/v1/experimental/agent4/operator"',
            android_source,
        )
        self.assertNotIn(
            'private const val OPERATOR_PATH = "experimental/agent4/operator"',
            android_source,
        )

        ui_text = screen_source + detail_source
        for forbidden_label in (
            'Text("Start")',
            'Text("Pause")',
            'Text("Genoptag")',
            'Text("Annullér")',
            'Text("Retry")',
        ):
            self.assertNotIn(forbidden_label, ui_text)

    def test_read_only_executor_remains_fail_closed(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "production_bootstrap.py"
        ).read_text(encoding="utf-8")
        for operation in (
            'self._reject("dispatch")',
            'self._reject("signal")',
            'self._reject("outcome lookup")',
        ):
            self.assertIn(operation, source)
        for forbidden in (
            ".recover(",
            ".dispatch_ready(",
            ".submit(",
            "threading.Thread",
            "asyncio.create_task",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
