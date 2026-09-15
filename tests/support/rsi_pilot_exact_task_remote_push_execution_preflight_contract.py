"""Adversarial contract for ADR-DC-056 exact remote push execution preflight."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_remote_push_execution_preflight as preflight  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_push_capability_requirements as push_requirements  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_remote_push_credential_capability_impl as credential_impl  # noqa: E402
from rsi_pilot_exact_task_remote_push_capability_requirements_contract import _live_consumption  # noqa: E402
from rsi_pilot_exact_task_remote_push_credential_capability_contract import _provider  # noqa: E402
from rsi_pilot_exact_task_remote_head_observation_contract import _reader  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-remote-push-execution-preflight-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-056 unexpectedly accepted unsafe push preflight")


def _live_capability():
    values = _live_consumption()
    (
        source_temp, admission_ledger_temp, capability_temp, reservation_temp,
        execution_temp, local_admission_temp, local_consume_temp, object_ledger_temp,
        ref_ledger_temp, ref_receipt, identity, task, fixture, base_reader,
        requirements, remote_observation, claim, signature, supplied, fresh_proof,
        remote_admission_temp, remote_admission, consume_temp, consume_receipt,
    ) = values
    push_req = (
        push_requirements._materialize_verified_pilot_exact_task_remote_push_capability_requirements(
            write_consumption_receipt=consume_receipt,
            now_provider=lambda: "2026-09-15T05:36:16Z",
        )
    )
    provider = _provider(
        repository=task.repository,
        canonical_remote_url=push_req.canonical_remote_url,
    )
    capability = (
        credential_impl._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=provider,
            provider_attestation_host_controlled=True,
            now_provider=lambda: "2026-09-15T05:36:17Z",
        )
    )
    assert push_req.requirements_authenticated is True
    assert capability.capability_authenticated is True
    return (*values, push_req, provider, capability)


def run_contract() -> None:
    if os.name == "nt":
        return

    values = _live_capability()
    (
        source_temp, admission_ledger_temp, capability_temp, reservation_temp,
        execution_temp, local_admission_temp, local_consume_temp, object_ledger_temp,
        ref_ledger_temp, ref_receipt, identity, task, fixture, base_reader,
        requirements, remote_observation, claim, signature, supplied, fresh_proof,
        remote_admission_temp, remote_admission, consume_temp, consume_receipt,
        push_req, provider, capability,
    ) = values
    try:
        calls, fixed, reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=task.base_sha,
        )
        times = iter(
            (
                "2026-09-15T05:36:18Z",
                "2026-09-15T05:36:19Z",
                "2026-09-15T05:36:20Z",
                "2026-09-15T05:36:21Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = preflight._preflight_verified_pilot_exact_task_remote_push(
                credential_capability=capability,
                now_provider=lambda: next(times),
            )

        assert calls.count(fixed) == 2
        assert receipt.preflight_authenticated is True
        assert receipt.credential_capability_sha256 == capability.sha256
        assert receipt.push_capability_requirements_sha256 == push_req.sha256
        assert receipt.write_consumption_receipt_sha256 == consume_receipt.sha256
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.local_commit_sha == identity.predicted_commit_sha
        assert receipt.destination_ref == push_req.destination_ref
        assert receipt.canonical_remote_url == push_req.canonical_remote_url
        assert receipt.push_refspec == push_req.push_refspec
        assert receipt.remote_publication_nonce_sha256 == consume_receipt.remote_publication_nonce_sha256
        assert receipt.provider_attestation_sha256 == provider.sha256
        assert receipt.provider_instance_id == provider.provider_instance_id
        assert receipt.provider_epoch == provider.provider_epoch
        assert receipt.credential_slot_sha256 == provider.credential_slot_sha256
        assert receipt.fresh_remote_head_observation.observation_authenticated is True
        assert receipt.fresh_remote_head_observation.remote_head_present is True
        assert receipt.fresh_remote_head_observation.remote_head_sha == task.base_sha
        assert receipt.expected_remote_head_present is True
        assert receipt.expected_remote_head_sha == task.base_sha
        assert receipt.preflight_started_at_utc == "2026-09-15T05:36:18Z"
        assert receipt.fresh_remote_observation_started_at_utc == "2026-09-15T05:36:19Z"
        assert receipt.fresh_remote_observation_completed_at_utc == "2026-09-15T05:36:20Z"
        assert receipt.preflight_completed_at_utc == "2026-09-15T05:36:21Z"
        assert receipt.preflight_expires_at_utc == "2026-09-15T05:36:31Z"
        assert receipt.credential_capability_authenticated_at_preflight is True
        assert receipt.fresh_remote_head_revalidation_completed is True
        assert receipt.exact_remote_state_unchanged is True
        assert receipt.local_source_state_revalidated is True
        assert receipt.provider_attestation_replay_revalidated is True
        assert receipt.opaque_credential_slot_bound is True
        assert receipt.credential_broker_invocation_required is True
        assert receipt.credential_broker_invoked is False
        assert receipt.credential_handle_materialized is False
        assert receipt.raw_credential_material_present is False
        assert receipt.credential_export_authorized is False
        assert receipt.credential_read_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.push_started is False
        assert receipt.push_completed is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = preflight.PilotExactTaskRemotePushExecutionPreflight.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.preflight_authenticated is False

        reloaded_capability = credential_impl.PilotExactTaskRemotePushCredentialCapability.from_mapping(
            capability.to_dict()
        )
        assert reloaded_capability.capability_authenticated is False
        _reject(
            lambda: preflight._preflight_verified_pilot_exact_task_remote_push(
                credential_capability=reloaded_capability,
                now_provider=lambda: "2026-09-15T05:36:22Z",
            )
        )

        absent_calls, absent_fixed, absent_reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=None,
        )
        absent_times = iter(
            (
                "2026-09-15T05:36:22Z",
                "2026-09-15T05:36:23Z",
                "2026-09-15T05:36:24Z",
                "2026-09-15T05:36:25Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=absent_reader):
            _reject(
                lambda: preflight._preflight_verified_pilot_exact_task_remote_push(
                    credential_capability=capability,
                    now_provider=lambda: next(absent_times),
                )
            )
        assert absent_calls.count(absent_fixed) == 2

        drift_calls, drift_fixed, drift_reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=task.base_sha,
            second="a" * 40,
        )
        drift_times = iter(
            (
                "2026-09-15T05:36:22Z",
                "2026-09-15T05:36:23Z",
                "2026-09-15T05:36:24Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(
                lambda: preflight._preflight_verified_pilot_exact_task_remote_push(
                    credential_capability=capability,
                    now_provider=lambda: next(drift_times),
                )
            )
        assert drift_calls.count(drift_fixed) == 2

        expired_calls, expired_fixed, expired_reader = _reader(
            base_reader=base_reader,
            requirements=requirements,
            operation_root=fixture["git_runner"].operation_root,
            first=task.base_sha,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=expired_reader):
            _reject(
                lambda: preflight._preflight_verified_pilot_exact_task_remote_push(
                    credential_capability=capability,
                    now_provider=lambda: "2026-09-15T05:36:47Z",
                )
            )
        assert expired_calls.count(expired_fixed) == 0

        for field, value in (
            ("credential_capability_sha256", "a" * 64),
            ("fresh_remote_head_observation_sha256", "a" * 64),
            ("fresh_observation_key_sha256", "a" * 64),
            ("broker_request_sha256", "a" * 64),
            ("credential_slot_sha256", "a" * 64),
            ("expected_remote_head_sha", "a" * 40),
            ("preflight_expires_at_utc", "2026-09-15T05:36:32Z"),
            ("credential_capability_authenticated_at_preflight", False),
            ("fresh_remote_head_revalidation_completed", False),
            ("exact_remote_state_unchanged", False),
            ("local_source_state_revalidated", False),
            ("provider_attestation_replay_revalidated", False),
            ("opaque_credential_slot_bound", False),
            ("credential_broker_invocation_required", False),
            ("credential_broker_invoked", True),
            ("credential_handle_materialized", True),
            ("raw_credential_material_present", True),
            ("credential_export_authorized", True),
            ("credential_read_authorized", True),
            ("inherited_git_credential_helpers_forbidden", False),
            ("interactive_credential_prompt_forbidden", False),
            ("exact_push_refspec_bound", False),
            ("push_transaction_must_revalidate_provider_attestation", False),
            ("push_transaction_must_revalidate_remote_head", False),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("push_started", True),
            ("push_completed", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: preflight.PilotExactTaskRemotePushExecutionPreflight.from_mapping(
                    {**receipt.to_dict(), field: value}
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["credential_broker_invoked"]["const"] is False
        assert schema["properties"]["credential_handle_materialized"]["const"] is False
        assert schema["properties"]["credential_read_authorized"]["const"] is False
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False

        public_api = inspect.signature(
            preflight.preflight_pilot_exact_task_remote_push
        ).parameters
        assert tuple(public_api) == ("credential_capability",)

        source = inspect.getsource(preflight)
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("push",' not in source
        assert "Ed25519PrivateKey" not in source
        assert "_observe_verified_pilot_exact_task_remote_head(" in source
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
