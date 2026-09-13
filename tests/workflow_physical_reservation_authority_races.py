#!/usr/bin/env python3
"""Adversarial regressions for the RSI host-local reservation authority boundary."""
from __future__ import annotations

import inspect
import json
import os
import tempfile
from pathlib import Path

import workflow_physical_validation_final_gate as base

import kaliv_dev_control.improvement_physical_authority_keyring as keyring_module
import kaliv_dev_control.improvement_physical_reservation as reservation_module
import kaliv_dev_control.improvement_physical_reservation_impl as reservation_impl
from kaliv_dev_control.improvement_physical_reservation import (
    PhysicalQualificationReservationError,
    _consume_physical_qualification_request_once,
)
from kaliv_dev_control.trusted_git_runtime import TrustedGitRuntime


def _fixture(root: Path):
    main_sha = "d" * 40
    trusted = base._trusted_git_fixture(root, main_sha)
    assert trusted is not None
    trusted_git, operation_root, repository_root = trusted
    snapshot_receipt = base._snapshot_receipt_fixture(trusted_git)
    qualification = base._qualification_fixture(snapshot_receipt.sha256)
    request = base._request_fixture(qualification)
    signature, verifier = base._sign_request(request)
    ledger_root = root / "ledger"
    ledger_root.mkdir()
    return (
        main_sha,
        trusted_git,
        operation_root,
        repository_root,
        ledger_root,
        snapshot_receipt,
        qualification,
        request,
        signature,
        verifier,
    )


def _clock():
    return base._SequenceClock(
        [
            "2026-09-12T19:40:00Z",
            "2026-09-12T19:40:01Z",
            "2026-09-12T19:40:02Z",
        ]
    )


def _expect(fragment: str, fn) -> None:
    try:
        fn()
    except PhysicalQualificationReservationError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalQualificationReservationError containing {fragment!r}"
        )


def _expect_keyring(fragment: str, fn) -> None:
    try:
        fn()
    except keyring_module.PhysicalRequestAuthorityKeyringError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalRequestAuthorityKeyringError containing {fragment!r}"
        )


def test_public_surface_cannot_select_or_traverse_verifier() -> None:
    public_parameters = set(
        inspect.signature(
            reservation_module.consume_physical_qualification_request_once
        ).parameters
    )
    for forbidden in (
        "verifier",
        "ledger_root",
        "repository_root",
        "operation_root",
        "consumed_at_utc",
    ):
        assert forbidden not in public_parameters
    assert not hasattr(
        reservation_impl, "consume_physical_qualification_request_once"
    )
    assert not hasattr(reservation_impl, "_implementation")
    assert not hasattr(reservation_module, "_implementation")


def test_windows_acl_policy_rejects_untrusted_write_or_owner() -> None:
    system = "S-1-5-18"
    admins = "S-1-5-32-544"
    users = "S-1-5-32-545"
    read_only = 0x00120089
    generic_write = 0x40000000

    keyring_module._validate_windows_acl_snapshot(
        system,
        ((read_only, users), (generic_write, admins)),
        is_directory=False,
    )
    _expect_keyring(
        "untrusted write/control",
        lambda: keyring_module._validate_windows_acl_snapshot(
            system,
            ((generic_write, users),),
            is_directory=False,
        ),
    )
    _expect_keyring(
        "owner is not host-admin controlled",
        lambda: keyring_module._validate_windows_acl_snapshot(
            users,
            (),
            is_directory=True,
        ),
    )


def test_runtime_subclass_is_rejected() -> None:
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
        ) = _fixture(root)

        class OverridableTrustedGitRuntime(TrustedGitRuntime):
            def verify(self) -> None:
                return None

        attacker_runtime = OverridableTrustedGitRuntime(trusted_git.transaction_root)
        _expect(
            "exact TrustedGitRuntime",
            lambda: _consume_physical_qualification_request_once(
                ledger_root=ledger_root,
                trusted_git=attacker_runtime,
                repository_root=repository_root,
                operation_root=operation_root,
                request=request,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                signature=signature,
                verifier=verifier,
                now_provider=_clock(),
            ),
        )
        assert not any(ledger_root.iterdir())


