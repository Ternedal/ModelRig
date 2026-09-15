"""Adversarial contract for ADR-DC-053 remote-publication write consumption."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_authorization_admission as admission  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_write_consumption as consumption  # noqa: E402
from rsi_pilot_exact_task_remote_head_observation_contract import _reader  # noqa: E402
from rsi_pilot_exact_task_remote_publication_authorization_admission_contract import _proof  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-write-consumption-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-053 unexpectedly consumed unsafe remote authority")


def _live_admission():
    values = _proof()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        local_consume_temp,
        object_ledger_temp,
        ref_ledger_temp,
        ref_receipt,
        identity,
        task,
        fixture,
        base_reader,
        requirements,
        remote_observation,
        claim,
        signature,
        supplied,
        fresh,
    ) = values
    remote_admission_temp = tempfile.TemporaryDirectory(
        prefix="rsi-remote-publication-admission-053-"
    )
    remote_admission_ledger = (
        admission._PilotExactTaskRemotePublicationAuthorizationAdmissionLedger(
            Path(remote_admission_temp.name)
        )
    )
    admission_times = iter(
        ("2026-09-15T05:36:11Z", "2026-09-15T05:36:12Z")
    )
    remote_admission = (
        admission._admit_verified_pilot_exact_task_remote_publication_authorization(
            supplied_proof=supplied,
            fresh_proof=fresh,
            remote_head_observation=remote_observation,
            ledger=remote_admission_ledger,
            now_provider=lambda: next(admission_times),
        )
    )
    assert remote_admission.admission_authenticated is True
    return (*values, remote_admission_temp, remote_admission)


def run_contract() -> None:
    if os.name == "nt":
        return

    values = _live_admission()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        local_consume_temp,
        object_ledger_temp,
        ref_ledger_temp,
        ref_receipt,
        identity,
        task,
        fixture,
        base_reader,
        requirements,
        remote_observation,
        claim,
        signature,
        supplied,
        fresh_proof,
        remote_admission_temp,
        remote_admission,
    ) = values
    ledger_temp = tempfile.TemporaryDirectory(
        prefix="rsi-remote-publication-consumption-"
    )
    try:
        ledger = consumption._PilotExactTaskRemotePublicationWriteConsumptionLedger(
            Path(ledger_temp.name)
        )
        calls, fixed, reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=task.base_sha,
        )
        times = iter(
            (
                "2026-09-15T05:36:13Z",
                "2026-09-15T05:36:14Z",
                "2026-09-15T05:36:15Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = (
                consumption._consume_verified_pilot_exact_task_remote_publication_authorization(
                    authorization_admission_receipt=remote_admission,
                    ledger=ledger,
                    now_provider=lambda: next(times),
                )
            )

        assert calls.count(fixed) == 2
        assert receipt.consumption_authenticated is True
        assert receipt.consumption_key_sha256 == supplied.remote_publication_nonce_sha256
        assert receipt.authorization_admission_receipt_sha256 == remote_admission.sha256
        assert receipt.authorization_proof_sha256 == supplied.sha256
        assert receipt.authorization_sha256 == claim.sha256
        assert receipt.authorization_signature_sha256 == signature.sha256
        assert receipt.original_remote_head_observation_sha256 == remote_observation.sha256
        assert receipt.original_observation_key_sha256 == remote_observation.observation_key_sha256
        assert receipt.fresh_remote_head_observation_sha256 != remote_observation.sha256
        assert receipt.fresh_remote_head_observation.observation_authenticated is True
        assert receipt.requirements_sha256 == requirements.sha256
        assert receipt.requirements_key_sha256 == requirements.requirements_key_sha256
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.local_commit_sha == identity.predicted_commit_sha
        assert receipt.destination_ref == requirements.destination_ref
        assert receipt.remote_head_present is True
        assert receipt.remote_head_sha == task.base_sha
        assert receipt.publication_mode == remote_observation.publication_mode
        assert receipt.host_consume_guard_committed is True
        assert receipt.human_remote_publication_authorization_verified is True
        assert receipt.remote_publication_authorization_admitted is True
        assert receipt.fresh_remote_head_revalidation_completed is True
        assert receipt.exact_remote_state_unchanged_since_admission is True
        assert receipt.remote_publication_authorization_consumed is True
        assert receipt.separate_fixed_push_transaction_required is True
        assert receipt.fresh_remote_head_revalidation_at_push_required is True
        assert receipt.network_access_performed is True
        assert receipt.credential_material_present is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = (
            consumption.PilotExactTaskRemotePublicationWriteConsumptionReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.consumption_authenticated is False
        assert reloaded.fresh_remote_head_observation.observation_authenticated is False

        replay_calls, replay_fixed, replay_reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=task.base_sha,
        )
        replay_times = iter(
            (
                "2026-09-15T05:36:16Z",
                "2026-09-15T05:36:17Z",
                "2026-09-15T05:36:18Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=replay_reader):
            _reject(
                lambda: consumption._consume_verified_pilot_exact_task_remote_publication_authorization(
                    authorization_admission_receipt=remote_admission,
                    ledger=ledger,
                    now_provider=lambda: next(replay_times),
                )
            )
        assert replay_calls.count(replay_fixed) == 2

        changed_temp = tempfile.TemporaryDirectory(
            prefix="rsi-remote-publication-consumption-changed-"
        )
        try:
            changed_ledger = (
                consumption._PilotExactTaskRemotePublicationWriteConsumptionLedger(
                    Path(changed_temp.name)
                )
            )
            changed_calls, changed_fixed, changed_reader = _reader(
                base_reader=base_reader,
                requirements=requirements,
                operation_root=fixture["git_runner"].operation_root,
                first=None,
            )
            changed_times = iter(
                (
                    "2026-09-15T05:36:19Z",
                    "2026-09-15T05:36:20Z",
                    "2026-09-15T05:36:21Z",
                )
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=changed_reader
            ):
                _reject(
                    lambda: consumption._consume_verified_pilot_exact_task_remote_publication_authorization(
                        authorization_admission_receipt=remote_admission,
                        ledger=changed_ledger,
                        now_provider=lambda: next(changed_times),
                    )
                )
            assert changed_calls.count(changed_fixed) == 2
            assert not changed_ledger._lock_path(
                remote_admission.remote_publication_nonce_sha256
            ).exists()
        finally:
            changed_temp.cleanup()

        expiry_temp = tempfile.TemporaryDirectory(
            prefix="rsi-remote-publication-consumption-expiry-"
        )
        try:
            expiry_ledger = (
                consumption._PilotExactTaskRemotePublicationWriteConsumptionLedger(
                    Path(expiry_temp.name)
                )
            )
            expiry_calls, expiry_fixed, expiry_reader = _reader(
                base_reader=base_reader,
                requirements=requirements,
                operation_root=fixture["git_runner"].operation_root,
                first=task.base_sha,
            )
            expiry_times = iter(
                (
                    "2026-09-15T05:41:59Z",
                    "2026-09-15T05:42:00Z",
                    "2026-09-15T05:42:01Z",
                )
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=expiry_reader
            ):
                _reject(
                    lambda: consumption._consume_verified_pilot_exact_task_remote_publication_authorization(
                        authorization_admission_receipt=remote_admission,
                        ledger=expiry_ledger,
                        now_provider=lambda: next(expiry_times),
                    )
                )
            assert expiry_calls.count(expiry_fixed) == 2
            assert not expiry_ledger._lock_path(
                remote_admission.remote_publication_nonce_sha256
            ).exists()
        finally:
            expiry_temp.cleanup()

        burned_temp = tempfile.TemporaryDirectory(
            prefix="rsi-remote-publication-consumption-burned-"
        )
        try:
            burned_ledger = (
                consumption._PilotExactTaskRemotePublicationWriteConsumptionLedger(
                    Path(burned_temp.name)
                )
            )
            burned_calls, burned_fixed, burned_reader = _reader(
                base_reader=base_reader,
                requirements=requirements,
                operation_root=fixture["git_runner"].operation_root,
                first=task.base_sha,
            )
            burned_times = iter(
                (
                    "2026-09-15T05:41:57Z",
                    "2026-09-15T05:41:58Z",
                    "2026-09-15T05:42:00Z",
                )
            )
            with patch.object(
                fixture["git_runner"], "run", side_effect=burned_reader
            ):
                _reject(
                    lambda: consumption._consume_verified_pilot_exact_task_remote_publication_authorization(
                        authorization_admission_receipt=remote_admission,
                        ledger=burned_ledger,
                        now_provider=lambda: next(burned_times),
                    )
                )
            assert burned_calls.count(burned_fixed) == 2
            assert burned_ledger._lock_path(
                remote_admission.remote_publication_nonce_sha256
            ).exists()
            assert not burned_ledger._receipt_path(
                remote_admission.remote_publication_nonce_sha256
            ).exists()
        finally:
            burned_temp.cleanup()

        reloaded_admission = (
            admission.PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt.from_mapping(
                remote_admission.to_dict()
            )
        )
        assert reloaded_admission.admission_authenticated is False
        reloaded_temp = tempfile.TemporaryDirectory(
            prefix="rsi-remote-publication-consumption-reloaded-"
        )
        try:
            reloaded_ledger = (
                consumption._PilotExactTaskRemotePublicationWriteConsumptionLedger(
                    Path(reloaded_temp.name)
                )
            )
            _reject(
                lambda: consumption._consume_verified_pilot_exact_task_remote_publication_authorization(
                    authorization_admission_receipt=reloaded_admission,
                    ledger=reloaded_ledger,
                    now_provider=lambda: "2026-09-15T05:36:22Z",
                )
            )
        finally:
            reloaded_temp.cleanup()

        for field, value in (
            ("host_consume_guard_committed", False),
            ("human_remote_publication_authorization_verified", False),
            ("remote_publication_authorization_admitted", False),
            ("fresh_remote_head_revalidation_completed", False),
            ("exact_remote_state_unchanged_since_admission", False),
            ("remote_publication_authorization_consumed", False),
            ("separate_fixed_push_transaction_required", False),
            ("fresh_remote_head_revalidation_at_push_required", False),
            ("network_access_performed", False),
            ("credential_material_present", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: consumption.PilotExactTaskRemotePublicationWriteConsumptionReceipt.from_mapping(
                    {**receipt.to_dict(), field: value}
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert (
            schema["properties"]["remote_publication_authorization_consumed"]["const"]
            is True
        )
        assert schema["properties"]["push_authorized"]["const"] is False

        public_api = inspect.signature(
            consumption.consume_pilot_exact_task_remote_publication_authorization
        ).parameters
        assert tuple(public_api) == ("authorization_admission_receipt",)
        source = inspect.getsource(consumption)
        implementation_source = inspect.getsource(consumption._implementation)
        assert "Ed25519PrivateKey" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("push",' not in implementation_source
        assert '("fetch",' not in implementation_source
        assert implementation_source.count(
            "_observe_verified_pilot_exact_task_remote_head("
        ) == 1
    finally:
        ledger_temp.cleanup()
        remote_admission_temp.cleanup()
        ref_ledger_temp.cleanup()
        object_ledger_temp.cleanup()
        local_consume_temp.cleanup()
        local_admission_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
