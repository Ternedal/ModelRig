"""Offline contract tests for GitHub handoff projection (stdlib-only CI)."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# CI executes test files directly, so the repository root is not on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker.app.github_handoff_projection import Handoff, HandoffProjection
from worker.app.github_connector_contract import (
    GitHubConnectorGrantStore, GitHubConnectorScope, GitHubSourceReceipt,
)


def sample(**kwargs):
    fields = dict(
        repository="Ternedal/ModelRig",
        source_type="issue",
        source_id=2319,
        revision="rev-1",
        source_url="https://github.com/Ternedal/ModelRig/issues/2319",
    )
    fields.update(kwargs)
    return Handoff(**fields)


class HandoffProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.grants = GitHubConnectorGrantStore(
            str(Path(self.temp.name) / "grants.db")
        )
        self.scope = GitHubConnectorScope(
            account="ternedal",
            repositories=("Ternedal/ModelRig",),
            operations=("issue",),
        )
        self.grant = self.grants.create(self.scope, actor="test", now=100)

    def tearDown(self):
        self.grants.close()
        self.temp.cleanup()

    def receipt(self, revision="rev-1", object_id="2319"):
        return GitHubSourceReceipt(
            grant_id=self.grant.grant_id,
            scope_sha256=self.scope.digest,
            repository="Ternedal/ModelRig",
            repository_id=1287914122,
            object_type="issue",
            object_id=object_id,
            revision=revision,
            retrieved_at=101,
        )

    def test_requires_receipt_and_grant(self):
        store = HandoffProjection(sqlite3.connect(":memory:"))
        with self.assertRaises((PermissionError, TypeError)):
            store.ingest(sample(), receipt=None, grants=self.grants)
        with self.assertRaises(PermissionError):
            store.ingest(
                sample(), receipt=self.receipt(object_id="2320"),
                grants=self.grants,
            )
        self.assertEqual(store.list_records(), [])

    def test_idempotent_and_revision_history(self):
        db = sqlite3.connect(":memory:")
        store = HandoffProjection(db)
        self.assertTrue(store.ingest(sample(), receipt=self.receipt(), grants=self.grants))
        self.assertFalse(store.ingest(sample(), receipt=self.receipt(), grants=self.grants))
        self.assertTrue(store.ingest(
            sample(revision="rev-2"), receipt=self.receipt("rev-2"),
            grants=self.grants,
        ))
        self.assertEqual(len(store.list_records()), 1)
        self.assertEqual(store.list_records()[0]["revision"], "rev-2")
        self.assertEqual(
            db.execute("SELECT COUNT(*) FROM handoff_revisions").fetchone()[0], 2,
        )

    def test_repository_case_alias_has_one_canonical_identity(self):
        upper = sample()
        lower = sample(
            repository="ternedal/modelrig",
            source_url="https://github.com/ternedal/modelrig/issues/2319",
        )
        self.assertEqual(upper.repository, lower.repository)
        self.assertEqual(upper.source_url, lower.source_url)
        store = HandoffProjection(sqlite3.connect(":memory:"))
        self.assertTrue(store.ingest(upper, receipt=self.receipt(), grants=self.grants))
        self.assertFalse(store.ingest(lower, receipt=self.receipt(), grants=self.grants))
        self.assertEqual(len(store.list_records()), 1)

    def test_revocation_blocks_new_ingest(self):
        store = HandoffProjection(sqlite3.connect(":memory:"))
        self.grants.revoke(self.grant.grant_id, actor="test", now=102)
        with self.assertRaises(PermissionError):
            store.ingest(sample(), receipt=self.receipt(), grants=self.grants)

    def test_unknown_is_not_pass(self):
        store = HandoffProjection(sqlite3.connect(":memory:"))
        store.ingest(sample(), receipt=self.receipt(), grants=self.grants)
        record = store.list_records()[0]
        self.assertTrue(all(
            record[key] == "UNKNOWN"
            for key in ("implemented", "tested", "handed_off", "released")
        ))

    def test_invalid_source_rejected(self):
        overrides = (
            {"source_url": "https://evil.example/issue/2319"},
            {"source_url": "https://github.com/Ternedal/Other/issues/2319"},
            {"source_id": True},
            {"revision": ""},
            {"head_sha": "deadbeef"},
            {"released": "YES"},
        )
        for override in overrides:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    sample(**override)

    def test_claimed_pass_is_not_evidence(self):
        store = HandoffProjection(sqlite3.connect(":memory:"))
        claimed = sample(
            implemented="PASS", tested="PASS", handed_off="PASS", released="PASS",
        )
        store.ingest(claimed, receipt=self.receipt(), grants=self.grants)
        record = store.list_records()[0]
        self.assertTrue(all(
            record[field] == "UNKNOWN"
            for field in ("implemented", "tested", "handed_off", "released")
        ))

    def test_old_revision_cannot_replace_new_revision(self):
        store = HandoffProjection(sqlite3.connect(":memory:"))
        self.assertTrue(store.ingest(
            sample(), receipt=self.receipt(), grants=self.grants,
        ))
        self.assertTrue(store.ingest(
            sample(revision="rev-2"), receipt=self.receipt("rev-2"),
            grants=self.grants,
        ))
        self.assertFalse(store.ingest(
            sample(), receipt=self.receipt(), grants=self.grants,
        ))
        self.assertEqual(store.list_records()[0]["revision"], "rev-2")


if __name__ == "__main__":
    unittest.main()
