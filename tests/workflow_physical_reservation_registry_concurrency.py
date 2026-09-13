#!/usr/bin/env python3
"""Deterministic concurrency regressions for live reservation provenance."""
from __future__ import annotations

import gc
import os
import tempfile
import threading
from pathlib import Path

import workflow_physical_reservation_authority_races as race

import kaliv_dev_control._improvement_physical_reservation_provenance as file_provenance
from kaliv_dev_control._improvement_physical_reservation_registry_lock import (
    registry_lock,
)


def _must_block_while_registry_locked(operation, *, label: str) -> None:
    started = threading.Event()
    completed = threading.Event()
    failure: list[BaseException] = []

    def worker() -> None:
        started.set()
        try:
            operation()
        except BaseException as exc:  # pragma: no cover - surfaced below
            failure.append(exc)
        finally:
            completed.set()

    with registry_lock():
        thread = threading.Thread(target=worker, name=f"registry-{label}")
        thread.start()
        assert started.wait(1.0), f"{label} worker did not start"
        assert not completed.wait(0.15), (
            f"{label} bypassed the shared provenance registry lock"
        )

    assert completed.wait(2.0), f"{label} did not resume after lock release"
    thread.join(timeout=2.0)
    assert not thread.is_alive(), f"{label} worker remained blocked"
    if failure:
        raise AssertionError(f"{label} raised unexpectedly") from failure[0]


def test_transaction_revocation_uses_shared_registry_lock() -> None:
    token = object()
    _must_block_while_registry_locked(
        lambda: file_provenance.revoke_transaction_authenticated(token),
        label="transaction-revocation",
    )


def test_composed_live_authentication_uses_shared_registry_lock() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as directory:
        consumed, _ledger_root, _request = race._consume_fixture(
            Path(directory).resolve()
        )
        assert consumed.transaction_authenticated is True
        result: list[bool] = []

        _must_block_while_registry_locked(
            lambda: result.append(consumed.transaction_authenticated),
            label="live-authentication",
        )
        assert result == [True]


def test_live_receipt_weakref_cleanup_uses_shared_registry_lock() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as directory:
        consumed, _ledger_root, _request = race._consume_fixture(
            Path(directory).resolve()
        )
        assert consumed.transaction_authenticated is True
        holder = [consumed]
        del consumed

        def drop_last_reference() -> None:
            holder.clear()
            gc.collect()

        _must_block_while_registry_locked(
            drop_last_reference,
            label="weakref-cleanup",
        )
        assert holder == []


def main() -> None:
    test_transaction_revocation_uses_shared_registry_lock()
    test_composed_live_authentication_uses_shared_registry_lock()
    test_live_receipt_weakref_cleanup_uses_shared_registry_lock()
    print("physical reservation registry concurrency regressions: PASS")


if __name__ == "__main__":
    main()
