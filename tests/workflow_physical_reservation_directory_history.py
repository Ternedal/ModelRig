#!/usr/bin/env python3
"""Regression for whole-ledger rename/replay/restore provenance resurrection."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import workflow_physical_reservation_authority_races as race


def test_ledger_root_rename_replay_restore_cannot_restore_first_receipt() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (
            _main_sha,
            trusted_git,
            operation_root,
            repository_root,
            ledger_root,
            snapshot_receipt,
            qualification,
            request,
            signature,
            verifier,
        ) = race._fixture(root)

        first = race._consume(
            ledger_root=ledger_root,
            trusted_git=trusted_git,
            repository_root=repository_root,
            operation_root=operation_root,
            request=request,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            signature=signature,
            verifier=verifier,
        )
        assert first.transaction_authenticated is True

        original_ledger = root / "ledger-original"
        ledger_root.rename(original_ledger)
        ledger_root.mkdir()

        # Replay succeeds while the canonical ledger path points at a fresh
        # directory. Do not inspect the first receipt while the attack is live;
        # restoration itself must not be able to hide the intervening replay.
        second = race._consume(
            ledger_root=ledger_root,
            trusted_git=trusted_git,
            repository_root=repository_root,
            operation_root=operation_root,
            request=request,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            signature=signature,
            verifier=verifier,
        )
        assert second.transaction_authenticated is True

        shutil.rmtree(ledger_root)
        original_ledger.rename(ledger_root)

        assert first.transaction_authenticated is False
        assert second.transaction_authenticated is False


def main() -> None:
    test_ledger_root_rename_replay_restore_cannot_restore_first_receipt()
    print("physical reservation ledger-directory history regression: PASS")


if __name__ == "__main__":
    main()
