#!/usr/bin/env python3
"""Cross-layer A4-19 campaign-list paging contract."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CampaignListPagingWorkflowTests(unittest.TestCase):
    def test_worker_and_android_share_cursor_schema(self) -> None:
        worker = (
            ROOT / "worker" / "app" / "agent4" / "campaign_list_query.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(worker)
        schema = None
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "CAMPAIGN_LIST_CURSOR_SCHEMA":
                schema = ast.literal_eval(node.value)
        android = (
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
        match = re.search(r'const val CAMPAIGN_CURSOR_SCHEMA = "([^"]+)"', android)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(schema, match.group(1))

    def test_api_keeps_campaigns_and_adds_snapshot_fields(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "operator_api.py"
        ).read_text(encoding="utf-8")
        for required in (
            "campaigns=[_overview(value) for value in page.campaigns]",
            "start_cursor=page.start_cursor.to_dict()",
            "next_cursor=page.next_cursor.to_dict()",
            "head_cursor=page.head_cursor.to_dict()",
            "has_more=page.has_more",
        ):
            self.assertIn(required, source)

    def test_android_has_no_local_offset_fallback(self) -> None:
        client = (
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
        screen = (
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
        self.assertIn('addQueryParameter("after", it.encoded)', client)
        self.assertIn('addQueryParameter("snapshot_head", it.encoded)', client)
        self.assertIn("next.startCursor == current.nextCursor", screen)
        self.assertIn("next.headCursor == current.headCursor", screen)
        for forbidden in ("offset", "pageIndex", "drop(", "takeLast("):
            self.assertNotIn(forbidden, client + screen)

    def test_cursor_snapshot_binds_filter_position_identity_and_hash(self) -> None:
        source = (
            ROOT / "worker" / "app" / "agent4" / "campaign_list_query.py"
        ).read_text(encoding="utf-8")
        for field in (
            '"statuses"',
            '"position"',
            '"total"',
            '"last_campaign_id"',
            '"snapshot_sha256"',
        ):
            self.assertIn(field, source)
        self.assertIn("cursor.statuses != normalized_statuses", source)
        self.assertIn("cursor.snapshot_sha256 != digest", source)
        self.assertIn("cursor.last_campaign_id != expected_last", source)


if __name__ == "__main__":
    unittest.main()
