"""Offline contract tests for GitHub handoff projection."""
import sqlite3

import pytest

from worker.app.github_handoff_projection import Handoff, HandoffProjection


def sample(**kwargs):
    fields = dict(repository="Ternedal/ModelRig", source_type="issue",
                  source_id=2319, revision="rev-1",
                  source_url="https://github.com/Ternedal/ModelRig/issues/2319")
    fields.update(kwargs)
    return Handoff(**fields)


def test_requires_explicit_authority():
    store = HandoffProjection(sqlite3.connect(":memory:"))
    with pytest.raises(PermissionError):
        store.ingest(sample())
    assert store.list_records() == []


def test_idempotent_and_revision_history():
    db = sqlite3.connect(":memory:")
    store = HandoffProjection(db)
    assert store.ingest(sample(), authorized=True)
    assert not store.ingest(sample(), authorized=True)
    assert store.ingest(sample(revision="rev-2"), authorized=True)
    assert len(store.list_records()) == 1
    assert store.list_records()[0]["revision"] == "rev-2"
    assert db.execute("SELECT COUNT(*) FROM handoff_revisions").fetchone()[0] == 2


def test_untrusted_claims_do_not_become_pass():
    store = HandoffProjection(sqlite3.connect(":memory:"))
    store.ingest(sample(), authorized=True)
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
