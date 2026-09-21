"""Durable live-provenance regressions for ADR-DC-010 campaign admission.

This support module is imported explicitly by the existing Stage-B workflow test.
It exercises the real private campaign transaction, not direct ledger minting:
original-publication provenance must therefore come from the same authenticated
transaction that returns the live admission.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

from kaliv_dev_control.improvement_physical_campaign_admission import (
    _PhysicalCampaignAdmissionLedger,
    _issue_physical_campaign_admission_once,
    build_physical_campaign_runner_authorization,
)


def _support_module():
    module = sys.modules.get("rsi_physical_campaign_admission_contract")
    if module is None:
        raise AssertionError("campaign admission contract must run before provenance contract")
    return module


def _issue_live(root: Path, *, suffix: str):
    support = _support_module()
    parent = support._load_parent_test_module()
    main_sha = "d" * 40
    fixture = parent._trusted_git_fixture(root, main_sha)
    assert fixture is not None
    trusted_git, reservation_operation_root, repository_root = fixture
    snapshot_receipt = parent._snapshot_receipt_fixture(trusted_git)
    qualification = parent._qualification_fixture(snapshot_receipt.sha256)
    request = parent._request_fixture(qualification)
    request_signature, request_verifier = parent._sign_request(request)
    reservation_ledger_root = support._fresh_dir(root, "reservation-ledger")
    reservation = parent._consume_physical_qualification_request_once(
        ledger_root=reservation_ledger_root,
        trusted_git=trusted_git,
        repository_root=repository_root,
        operation_root=reservation_operation_root,
        request=request,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        signature=request_signature,
        verifier=request_verifier,
        now_provider=parent._SequenceClock(
            [
                "2026-09-12T19:11:00Z",
                "2026-09-12T19:11:01Z",
                "2026-09-12T19:11:02Z",
            ]
        ),
    )
    assert reservation.transaction_authenticated is True

    runner_rel = f"scripts/rsi-dc-l15-provenance-{suffix}.py"
    runner_path = repository_root.joinpath(*runner_rel.split("/"))
    runner_path.parent.mkdir(exist_ok=True)
    runner_bytes = f"print('provenance {suffix}')\n".encode("utf-8")
    runner_path.write_bytes(runner_bytes)
    authorization = build_physical_campaign_runner_authorization(
        reservation=reservation,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        authorization_id=f"rsi-runner-prov-{suffix}",
        campaign_id=f"rsi-dc-l15-prov-{suffix}",
        runner_relative_path=runner_rel,
        runner_sha256=hashlib.sha256(runner_bytes).hexdigest(),
        runner_bytes=len(runner_bytes),
        authorized_at_utc="2026-09-12T19:11:05Z",
        expires_at_utc="2026-09-12T19:14:59Z",
    )
    signature, verifier = support._sign_runner_authorization(authorization)
    ledger_root = support._fresh_dir(root, f"admission-ledger-{suffix}")
    admission = _issue_physical_campaign_admission_once(
        ledger_root=ledger_root,
        trusted_git=trusted_git,
        repository_root=repository_root,
        operation_root=support._fresh_dir(root, f"admission-operation-{suffix}"),
        reservation=reservation,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        runner_authorization=authorization,
        runner_signature=signature,
        verifier=verifier,
        now_provider=parent._SequenceClock(
            [
                "2026-09-12T19:11:10Z",
                "2026-09-12T19:11:11Z",
                "2026-09-12T19:11:12Z",
            ]
        ),
    )
    assert admission.transaction_authenticated is True
    ledger = _PhysicalCampaignAdmissionLedger(ledger_root)
    final, pending, lock = ledger._paths(reservation.sha256)
    assert final.is_file() and not pending.exists() and lock.is_file()
    return admission, ledger_root, final, lock


def _remove_replay_tree(ledger_root: Path, final_name: str, lock_name: str) -> None:
    (ledger_root / final_name).unlink()
    (ledger_root / lock_name).unlink()
    ledger_root.rmdir()


def run_contract() -> None:
    # Deserialization/reload denial is covered in the main admission contract.
    # This module concentrates on durable identity/history after a real transaction.
    if os.name == "nt":
        # Descriptor identity is portable, but exact directory-history semantics in
        # this revision are intentionally a Linux production claim.
        return

    with tempfile.TemporaryDirectory(prefix="rsi-admission-prov-recreate-") as directory:
        root = Path(directory).resolve()
        live, _ledger_root, final, _lock = _issue_live(root, suffix="recreate")
        authenticated_sha = live.sha256
        original_campaign = live.campaign_id
        object.__setattr__(live, "campaign_id", f"{original_campaign}-mutated")
        assert live.sha256 != authenticated_sha
        assert live.transaction_authenticated is False
        object.__setattr__(live, "campaign_id", original_campaign)
        assert live.sha256 == authenticated_sha
        assert live.transaction_authenticated is True

        payload = final.read_bytes()
        final.unlink()
        final.write_bytes(payload)
        assert live.transaction_authenticated is False
        # Original-publication mismatch is monotonic: exact byte recreation cannot
        # establish a new baseline.
        assert live.transaction_authenticated is False

    with tempfile.TemporaryDirectory(prefix="rsi-admission-prov-ledger-") as directory:
        root = Path(directory).resolve()
        live, ledger_root, final, lock = _issue_live(root, suffix="ledger")
        final_payload = final.read_bytes()
        lock_payload = lock.read_bytes()
        final_name, lock_name = final.name, lock.name
        saved = ledger_root.with_name(f"{ledger_root.name}-saved")
        ledger_root.rename(saved)
        ledger_root.mkdir()
        (ledger_root / final_name).write_bytes(final_payload)
        (ledger_root / lock_name).write_bytes(lock_payload)
        _remove_replay_tree(ledger_root, final_name, lock_name)
        saved.rename(ledger_root)
        assert live.transaction_authenticated is False

    with tempfile.TemporaryDirectory(prefix="rsi-admission-prov-ancestor-") as directory:
        root = Path(directory).resolve()
        live, ledger_root, final, lock = _issue_live(root, suffix="ancestor")
        final_payload = final.read_bytes()
        lock_payload = lock.read_bytes()
        final_name, lock_name = final.name, lock.name
        ancestor = ledger_root.parent
        relative_ledger = ledger_root.relative_to(ancestor)
        saved_ancestor = ancestor.with_name(f"{ancestor.name}-saved")
        ancestor.rename(saved_ancestor)
        ancestor.mkdir()
        replay_ledger = ancestor / relative_ledger
        replay_ledger.mkdir()
        (replay_ledger / final_name).write_bytes(final_payload)
        (replay_ledger / lock_name).write_bytes(lock_payload)
        _remove_replay_tree(replay_ledger, final_name, lock_name)
        ancestor.rmdir()
        saved_ancestor.rename(ancestor)
        assert live.transaction_authenticated is False

    with tempfile.TemporaryDirectory(prefix="rsi-admission-prov-sibling-") as directory:
        root = Path(directory).resolve()
        live, ledger_root, _final, _lock = _issue_live(root, suffix="sibling")
        sibling = ledger_root.parent / "unrelated-sibling-after-arming"
        sibling.mkdir()
        assert live.transaction_authenticated is True
        sibling.rmdir()
        assert live.transaction_authenticated is True

    if hasattr(os, "fork"):
        with tempfile.TemporaryDirectory(prefix="rsi-admission-prov-fork-") as directory:
            root = Path(directory).resolve()
            live, _ledger_root, _final, _lock = _issue_live(root, suffix="fork")
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(read_fd)
                    os.write(write_fd, b"1" if live.transaction_authenticated else b"0")
                finally:
                    os.close(write_fd)
                    os._exit(0)
            os.close(write_fd)
            try:
                child_value = os.read(read_fd, 1)
            finally:
                os.close(read_fd)
            waited_pid, status = os.waitpid(pid, 0)
            assert waited_pid == pid
            assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
            assert child_value == b"0"
            assert live.transaction_authenticated is True
