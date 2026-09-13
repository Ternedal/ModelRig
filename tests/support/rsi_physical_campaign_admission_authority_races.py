"""Authority-race regressions for ADR-DC-010 physical campaign admission.

This support module is imported explicitly by the existing Stage-B gate.  It does
not extend the top-level repository test glob while ADR-DC-010 remains proposed.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import rsi_physical_campaign_admission_contract as base

import kaliv_dev_control.improvement_physical_campaign_admission as admission_module
from kaliv_dev_control.improvement_physical_campaign_admission import (
    PhysicalCampaignAdmissionError,
    _PhysicalCampaignAdmissionLedger,
    _issue_physical_campaign_admission_once,
    build_physical_campaign_runner_authorization,
)


def _expect(fragment: str, fn) -> None:
    try:
        fn()
    except PhysicalCampaignAdmissionError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalCampaignAdmissionError containing {fragment!r}"
        )


def _fixture(root: Path):
    parent = base._load_parent_test_module()
    main_sha = "d" * 40
    trusted = parent._trusted_git_fixture(root, main_sha)
    assert trusted is not None
    trusted_git, reservation_operation_root, repository_root = trusted
    snapshot_receipt = parent._snapshot_receipt_fixture(trusted_git)
    qualification = parent._qualification_fixture(snapshot_receipt.sha256)
    request = parent._request_fixture(qualification)
    request_signature, request_verifier = parent._sign_request(request)
    reservation_ledger_root = base._fresh_dir(root, "reservation-ledger")
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

    runner_rel = "scripts/rsi-dc-l15-race-runner-fixture.py"
    runner_path = repository_root / "scripts" / "rsi-dc-l15-race-runner-fixture.py"
    runner_path.parent.mkdir(exist_ok=True)
    runner_bytes = b"print('dc-l15 race runner fixture')\n"
    runner_path.write_bytes(runner_bytes)
    runner_sha = admission_module._sha256_bytes(runner_bytes)
    runner_authorization = build_physical_campaign_runner_authorization(
        reservation=reservation,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        authorization_id="rsi-runner-race-auth-001",
        campaign_id="rsi-dc-l15-race-campaign-001",
        runner_relative_path=runner_rel,
        runner_sha256=runner_sha,
        runner_bytes=len(runner_bytes),
        authorized_at_utc="2026-09-12T19:11:05Z",
        expires_at_utc="2026-09-12T19:14:59Z",
    )
    runner_signature, runner_verifier = base._sign_runner_authorization(
        runner_authorization
    )
    return (
        parent,
        trusted_git,
        repository_root,
        snapshot_receipt,
        qualification,
        reservation,
        runner_authorization,
        runner_signature,
        runner_verifier,
    )


def test_runtime_subclass_is_rejected() -> None:
    with tempfile.TemporaryDirectory(prefix="rsi-campaign-runtime-race-") as directory:
        root = Path(directory).resolve()
        (
            parent,
            trusted_git,
            repository_root,
            snapshot_receipt,
            qualification,
            reservation,
            runner_authorization,
            runner_signature,
            runner_verifier,
        ) = _fixture(root)

        class OverridableTrustedGitRuntime(admission_module.TrustedGitRuntime):
            def verify(self) -> None:
                return None

        attacker_runtime = OverridableTrustedGitRuntime(trusted_git.transaction_root)
        ledger_root = base._fresh_dir(root, "admission-ledger")
        _expect(
            "exact TrustedGitRuntime",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=ledger_root,
                trusted_git=attacker_runtime,
                repository_root=repository_root,
                operation_root=base._fresh_dir(root, "admission-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(["2026-09-12T19:11:10Z"]),
            ),
        )
        assert not any(ledger_root.iterdir())


def test_private_runtime_copy_survives_caller_runtime_mutation() -> None:
    with tempfile.TemporaryDirectory(prefix="rsi-campaign-runtime-copy-") as directory:
        root = Path(directory).resolve()
        (
            _parent,
            trusted_git,
            _repository_root,
            _snapshot_receipt,
            _qualification,
            _reservation,
            _runner_authorization,
            _runner_signature,
            _runner_verifier,
        ) = _fixture(root)
        operation_root = base._fresh_dir(root, "private-runtime-operation")
        snapshot_runtime, snapshot_root = admission_module._snapshot_trusted_git_runtime(
            trusted_git,
            operation_root=operation_root,
        )
        try:
            assert snapshot_runtime.transaction_root != Path(trusted_git.transaction_root).resolve()
            assert snapshot_root.parent == operation_root
            source_file = next(
                candidate
                for candidate in Path(trusted_git.runtime_root).rglob("*")
                if candidate.is_file()
            )
            source_file.write_bytes(source_file.read_bytes() + b"\n")
            snapshot_runtime.verify()
        finally:
            admission_module.remove_tree_durable(snapshot_root)


def test_verified_input_snapshot_survives_caller_mutation() -> None:
    with tempfile.TemporaryDirectory(prefix="rsi-campaign-input-race-") as directory:
        root = Path(directory).resolve()
        (
            parent,
            trusted_git,
            repository_root,
            snapshot_receipt,
            qualification,
            reservation,
            runner_authorization,
            runner_signature,
            runner_verifier,
        ) = _fixture(root)
        authenticated_qualification_sha = qualification.sha256
        original_verify = admission_module._verify_runner_authorization_at
        calls = 0

        def verify_then_mutate(**kwargs):
            nonlocal calls
            actor = original_verify(**kwargs)
            calls += 1
            if calls == 1:
                object.__setattr__(qualification, "baseline_eval_sha256", "0" * 64)
            return actor

        admission_module._verify_runner_authorization_at = verify_then_mutate
        try:
            admission = _issue_physical_campaign_admission_once(
                ledger_root=base._fresh_dir(root, "admission-ledger"),
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=base._fresh_dir(root, "admission-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(
                    [
                        "2026-09-12T19:11:10Z",
                        "2026-09-12T19:11:11Z",
                        "2026-09-12T19:11:12Z",
                    ]
                ),
            )
        finally:
            admission_module._verify_runner_authorization_at = original_verify

        assert calls == 2
        assert qualification.sha256 != authenticated_qualification_sha
        assert admission.qualification_packet_sha256 == authenticated_qualification_sha
        assert admission.transaction_authenticated is True


def test_final_swap_cannot_be_upgraded_to_live_authority() -> None:
    with tempfile.TemporaryDirectory(prefix="rsi-campaign-final-race-") as directory:
        root = Path(directory).resolve()
        (
            parent,
            trusted_git,
            repository_root,
            snapshot_receipt,
            qualification,
            reservation,
            runner_authorization,
            runner_signature,
            runner_verifier,
        ) = _fixture(root)
        ledger_root = base._fresh_dir(root, "admission-ledger")
        expected_final_name = f"{reservation.sha256}.json"
        original_create_once = admission_module.create_once_file
        swapped = False

        def create_then_swap(path, payload, *args, **kwargs):
            nonlocal swapped
            result = original_create_once(path, payload, *args, **kwargs)
            candidate = Path(path)
            if candidate.name == expected_final_name:
                value = json.loads(payload.decode("utf-8"))
                value["runner_authorizer_actor_id"] = "attacker.actor"
                candidate.write_bytes(
                    admission_module._canonical(value).encode("utf-8")
                )
                swapped = True
            return result

        admission_module.create_once_file = create_then_swap
        try:
            _expect(
                "durably host-consumed but requires recovery",
                lambda: _issue_physical_campaign_admission_once(
                    ledger_root=ledger_root,
                    trusted_git=trusted_git,
                    repository_root=repository_root,
                    operation_root=base._fresh_dir(root, "admission-operation"),
                    reservation=reservation,
                    qualification=qualification,
                    snapshot_receipt=snapshot_receipt,
                    runner_authorization=runner_authorization,
                    runner_signature=runner_signature,
                    verifier=runner_verifier,
                    now_provider=parent._SequenceClock(
                        [
                            "2026-09-12T19:11:10Z",
                            "2026-09-12T19:11:11Z",
                            "2026-09-12T19:11:12Z",
                        ]
                    ),
                ),
            )
        finally:
            admission_module.create_once_file = original_create_once

        assert swapped is True
        loaded = _PhysicalCampaignAdmissionLedger(ledger_root).load(
            reservation.sha256
        )
        assert loaded.runner_authorizer_actor_id == "attacker.actor"
        assert loaded.transaction_authenticated is False


def run_contract() -> None:
    test_runtime_subclass_is_rejected()
    test_private_runtime_copy_survives_caller_runtime_mutation()
    test_verified_input_snapshot_survives_caller_mutation()
    test_final_swap_cannot_be_upgraded_to_live_authority()
