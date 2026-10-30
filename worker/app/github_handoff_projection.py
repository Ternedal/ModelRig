"""Offline, inert GitHub handoff projection (no network or agent execution).

This module does not activate the GitHub connector. Source receipts must be
verified by the caller using the existing grant-bound connector authority.
"""
from __future__ import annotations

import json
import re
import sqlite3

from dataclasses import dataclass

from .github_connector_contract import GitHubConnectorGrantStore, GitHubSourceReceipt

_REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_STATES = frozenset({"UNKNOWN", "PASS", "FAIL"})


@dataclass(frozen=True)
class Handoff:
    repository: str
    source_type: str
    source_id: int
    revision: str
    source_url: str
    head_sha: str | None = None
    implemented: str = "UNKNOWN"
    tested: str = "UNKNOWN"
    handed_off: str = "UNKNOWN"
    released: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if not _REPO.fullmatch(self.repository):
            raise ValueError("invalid repository")
        if self.source_type not in ("issue", "pull_request"):
            raise ValueError("invalid source type")
        if type(self.source_id) is not int or self.source_id <= 0:
            raise ValueError("invalid source id")
        if not self.revision or len(self.revision) > 160:
            raise ValueError("invalid revision")
        expected = f"https://github.com/{self.repository}/"
        path = "issues" if self.source_type == "issue" else "pull"
        if self.source_url != f"{expected}{path}/{self.source_id}":
            raise ValueError("source URL must match identity")
        if self.head_sha is not None and not _SHA.fullmatch(self.head_sha):
            raise ValueError("invalid SHA")
        if any(getattr(self, name) not in _STATES for name in
               ("implemented", "tested", "handed_off", "released")):
            raise ValueError("invalid status")
        # Status claims must be supplied only by trusted evidence, never
        # inferred from arbitrary GitHub issue or PR text.


class HandoffProjection:
    """SQLite projection; caller is responsible for authorization and receipts."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.db.execute("""CREATE TABLE IF NOT EXISTS handoff_projection (
            repository TEXT NOT NULL, source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL, revision TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (repository, source_type, source_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS handoff_revisions (
            repository TEXT NOT NULL, source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL, revision TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (repository, source_type, source_id, revision))""")

    def ingest(self, handoff: Handoff, *, receipt: GitHubSourceReceipt, grants: GitHubConnectorGrantStore) -> bool:
        """Return True on a new revision; fail closed without explicit authority."""
        if not isinstance(receipt, GitHubSourceReceipt) or not isinstance(grants, GitHubConnectorGrantStore):
            raise PermissionError("verified GitHub receipt and grant store required")
        grant = grants.authorize(receipt.grant_id, repository=handoff.repository, operation=handoff.source_type)
        if (receipt.scope_sha256 != grant.scope.digest
                or receipt.repository != handoff.repository
                or receipt.object_type != handoff.source_type
                or receipt.object_id != str(handoff.source_id)
                or receipt.revision != handoff.revision):
            raise PermissionError("source receipt does not match handoff identity")
        from dataclasses import asdict
        record = asdict(handoff)
        # GitHub source identity does not establish CI, merge or release.
        for field in ('implemented', 'tested', 'handed_off', 'released'):
            record[field] = 'UNKNOWN'
        payload = json.dumps(record, sort_keys=True)
        key = (handoff.repository, handoff.source_type, handoff.source_id)
        with self.db:
            row = self.db.execute(
                "SELECT revision FROM handoff_projection WHERE repository=? AND source_type=? AND source_id=?",
                key,
            ).fetchone()
            if row is not None and row[0] == handoff.revision:
                return False
            # Do not roll back to an already-seen opaque revision.
            seen = self.db.execute(
                'SELECT 1 FROM handoff_revisions WHERE repository=? AND source_type=? AND source_id=? AND revision=?',
                (*key, handoff.revision),
            ).fetchone()
            if seen is not None:
                return False
            self.db.execute(
                "INSERT OR IGNORE INTO handoff_revisions VALUES (?, ?, ?, ?, ?)",
                (*key, handoff.revision, payload),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO handoff_projection VALUES (?, ?, ?, ?, ?)",
                (*key, handoff.revision, payload),
            )
        return True

    def list_records(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT payload FROM handoff_projection ORDER BY repository, source_type, source_id"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]
