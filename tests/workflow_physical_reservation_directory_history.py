#!/usr/bin/env python3
"""Regressions for reservation provenance, directory history, and host control."""
from __future__ import annotations

import gc
import os
import shutil
import stat
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import workflow_physical_reservation_authority_races as race

import kaliv_dev_control._improvement_physical_reservation_directory_provenance as directory_history
import kaliv_dev_control._improvement_physical_reservation_provenance as file_provenance
import kaliv_dev_control._improvement_physical_runtime_host_control as host_runtime
import kaliv_dev_control.improvement_physical_reservation as reservation_module
from kaliv_dev_control._improvement_physical_reservation_registry_lock import (
    registry_lock,
)


def _is_linux() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "uname")
        and os.uname().sysname == "Linux"
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


def test_ancestor_rename_replay_restore_cannot_restore_first_receipt() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (
            _main_sha,
            trusted_git,
            operation_root,
            repository_root,
            _fixture_ledger_root,
            snapshot_receipt,
            qualification,
            request,
            signature,
            verifier,
        ) = race._fixture(root)

        state_root = root / "host-state"
        ledger_root = state_root / "ledger"
        ledger_root.mkdir(parents=True)

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

        original_state = root / "host-state-original"
        state_root.rename(original_state)
        replacement_ledger = state_root / "ledger"
        replacement_ledger.mkdir(parents=True)

        second = race._consume(
            ledger_root=replacement_ledger,
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

        shutil.rmtree(state_root)
        original_state.rename(state_root)

        assert first.transaction_authenticated is False
        assert second.transaction_authenticated is False


def test_linux_watch_precedes_identity_capture_even_without_ctime_signal() -> None:
    if not _is_linux():
        return
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        state_root = root / "host-state"
        ledger_root = state_root / "ledger"
        ledger_root.mkdir(parents=True)
        moved = root / "host-state-moved"

        original_capture = directory_history._capture_nodes
        original_stamp = directory_history._metadata_stamp
        calls = 0

        def constant_stamp(_observed) -> int:
            return 1

        def racing_capture(ledger: Path):
            nonlocal calls
            calls += 1
            state_root.rename(moved)
            moved.rename(state_root)
            return original_capture(ledger)

        directory_history._metadata_stamp = constant_stamp
        directory_history._capture_nodes = racing_capture
        try:
            try:
                binding = directory_history._capture_binding(ledger_root, object())
            except directory_history.DirectoryBoundProvenanceError as exc:
                assert "identities were captured" in str(exc)
            else:
                directory_history._close_binding(binding)
                raise AssertionError(
                    "rename→restore after watch arming must fail without ctime evidence"
                )
        finally:
            directory_history._capture_nodes = original_capture
            directory_history._metadata_stamp = original_stamp

        assert calls == 1


def test_non_linux_posix_watch_before_trust_fails_closed() -> None:
    if not _is_linux():
        return
    with tempfile.TemporaryDirectory() as directory:
        ledger_root = Path(directory).resolve() / "ledger"
        ledger_root.mkdir()
        original_is_linux = directory_history._is_linux
        directory_history._is_linux = lambda: False
        try:
            try:
                directory_history._capture_binding(ledger_root, object())
            except directory_history.DirectoryBoundProvenanceError as exc:
                assert "race-free" in str(exc)
                assert "unsupported" in str(exc)
            else:
                raise AssertionError(
                    "production guard must fail closed without Linux watch-before-trust"
                )
        finally:
            directory_history._is_linux = original_is_linux


def test_unrelated_sibling_churn_does_not_revoke_live_receipt() -> None:
    if os.name != "posix":
        return
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        consumed, ledger_root, _request = race._consume_fixture(root)
        assert consumed.transaction_authenticated is True

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
    test_transaction_revocation_uses_shared_registry_lock()
    test_composed_live_authentication_uses_shared_registry_lock()
    test_live_receipt_weakref_cleanup_uses_shared_registry_lock()
    test_ledger_root_rename_replay_restore_cannot_restore_first_receipt()
    test_ancestor_rename_replay_restore_cannot_restore_first_receipt()
    test_linux_watch_precedes_identity_capture_even_without_ctime_signal()
    test_non_linux_posix_watch_before_trust_fails_closed()
    test_unrelated_sibling_churn_does_not_revoke_live_receipt()
    test_non_admin_posix_runtime_metadata_is_rejected()
    test_public_consume_routes_through_host_controlled_runtime_boundary()
    print("physical reservation provenance/directory/runtime regressions: PASS")


if __name__ == "__main__":
    main()