def test_runtime_source_mutation_after_private_snapshot_cannot_change_observation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        (
            main_sha,
            trusted_git,
            operation_root,
            repository_root,
            ledger_root,
            snapshot_receipt,
            qualification,
            request,
            signature,
            verifier,
        ) = _fixture(root)
        source_executable = trusted_git.executable_path
        original_verify = reservation_impl._verify_request_at
        calls = 0

        def verify_then_mutate_source(**kwargs):
            nonlocal calls
            receipt = original_verify(**kwargs)
            calls += 1
            if calls == 1:
                source_executable.write_bytes(
                    b"#!/bin/sh\nprintf '%s\\n' '" + b"e" * 40 + b"'\n"
                )
                source_executable.chmod(0o755)
            return receipt

        reservation_impl._verify_request_at = verify_then_mutate_source
        try:
            consumed = _consume_physical_qualification_request_once(
                ledger_root=ledger_root,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=operation_root,
                request=request,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                signature=signature,
                verifier=verifier,
                now_provider=_clock(),
            )
        finally:
            reservation_impl._verify_request_at = original_verify

        assert calls == 2
        assert consumed.observed_main_sha == main_sha
        assert consumed.transaction_authenticated is True
        assert source_executable.read_bytes().endswith(b"'\n")


def test_verified_input_snapshot_survives_caller_mutation_after_verify() -> None:
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
        ) = _fixture(root)
        authenticated_qualification_sha = qualification.sha256
        original_verify = reservation_impl._verify_request_at
        calls = 0

        def verify_then_mutate(**kwargs):
            nonlocal calls
            receipt = original_verify(**kwargs)
            calls += 1
            if calls == 2:
                object.__setattr__(qualification, "baseline_eval_sha256", "0" * 64)
            return receipt

        reservation_impl._verify_request_at = verify_then_mutate
        try:
            consumed = _consume_physical_qualification_request_once(
                ledger_root=ledger_root,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=operation_root,
                request=request,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                signature=signature,
                verifier=verifier,
                now_provider=_clock(),
            )
        finally:
            reservation_impl._verify_request_at = original_verify

        assert calls == 2
        assert qualification.sha256 != authenticated_qualification_sha
        assert consumed.qualification_packet_sha256 == authenticated_qualification_sha
        assert consumed.transaction_authenticated is True


def test_final_swap_cannot_be_upgraded_to_live_authority() -> None:
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
        ) = _fixture(root)
        expected_final_name = f"{request.sha256}.json"
        original_create_once = reservation_impl.create_once_file
        swapped = False

        def create_then_swap(path, payload, *args, **kwargs):
            nonlocal swapped
            result = original_create_once(path, payload, *args, **kwargs)
            candidate = Path(path)
            if candidate.name == expected_final_name:
                value = json.loads(payload.decode("utf-8"))
                value["requester_actor_id"] = "attacker.actor"
                candidate.write_bytes(
                    reservation_impl._canonical(value).encode("utf-8")
                )
                swapped = True
            return result

        reservation_impl.create_once_file = create_then_swap
        try:
            _expect(
                "durably host-consumed but reservation requires recovery",
                lambda: _consume_physical_qualification_request_once(
                    ledger_root=ledger_root,
                    trusted_git=trusted_git,
                    repository_root=repository_root,
                    operation_root=operation_root,
                    request=request,
                    qualification=qualification,
                    snapshot_receipt=snapshot_receipt,
                    signature=signature,
                    verifier=verifier,
                    now_provider=_clock(),
                ),
            )
        finally:
            reservation_impl.create_once_file = original_create_once

        assert swapped is True
        loaded = reservation_module._PhysicalQualificationRequestLedger(ledger_root).load(
            request.sha256
        )
        assert loaded.requester_actor_id == "attacker.actor"
        assert loaded.transaction_authenticated is False


