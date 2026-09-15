"""Adversarial contract for ADR-DC-046 local-commit write consumption."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_authorization_admission as admission,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_consumption as consumption,
)
from rsi_pilot_exact_task_local_commit_authorization_admission_contract import (  # noqa: E402
    _source,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-write-consumption-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-046 unexpectedly accepted invalid authority")


def _live_admission():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        supplied,
        fresh,
        signature,
        _verifier,
        _manifest,
        identity,
        task,
        fixture,
        staged,
    ) = _source()
    local_admission_temp = tempfile.TemporaryDirectory(
        prefix="rsi-local-commit-auth-admission-for-consumption-"
    )
    ledger = admission._PilotExactTaskLocalCommitAuthorizationAdmissionLedger(
        Path(local_admission_temp.name).resolve()
    )
    index_payload = f"100644 {'1' * 40} 0\tVERSION\x00".encode("ascii")
    _calls, reader = _identity_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    times = iter(("2026-09-15T05:34:02Z", "2026-09-15T05:34:03Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        receipt = (
            admission._admit_verified_pilot_exact_task_local_commit_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                object_identity=identity,
                ledger=ledger,
                now_provider=lambda: next(times),
            )
        )
    assert receipt.admission_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        receipt,
        identity,
        task,
        fixture,
        staged,
        index_payload,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        admitted,
        identity,
        task,
        fixture,
        staged,
        index_payload,
    ) = _live_admission()
    consume_temp = tempfile.TemporaryDirectory(
        prefix="rsi-local-commit-write-consumption-"
    )
    try:
        ledger = consumption._PilotExactTaskLocalCommitWriteConsumptionLedger(
            Path(consume_temp.name).resolve()
        )
        calls, reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        times = iter(("2026-09-15T05:34:04Z", "2026-09-15T05:34:05Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = (
                consumption._consume_verified_pilot_exact_task_local_commit_authorization(
                    admission_receipt=admitted,
                    ledger=ledger,
                    now_provider=lambda: next(times),
                )
            )

        assert len(calls) == 19
        assert receipt.consumption_authenticated is True
        assert receipt.consumption_key_sha256 == admitted.local_commit_nonce_sha256
        assert receipt.admission_receipt_sha256 == admitted.sha256
        assert receipt.authorization_proof_sha256 == admitted.authorization_proof_sha256
        assert receipt.authorization_sha256 == admitted.authorization_sha256
        assert receipt.authorization_signature_sha256 == admitted.authorization_signature_sha256
        assert receipt.authorization_requirements_sha256 == admitted.authorization_requirements_sha256
        assert receipt.requirements_key_sha256 == admitted.requirements_key_sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.local_commit_plan_sha256 == admitted.local_commit_plan_sha256
        assert receipt.development_task_sha256 == admitted.development_task_sha256
        assert receipt.task_id == admitted.task_id
        assert receipt.repository == admitted.repository
        assert receipt.base_sha == identity.base_sha
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.index_entry_count == identity.index_entry_count
        assert receipt.commit_subject_sha256 == identity.commit_subject_sha256
        assert receipt.local_commit_nonce_sha256 == admitted.local_commit_nonce_sha256
        assert receipt.admitted_at_utc == admitted.admitted_at_utc
        assert receipt.prepared_at_utc == "2026-09-15T05:34:04Z"
        assert receipt.consumed_at_utc == "2026-09-15T05:34:05Z"
        assert receipt.host_consumption_guard_committed is True
        assert receipt.admission_authenticated_at_consumption is True
        assert receipt.human_local_commit_authorization_verified is True
        assert receipt.local_commit_authorization_admitted is True
        assert receipt.local_commit_authorization_consumed is True
        assert receipt.one_shot_local_commit_required is True
        assert receipt.exact_object_identity_revalidated is True
        assert receipt.fresh_workspace_snapshot_matched is True
        assert receipt.write_boundary_ready is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.local_commit_created is False
        assert receipt.push_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = (
            consumption.PilotExactTaskLocalCommitWriteConsumptionReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.consumption_authenticated is False

        replay_calls, replay_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        replay_times = iter(("2026-09-15T05:34:06Z", "2026-09-15T05:34:07Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=replay_reader):
            _reject(
                lambda: consumption._consume_verified_pilot_exact_task_local_commit_authorization(
                    admission_receipt=admitted,
                    ledger=ledger,
                    now_provider=lambda: next(replay_times),
                )
            )
        assert replay_calls

        reloaded_admission = (
            admission.PilotExactTaskLocalCommitAuthorizationAdmissionReceipt.from_mapping(
                admitted.to_dict()
            )
        )
        assert reloaded_admission.admission_authenticated is False
        other_temp = tempfile.TemporaryDirectory(
            prefix="rsi-local-commit-write-consumption-reloaded-"
        )
        try:
            _reject(
                lambda: consumption._consume_verified_pilot_exact_task_local_commit_authorization(
                    admission_receipt=reloaded_admission,
                    ledger=consumption._PilotExactTaskLocalCommitWriteConsumptionLedger(
                        Path(other_temp.name).resolve()
                    ),
                    now_provider=lambda: "2026-09-15T05:34:08Z",
                )
            )
        finally:
            other_temp.cleanup()

        for field, value in (
            ("host_consumption_guard_committed", False),
            ("admission_authenticated_at_consumption", False),
            ("local_commit_authorization_consumed", False),
            ("write_boundary_ready", False),
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("local_commit_created", True),
            ("push_authorized", True),
            ("production_activation_authorized", True),
            ("predicted_commit_sha", "a" * 40),
            ("consumption_key_sha256", "b" * 64),
        ):
            _reject(
                lambda field=field, value=value: (
                    consumption.PilotExactTaskLocalCommitWriteConsumptionReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["local_commit_authorization_consumed"]["const"] is True
        assert schema["properties"]["write_boundary_ready"]["const"] is True
        assert schema["properties"]["git_object_write_authorized"]["const"] is False
        assert schema["properties"]["local_ref_update_authorized"]["const"] is False
        assert schema["properties"]["local_commit_authorized"]["const"] is False
        assert schema["properties"]["local_commit_created"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            consumption.consume_pilot_exact_task_local_commit_authorization
        ).parameters
        assert tuple(public_parameters) == ("admission_receipt",)

        impl_source = inspect.getsource(
            sys.modules[
                "kaliv_dev_control._improvement_pilot_exact_task_local_commit_write_consumption_impl"
            ]
        )
        assert "create_once_file(" in impl_source
        assert "_revalidate_object_identity(" in impl_source
        assert "subprocess" not in impl_source
        assert "shell=True" not in impl_source
        assert '"write-tree"' not in impl_source
        assert '"commit-tree"' not in impl_source
        assert '("commit",' not in impl_source
        assert '("update-ref",' not in impl_source
        assert '("push",' not in impl_source
        assert '("reset",' not in impl_source
        assert '("clean",' not in impl_source
    finally:
        consume_temp.cleanup()
        local_admission_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
