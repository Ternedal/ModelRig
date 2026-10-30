"""Offline contract tests for GitHub handoff projection."""
import sqlite3

import pytest

from worker.app.github_handoff_projection import Handoff, HandoffProjection
from worker.app.github_connector_contract import (
    GitHubConnectorGrantStore, GitHubConnectorScope, GitHubSourceReceipt,
)


def sample(**kwargs):
    fields = dict(repository="Ternedal/ModelRig", source_type="issue",
                  source_id=2319, revision="rev-1",
                  source_url="https://github.com/Ternedal/ModelRig/issues/2319")
    fields.update(kwargs)
    return Handoff(**fields)


@pytest.fixture
def authority(tmp_path):
    grants = GitHubConnectorGrantStore(str(tmp_path / "grants.db"))
    scope = GitHubConnectorScope(account="ternedal", repositories=("Ternedal/ModelRig",),
                                 operations=("issue",))
    grant = grants.create(scope, actor="test", now=100)
    def receipt(revision="rev-1", object_id="2319"):
        return GitHubSourceReceipt(grant_id=grant.grant_id,
                                   scope_sha256=scope.digest,
                                   repository="Ternedal/ModelRig",
                                   repository_id=1287914122, object_type="issue",
                                   object_id=object_id, revision=revision, retrieved_at=101)
    yield grants, grant, receipt
    grants.close()


def test_requires_receipt_and_grant(authority):
    store = HandoffProjection(sqlite3.connect(":memory:"))
    grants, _, receipt = authority
    with pytest.raises((PermissionError, TypeError)):
        store.ingest(sample(), receipt=None, grants=grants)
    with pytest.raises(PermissionError):
        store.ingest(sample(), receipt=receipt(object_id="2320"), grants=grants)
    assert store.list_records() == []


def test_idempotent_and_revision_history(authority):
    grants, _, receipt = authority
    db = sqlite3.connect(":memory:")
    store = HandoffProjection(db)
    assert store.ingest(sample(), receipt=receipt(), grants=grants)
    assert not store.ingest(sample(), receipt=receipt(), grants=grants)
    assert store.ingest(sample(revision="rev-2"), receipt=receipt("rev-2"), grants=grants)
    assert len(store.list_records()) == 1
    assert store.list_records()[0]["revision"] == "rev-2"
    assert db.execute("SELECT COUNT(*) FROM handoff_revisions").fetchone()[0] == 2


def test_revocation_blocks_new_ingest(authority):
    grants, grant, receipt = authority
    store = HandoffProjection(sqlite3.connect(":memory:"))
    grants.revoke(grant.grant_id, actor="test", now=102)
    with pytest.raises(PermissionError):
        store.ingest(sample(), receipt=receipt(), grants=grants)


def test_unknown_is_not_pass(authority):
    grants, _, receipt = authority
    store = HandoffProjection(sqlite3.connect(":memory:"))
    store.ingest(sample(), receipt=receipt(), grants=grants)
    record = store.list_records()[0]
    assert all(record[key] == "UNKNOWN" for key in
               ("implemented", "tested", "handed_off", "released"))


@pytest.mark.parametrize("override", [
    {"source_url": "https://evil.example/issue/2319"},
    {"source_url": "https://github.com/Ternedal/Other/issues/2319"},
    {"source_id": True},
    {"revision": ""},
    {"head_sha": "deadbeef"},
    {"released": "YES"},
])
def test_invalid_source_rejected(override):
    with pytest.raises(ValueError):
        sample(**override)


def test_claimed_pass_is_not_evidence(authority):
    grants, _, receipt = authority
    store = HandoffProjection(sqlite3.connect(":memory:"))
    claimed = sample(implemented="PASS", tested="PASS", handed_off="PASS", released="PASS")
    store.ingest(claimed, receipt=receipt(), grants=grants)
    assert all(store.list_records()[0][field] == "UNKNOWN" for field in
               ("implemented", "tested", "handed_off", "released"))


def test_old_revision_cannot_replace_new_revision(authority):
    grants, _, receipt = authority
    store = HandoffProjection(sqlite3.connect(":memory:"))
    assert store.ingest(sample(), receipt=receipt(), grants=grants)
    assert store.ingest(sample(revision="rev-2"), receipt=receipt("rev-2"), grants=grants)
    assert not store.ingest(sample(), receipt=receipt(), grants=grants)
    assert store.list_records()[0]["revision"] == "rev-2"
