"""Atomic SQLite replay identity ledger for an independently managed coordinator.

This is a durable anti-replay building block, NOT a release authorization service.
The coordinator must own the database path, filesystem permissions, backups,
and the transaction boundary with its external approval workflow.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


class ReplayLedgerError(ValueError):
    """Replay, invalid identity or storage failure."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS accepted_attestations (
    release_id TEXT NOT NULL,
    gate TEXT NOT NULL,
    producer TEXT NOT NULL,
    run_id TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    PRIMARY KEY (release_id, gate, producer, run_id)
);
"""


def _validate(fields: tuple[str, ...]) -> None:
    if any(type(value) is not str or not value or len(value) > 256
           or value.strip() != value for value in fields):
        raise ReplayLedgerError("Invalid replay identity")


def record_verified_attestation(
    database_path: str | Path,
    *,
    release_id: str,
    gate: str,
    producer: str,
    run_id: str,
    evidence_sha256: str,
    signature_verified: bool,
) -> bool:
    """Atomically reserve a verified attestation identity once.

    Returns True only for a new record. Duplicate identities fail closed.
    signature_verified must be literal True from a trusted caller, never read
    from a user-supplied attestation or an untrusted JSON result.
    """
    identity = (release_id, gate, producer, run_id)
    _validate(identity)
    if type(evidence_sha256) is not str or len(evidence_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in evidence_sha256
    ):
        raise ReplayLedgerError("Invalid evidence digest")
    if signature_verified is not True:
        raise ReplayLedgerError("Unverified attestation cannot be recorded")
    path = Path(database_path)
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise ReplayLedgerError("Coordinator database path must be absolute and non-symlink")
    try:
        # BEGIN IMMEDIATE obtains the write lock before checking uniqueness.
        with sqlite3.connect(str(path), timeout=5.0) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_SCHEMA)
            conn.execute(
                "INSERT INTO accepted_attestations "
                "(release_id, gate, producer, run_id, evidence_sha256) "
                "VALUES (?, ?, ?, ?, ?)",
                (*identity, evidence_sha256),
            )
        return True
    except sqlite3.IntegrityError as exc:
        raise ReplayLedgerError("Attestation identity already recorded") from exc
    except sqlite3.Error as exc:
        raise ReplayLedgerError("Replay ledger unavailable") from exc
