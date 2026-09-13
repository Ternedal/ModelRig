#!/usr/bin/env python3
"""Adversarial regressions for the RSI host-local reservation authority boundary."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import workflow_physical_validation_final_gate as base

import kaliv_dev_control.improvement_physical_reservation as reservation_module
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
        original_verify = reservation_module._verify_request_at
        calls = 0

        def verify_then_mutate(**kwargs):
            nonlocal calls
            receipt = original_verify(**kwargs)
            calls += 1
            if calls == 2:
                object.__setattr__(qualification, "baseline_eval_sha256", "0" * 64)
            return receipt

        reservation_module._verify_request_at = verify_then_mutate
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
            reservation_module._verify_request_at = original_verify

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
        original_create_once = reservation_module.create_once_file
        swapped = False

        def create_then_swap(path, payload, *args, **kwargs):
            nonlocal swapped
            result = original_create_once(path, payload, *args, **kwargs)
            candidate = Path(path)
            if candidate.name == expected_final_name:
                value = json.loads(payload.decode("utf-8"))
                value["requester_actor_id"] = "attacker.actor"
                candidate.write_bytes(
                    reservation_module._canonical(value).encode("utf-8")
                )
                swapped = True
            return result

        reservation_module.create_once_file = create_then_swap
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
            reservation_module.create_once_file = original_create_once

        assert swapped is True
        loaded = reservation_module._PhysicalQualificationRequestLedger(ledger_root).load(
            request.sha256
        )
        assert loaded.requester_actor_id == "attacker.actor"
        assert loaded.transaction_authenticated is False


def main() -> None:
    if os.name == "nt":
        print("RSI physical reservation authority-race regressions: SKIP (POSIX fixture)")
        return
    test_runtime_subclass_is_rejected()
    test_verified_input_snapshot_survives_caller_mutation_after_verify()
    test_final_swap_cannot_be_upgraded_to_live_authority()
    print("RSI physical reservation authority-race regressions: PASS")


if __name__ == "__main__":
    main()
