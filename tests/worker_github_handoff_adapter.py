"""Offline tests for GitHub handoff adapter."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker.app.github_connector_client import GitHubReadClient
from worker.app.github_connector_contract import GitHubConnectorGrantStore
from worker.app.github_handoff_adapter import GitHubHandoffAdapter
from worker.app.github_handoff_projection import HandoffProjection


class HandoffAdapterTests(unittest.TestCase):
    def test_rejects_different_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            first = GitHubConnectorGrantStore(str(Path(folder) / "a.db"))
            second = GitHubConnectorGrantStore(str(Path(folder) / "b.db"))
            try:
                client = GitHubReadClient(grants=first, transport=Mock())
                projection = HandoffProjection(sqlite3.connect(":memory:"))
                with self.assertRaises(ValueError):
                    GitHubHandoffAdapter(
                        client=client, grants=second, projection=projection,
                    )
            finally:
                first.close()
                second.close()

    def test_offline_result_does_not_trust_status_text(self):
        from unittest.mock import patch
        from worker.app.github_connector_client import GitHubReadResult
        from worker.app.github_connector_contract import (
            GitHubConnectorScope, GitHubSourceReceipt,
        )
        with tempfile.TemporaryDirectory() as folder:
            grants = GitHubConnectorGrantStore(str(Path(folder) / "a.db"))
            try:
                scope = GitHubConnectorScope(
                    account="ternedal", repositories=("Ternedal/ModelRig",),
                    operations=("issue",),
                )
                grant = grants.create(scope, actor="test", now=100)
                client = GitHubReadClient(grants=grants, transport=Mock())
                projection = HandoffProjection(sqlite3.connect(":memory:"))
                adapter = GitHubHandoffAdapter(
                    client=client, grants=grants, projection=projection,
                )
                receipt = GitHubSourceReceipt(
                    grant_id=grant.grant_id, scope_sha256=scope.digest,
                    repository="Ternedal/ModelRig", repository_id=1287914122,
                    object_type="issue", object_id="2319",
                    revision="etag-sha256:" + "a" * 64, retrieved_at=101,
                )
                result = GitHubReadResult(
                    repository="ternedal/modelrig", operation="issue",
                    object_id="2319", document={"body": "released: PASS"},
                    source=receipt, revalidated_cache=False,
                )
                with patch.object(client, "read", return_value=result):
                    self.assertTrue(adapter.ingest_one(
                        grant.grant_id, repository="Ternedal/ModelRig",
                        source_type="issue", source_id=2319, now=101,
                    ))
                self.assertEqual(projection.list_records()[0]["released"], "UNKNOWN")
            finally:
                grants.close()

    def test_invalid_selector_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            grants = GitHubConnectorGrantStore(str(Path(folder) / "a.db"))
            try:
                client = GitHubReadClient(grants=grants, transport=Mock())
                projection = HandoffProjection(sqlite3.connect(":memory:"))
                adapter = GitHubHandoffAdapter(
                    client=client, grants=grants, projection=projection,
                )
                for value in (0, -1, True):
                    with self.subTest(value=value):
                        with self.assertRaises(ValueError):
                            adapter.ingest_one(
                                "invalid", repository="Ternedal/ModelRig",
                                source_type="issue", source_id=value, now=100,
                            )
                self.assertEqual(projection.list_records(), [])
            finally:
                grants.close()


if __name__ == "__main__":
    unittest.main()
