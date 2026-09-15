"""Adversarial contract for ADR-DC-054 exact remote push-capability requirements."""
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

from kaliv_dev_control import improvement_pilot_exact_task_remote_push_capability_requirements as push_requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_write_consumption as consumption  # noqa: E402
from rsi_pilot_exact_task_remote_head_observation_contract import _reader  # noqa: E402
from rsi_pilot_exact_task_remote_publication_write_consumption_contract import _live_admission  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-push-capability-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-054 unexpectedly materialized unsafe push capability requirements")


def _live_consumption():
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
    consume_temp = tempfile.TemporaryDirectory(
        prefix="rsi-remote-push-capability-consumption-054-"
    )
    ledger = consumption._PilotExactTaskRemotePublicationWriteConsumptionLedger(
        Path(consume_temp.name)
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
    return (*values, consume_temp, receipt)


def run_contract() -> None:
    if os.name == "nt":
        return

    values = _live_consumption()
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
        consume_temp,
        consume_receipt,
    ) = values
    try:
        planned = (
            push_requirements._materialize_verified_pilot_exact_task_remote_push_capability_requirements(
                write_consumption_receipt=consume_receipt,
                now_provider=lambda: "2026-09-15T05:36:16Z",
            )
        )

        assert planned.requirements_authenticated is True
        assert planned.write_consumption_receipt_sha256 == consume_receipt.sha256
        assert planned.authorization_admission_receipt_sha256 == remote_admission.sha256
        assert planned.authorization_proof_sha256 == supplied.sha256
        assert planned.original_remote_head_observation_sha256 == remote_observation.sha256
        assert (
            planned.fresh_remote_head_observation_sha256
            == consume_receipt.fresh_remote_head_observation_sha256
        )
        assert planned.requirements_sha256 == requirements.sha256
        assert planned.requirements_key_sha256 == requirements.requirements_key_sha256
        assert planned.repository == task.repository
        assert planned.base_sha == task.base_sha
        assert planned.local_commit_sha == identity.predicted_commit_sha
        assert planned.source_ref == requirements.source_ref
        assert planned.destination_ref == requirements.destination_ref
        assert planned.source_ref == planned.destination_ref
        assert planned.canonical_remote_url == requirements.canonical_remote_url
        assert planned.remote_name == "origin"
        assert planned.remote_provider == "github"
        assert (
            planned.push_refspec
            == f"{identity.predicted_commit_sha}:{requirements.destination_ref}"
        )
        assert planned.expected_remote_head_present is True
        assert planned.expected_remote_head_sha == task.base_sha
        assert planned.publication_mode == remote_observation.publication_mode
        assert (
            planned.remote_publication_nonce_sha256
            == supplied.remote_publication_nonce_sha256
        )
        assert planned.consumed_at_utc == consume_receipt.consumed_at_utc
        assert planned.capability_materialized_at_utc == "2026-09-15T05:36:16Z"
        assert planned.capability_expires_at_utc == "2026-09-15T05:37:16Z"
        assert planned.push_timeout_seconds == 60
        assert planned.max_push_output_bytes == 65536
        assert planned.push_capability_max_age_seconds == 60
        assert planned.push_capability_requirements_materialized is True
        assert planned.remote_publication_authorization_consumed is True
        assert planned.consumption_authenticated_at_materialization is True
        assert planned.host_pinned_credential_provider_required is True
        assert planned.caller_supplied_credential_forbidden is True
        assert planned.credential_material_present is False
        assert planned.inherited_git_credential_helpers_forbidden is True
        assert planned.interactive_credential_prompt_forbidden is True
        assert planned.fast_forward_only_required is True
        assert planned.force_push_forbidden is True
        assert planned.force_with_lease_forbidden is True
        assert planned.remote_delete_forbidden is True
        assert planned.tag_publication_forbidden is True
        assert planned.remote_write_authorized is False
        assert planned.push_authorized is False
        assert planned.push_started is False
        assert planned.push_completed is False
        assert planned.pr_mutation_authorized is False
        assert planned.production_activation_authorized is False

        reloaded = (
            push_requirements.PilotExactTaskRemotePushCapabilityRequirements.from_mapping(
                planned.to_dict()
            )
        )
        assert reloaded == planned
        assert reloaded.sha256 == planned.sha256
        assert reloaded.requirements_authenticated is False

        reloaded_consumption = (
            consumption.PilotExactTaskRemotePublicationWriteConsumptionReceipt.from_mapping(
                consume_receipt.to_dict()
            )
        )
        assert reloaded_consumption.consumption_authenticated is False
        _reject(
            lambda: push_requirements._materialize_verified_pilot_exact_task_remote_push_capability_requirements(
                write_consumption_receipt=reloaded_consumption,
                now_provider=lambda: "2026-09-15T05:36:16Z",
            )
        )

        _reject(
            lambda: push_requirements._materialize_verified_pilot_exact_task_remote_push_capability_requirements(
                write_consumption_receipt=consume_receipt,
                now_provider=lambda: "2026-09-15T05:36:14Z",
            )
        )
        _reject(
            lambda: push_requirements._materialize_verified_pilot_exact_task_remote_push_capability_requirements(
                write_consumption_receipt=consume_receipt,
                now_provider=lambda: "2026-09-15T05:37:16Z",
            )
        )

        for field, value in (
            ("push_refspec", f"{identity.predicted_commit_sha}:refs/heads/other"),
            ("source_ref", "refs/heads/other"),
            ("expected_remote_head_sha", "a" * 40),
            ("capability_expires_at_utc", "2026-09-15T05:37:17Z"),
            ("push_timeout_seconds", 61),
            ("max_push_output_bytes", 1),
            ("push_capability_max_age_seconds", 61),
            ("host_pinned_credential_provider_required", False),
            ("caller_supplied_credential_forbidden", False),
            ("credential_material_present", True),
            ("inherited_git_credential_helpers_forbidden", False),
            ("interactive_credential_prompt_forbidden", False),
            ("fast_forward_only_required", False),
            ("force_push_forbidden", False),
            ("force_with_lease_forbidden", False),
            ("remote_delete_forbidden", False),
            ("tag_publication_forbidden", False),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("push_started", True),
            ("push_completed", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: push_requirements.PilotExactTaskRemotePushCapabilityRequirements.from_mapping(
                    {**planned.to_dict(), field: value}
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(planned.to_dict())
        assert set(schema["required"]) == set(planned.to_dict())
        assert (
            schema["properties"]["push_capability_requirements_materialized"]["const"]
            is True
        )
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False

        public_api = inspect.signature(
            push_requirements.materialize_pilot_exact_task_remote_push_capability_requirements
        ).parameters
        assert tuple(public_api) == ("write_consumption_receipt",)

        source = inspect.getsource(push_requirements)
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert ".run(" not in source
        assert '"ls-remote"' not in source
        assert '("push",' not in source
        assert "Ed25519PrivateKey" not in source
    finally:
        consume_temp.cleanup()
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