def test_final_removed_during_cleanup_fails_before_provenance_registration() -> None:
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
        ) = _fixture(root)
        final_path = ledger_root / f"{request.sha256}.json"
        original_unlink = reservation_impl.unlink_durable
        removed = False

        def unlink_then_remove_final(path):
            nonlocal removed
            result = original_unlink(path)
            if Path(path).name.endswith(".pending.json") and final_path.exists():
                final_path.unlink()
                removed = True
            return result

        reservation_impl.unlink_durable = unlink_then_remove_final
        try:
            _expect(
                "durably host-consumed but reservation requires recovery",
                lambda: _consume_physical_qualification_request_once(
                    ledger_root=ledger_root,
                    trusted_git=trusted_git,
                    repository_root=repository_root,
                    operation_root=operation_root,
                    request=request,
                    qualification=qualification,
                    snapshot_receipt=snapshot_receipt,
                    signature=signature,
                    verifier=verifier,
                    now_provider=_clock(),
                ),
            )
        finally:
            reservation_impl.unlink_durable = original_unlink

        assert removed is True
        replay_marker = ledger_root / f".{request.sha256}.lock"
        assert replay_marker.is_file()
        _expect(
            "host-locally consumed but reservation requires recovery",
            lambda: reservation_module._PhysicalQualificationRequestLedger(
                ledger_root
            ).load(request.sha256),
        )


def _consume_fixture(root: Path):
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
    ) = _fixture(root)
    consumed = _consume_physical_qualification_request_once(
        ledger_root=ledger_root,
        trusted_git=trusted_git,
        repository_root=repository_root,
        operation_root=operation_root,
        request=request,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        signature=signature,
        verifier=verifier,
        now_provider=_clock(),
    )
    return consumed, ledger_root, request


def test_recreated_final_bytes_cannot_restore_live_provenance() -> None:
    with tempfile.TemporaryDirectory() as directory:
        consumed, ledger_root, request = _consume_fixture(Path(directory).resolve())
        final_path = ledger_root / f"{request.sha256}.json"
        replay_marker = ledger_root / f".{request.sha256}.lock"
        assert final_path.is_file() and replay_marker.is_file()
        assert consumed.transaction_authenticated is True
        payload = final_path.read_bytes()
        final_path.unlink()
        assert consumed.transaction_authenticated is False
        final_path.write_bytes(payload)
        assert consumed.transaction_authenticated is False


def test_recreated_replay_marker_bytes_cannot_restore_live_provenance() -> None:
    with tempfile.TemporaryDirectory() as directory:
        consumed, ledger_root, request = _consume_fixture(Path(directory).resolve())
        replay_marker = ledger_root / f".{request.sha256}.lock"
        assert consumed.transaction_authenticated is True
        payload = replay_marker.read_bytes()
        replay_marker.unlink()
        assert consumed.transaction_authenticated is False
        replay_marker.write_bytes(payload)
        assert consumed.transaction_authenticated is False


def main() -> None:
    test_public_surface_cannot_select_or_traverse_verifier()
    test_windows_acl_policy_rejects_untrusted_write_or_owner()
    if os.name == "nt":
        print("RSI physical reservation authority-race regressions: PASS (surface/ACL policy; POSIX races skipped)")
        return
    test_runtime_subclass_is_rejected()
    test_runtime_source_mutation_after_private_snapshot_cannot_change_observation()
    test_verified_input_snapshot_survives_caller_mutation_after_verify()
    test_final_swap_cannot_be_upgraded_to_live_authority()
    test_final_removed_during_cleanup_fails_before_provenance_registration()
    test_recreated_final_bytes_cannot_restore_live_provenance()
    test_recreated_replay_marker_bytes_cannot_restore_live_provenance()
    print("RSI physical reservation authority-race regressions: PASS")


if __name__ == "__main__":
    main()
