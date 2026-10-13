"""SQLite replay ledger atomic uniqueness and fail-closed tests."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kaliv_durable_attestation_replay_ledger import (
    ReplayLedgerError, record_verified_attestation,
)


class DurableReplayLedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "replay.sqlite3"
        self.kwargs = {
            "release_id": "release-1",
            "gate": "voicerig_physical_acceptance",
            "producer": "runner-1",
            "run_id": "run-1",
            "evidence_sha256": "a" * 64,
            "signature_verified": True,
        }

    def record(self, **changes):
        return record_verified_attestation(self.path, **{**self.kwargs, **changes})

    def test_first_verified_identity_persists(self):
        self.assertTrue(self.record())
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM accepted_attestations").fetchone()[0], 1)

    def test_replayed_identity_rejected_after_reopen(self):
        self.record()
        with self.assertRaisesRegex(ReplayLedgerError, "already recorded"):
            self.record()

    def test_distinct_run_allowed(self):
        self.record()
        self.assertTrue(self.record(run_id="run-2"))

    def test_unverified_signature_rejected(self):
        with self.assertRaisesRegex(ReplayLedgerError, "Unverified"):
            self.record(signature_verified=False)
        self.assertFalse(self.path.exists())

    def test_string_trust_flag_rejected(self):
        with self.assertRaises(ReplayLedgerError):
            self.record(signature_verified="true")

    def test_invalid_digest_rejected(self):
        with self.assertRaises(ReplayLedgerError):
            self.record(evidence_sha256="wrong")

    def test_relative_path_rejected(self):
        with self.assertRaisesRegex(ReplayLedgerError, "absolute"):
            record_verified_attestation("replay.sqlite3", **self.kwargs)

    def test_forged_schema_without_primary_key_rejected(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE accepted_attestations "
                "(release_id TEXT, gate TEXT, producer TEXT, run_id TEXT, evidence_sha256 TEXT)"
            )
        with self.assertRaisesRegex(ReplayLedgerError, "schema is not trusted"):
            self.record()

    def test_forged_schema_with_wrong_unique_constraint_rejected(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "CREATE TABLE accepted_attestations "
                "(release_id TEXT, gate TEXT, producer TEXT, run_id TEXT, "
                "evidence_sha256 TEXT, UNIQUE(release_id, gate))"
            )
        with self.assertRaisesRegex(ReplayLedgerError, "schema is not trusted"):
            self.record()

    def test_symlinked_parent_directory_rejected(self):
        target = Path(self.directory.name) / "actual"
        target.mkdir()
        alias = Path(self.directory.name) / "alias"
        alias.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ReplayLedgerError, "non-symlink"):
            record_verified_attestation(alias / "ledger.sqlite3", **self.kwargs)

    def test_directory_instead_of_database_rejected(self):
        self.path.mkdir()
        with self.assertRaisesRegex(ReplayLedgerError, "regular file"):
            self.record()

    def test_database_symlink_rejected(self):
        target = Path(self.directory.name) / "actual.sqlite3"
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ReplayLedgerError, "non-symlink"):
            self.record()


if __name__ == "__main__":
    unittest.main()
