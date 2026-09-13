#!/usr/bin/env python3
"""Regressions for directory history, sibling churn, and production runtime host control."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import workflow_physical_reservation_authority_races as race

import kaliv_dev_control._improvement_physical_runtime_host_control as host_runtime
import kaliv_dev_control.improvement_physical_reservation as reservation_module


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


def test_unrelated_sibling_churn_does_not_revoke_live_receipt() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        consumed, ledger_root, _request = race._consume_fixture(root)
        assert consumed.transaction_authenticated is True

        # Campaign admission creates sibling directories below the canonical
        # host-state root before it rechecks the live reservation. Sibling
        # entry churn must not revoke an otherwise unchanged ledger receipt.
        sibling_ledger = ledger_root.parent / "rsi-physical-campaign-admission-ledger-v1"
        sibling_operation = ledger_root.parent / "rsi-physical-campaign-git-operation-v1"
        sibling_ledger.mkdir()
        sibling_operation.mkdir()
        assert consumed.transaction_authenticated is True
        sibling_operation.rmdir()
        sibling_ledger.rmdir()
        assert consumed.transaction_authenticated is True


def test_non_admin_posix_runtime_metadata_is_rejected() -> None:
    class FakeRegularFile:
        def lstat(self):
            return SimpleNamespace(
                st_mode=stat.S_IFREG | 0o700,
                st_nlink=1,
                st_uid=1000,
            )

    try:
        host_runtime._require_posix_object(FakeRegularFile(), is_directory=False)
    except host_runtime.PhysicalHostRuntimeError as exc:
        assert "not root-controlled" in str(exc)
    else:
        raise AssertionError("non-admin runtime ownership must fail closed")


def test_public_consume_routes_through_host_controlled_runtime_boundary() -> None:
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

        original_verifier = reservation_module._canonical_physical_request_authority_verifier
        original_ledger = reservation_module._canonical_host_ledger_root
        original_repository = reservation_module._canonical_repository_root
        original_operation = reservation_module._canonical_operation_root
        original_require = host_runtime._require_host_controlled_physical_git_runtime
        calls = 0

        def reject_same_user_runtime(runtime):
            nonlocal calls
            calls += 1
            assert type(runtime) is type(trusted_git)
            raise host_runtime.PhysicalHostRuntimeError(
                "synthetic same-user writable runtime"
            )

        reservation_module._canonical_physical_request_authority_verifier = lambda: verifier
        reservation_module._canonical_host_ledger_root = lambda: ledger_root
        reservation_module._canonical_repository_root = lambda: repository_root
        reservation_module._canonical_operation_root = lambda: operation_root
        host_runtime._require_host_controlled_physical_git_runtime = reject_same_user_runtime
        try:
            try:
                reservation_module.consume_physical_qualification_request_once(
                    trusted_git=trusted_git,
                    request=request,
                    qualification=qualification,
                    snapshot_receipt=snapshot_receipt,
                    signature=signature,
                )
            except reservation_module.PhysicalQualificationReservationError as exc:
                assert "host-controlled physical request Git runtime is unavailable" in str(exc)
            else:
                raise AssertionError(
                    "public consume must not fall back to caller-writable runtime staging"
                )
        finally:
            reservation_module._canonical_physical_request_authority_verifier = original_verifier
            reservation_module._canonical_host_ledger_root = original_ledger
            reservation_module._canonical_repository_root = original_repository
            reservation_module._canonical_operation_root = original_operation
            host_runtime._require_host_controlled_physical_git_runtime = original_require

        assert calls == 1
        assert not any(ledger_root.iterdir())


def main() -> None:
    test_ledger_root_rename_replay_restore_cannot_restore_first_receipt()
    test_unrelated_sibling_churn_does_not_revoke_live_receipt()
    test_non_admin_posix_runtime_metadata_is_rejected()
    test_public_consume_routes_through_host_controlled_runtime_boundary()
    print("physical reservation directory/runtime host-control regressions: PASS")


if __name__ == "__main__":
    main()
