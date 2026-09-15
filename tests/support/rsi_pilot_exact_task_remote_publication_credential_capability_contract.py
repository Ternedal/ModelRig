"""Adversarial contract for ADR-DC-052 host-pinned credential capability."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_state_observation as state  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_write_reservation as reservation  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_remote_publication_credential_capability_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_remote_publication_state_observation_contract import (  # noqa: E402
    _attested_material,
    _observation_reader,
)

CAPABILITY_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-credential-capability-v1.schema.json"
)
POLICY_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-credential-broker-policy-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskRemotePublicationCredentialCapabilityError,
        production.PilotExactTaskRemotePublicationCredentialCapabilityProductionBoundaryError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-052 unexpectedly accepted unsafe credential capability")


def _reservation_material():
    material = _attested_material()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        local_reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        completed,
        requirements,
        attestation,
    ) = material
    ledger_temp = TemporaryDirectory(prefix="rsi-remote-write-reservation-052-")
    calls, _remote_args, reader = _observation_reader(
        fixture=fixture,
        task=task,
        identity=identity,
        staged=staged,
        index_payload=index_payload,
        completed=completed,
        attestation=attestation,
    )
    initial_times = iter(("2026-09-15T06:20:00Z", "2026-09-15T06:21:00Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        observation = state._observe_verified_pilot_exact_task_remote_publication_state(
            target_attestation=attestation,
            now_provider=lambda: next(initial_times),
        )
    assert calls
    ledger = reservation._PilotExactTaskRemotePublicationWriteReservationLedger(
        Path(ledger_temp.name)
    )
    fresh_calls, _fresh_remote_args, fresh_reader = _observation_reader(
        fixture=fixture,
        task=task,
        identity=identity,
        staged=staged,
        index_payload=index_payload,
        completed=completed,
        attestation=attestation,
    )
    reservation_times = iter(
        (
            "2026-09-15T06:21:10Z",
            "2026-09-15T06:21:20Z",
            "2026-09-15T06:21:30Z",
            "2026-09-15T06:21:40Z",
        )
    )
    with patch.object(fixture["git_runner"], "run", side_effect=fresh_reader):
        receipt = reservation._reserve_verified_pilot_exact_task_remote_publication_write(
            state_observation=observation,
            ledger=ledger,
            now_provider=lambda: next(reservation_times),
        )
    assert fresh_calls
    assert receipt.reservation_authenticated is True
    return material, ledger_temp, receipt


def _broker_descriptor(temp: TemporaryDirectory):
    root = Path(temp.name)
    broker = root / "rsi-github-askpass-v1"
    broker_bytes = b"modelrig-test-credential-broker-v1\n"
    broker.write_bytes(broker_bytes)
    broker.chmod(0o700)
    broker_sha = hashlib.sha256(broker_bytes).hexdigest()
    policy = {
        "schema": production.PILOT_EXACT_TASK_REMOTE_PUBLICATION_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "host": "github.com",
        "repository": "Ternedal/ModelRig",
        "credential_protocol": "git-askpass-v1",
        "broker_version": "test-v1",
        "broker_executable_path": os.fspath(broker),
        "broker_executable_sha256": broker_sha,
        "secret_source": "host-secret-store-only",
        "secret_transport": "askpass-stdout-direct-to-git-only",
        "repository_contents_write_required": True,
        "pull_request_write_forbidden": True,
        "administration_write_forbidden": True,
    }
    payload = json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    policy_path = root / "policy.json"
    policy_path.write_bytes(payload)
    descriptor = production._load_broker_descriptor_at(
        policy_path,
        broker,
        require_host_control=False,
    )
    return descriptor, policy_path, broker, policy


def run_contract() -> None:
    if os.name == "nt":
        return

    material, ledger_temp, receipt = _reservation_material()
    (
        source_temp,
        admission_ledger_temp,
        executor_capability_temp,
        local_reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        _identity,
        _task,
        _fixture,
        _staged,
        _index_payload,
        _completed,
        _requirements,
        _attestation,
    ) = material
    broker_temp = TemporaryDirectory(prefix="rsi-credential-broker-052-")
    try:
        descriptor, policy_path, broker_path, policy = _broker_descriptor(broker_temp)
        result = capability._materialize_verified_pilot_exact_task_remote_publication_credential_capability(
            remote_write_reservation=receipt,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:21:45Z",
        )

        assert result.remote_write_reservation_sha256 == receipt.sha256
        assert result.fresh_state_observation_sha256 == receipt.fresh_state_observation_sha256
        assert result.target_attestation_sha256 == receipt.target_attestation_sha256
        assert result.authorization_proof_sha256 == receipt.authorization_proof_sha256
        assert result.remote_publication_nonce_sha256 == receipt.remote_publication_nonce_sha256
        assert result.predicted_commit_sha == receipt.predicted_commit_sha
        assert result.destination_ref == receipt.destination_ref
        assert result.expected_old_remote_sha == "0" * 40
        assert result.broker_policy_sha256 == descriptor["broker_policy_sha256"]
        assert result.broker_executable_path_sha256 == descriptor["broker_executable_path_sha256"]
        assert result.broker_executable_sha256 == descriptor["broker_executable_sha256"]
        assert result.broker_version == "test-v1"
        assert result.credential_protocol == "git-askpass-v1"
        assert result.secret_source == "host-secret-store-only"
        assert result.secret_transport == "askpass-stdout-direct-to-git-only"
        assert result.materialized_at_utc == "2026-09-15T06:21:45Z"
        assert result.capability_authenticated is True

        for field in (
            "host_replay_guard_committed",
            "remote_publication_authorization_consumed",
            "remote_write_slot_reserved",
            "credential_broker_host_pinned",
            "credential_broker_binary_verified",
            "credential_secret_not_loaded",
            "one_shot_remote_write_required",
            "fresh_remote_state_revalidation_before_write_required",
            "create_only_remote_ref_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        artifact = result.to_dict()
        assert "broker_executable_path" not in artifact
        assert os.fspath(broker_path) not in result.canonical_json()
        assert "credential" not in artifact or "credential" in "".join(artifact.keys())

        reloaded = capability.PilotExactTaskRemotePublicationCredentialCapability.from_mapping(
            artifact
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        changed = dict(descriptor)
        changed["broker_executable_sha256"] = "a" * 64
        _reject(
            lambda: capability._materialize_verified_pilot_exact_task_remote_publication_credential_capability(
                remote_write_reservation=receipt,
                broker_descriptor=changed,
                now_provider=lambda: "2026-09-15T06:21:46Z",
            )
        )

        broker_path.write_bytes(b"tampered\n")
        _reject(
            lambda: production._load_broker_descriptor_at(
                policy_path,
                broker_path,
                require_host_control=False,
            )
        )

        capability_schema = json.loads(CAPABILITY_SCHEMA.read_text(encoding="utf-8"))
        assert set(capability_schema["properties"]) == set(artifact)
        assert set(capability_schema["required"]) == set(artifact)
        assert capability_schema["properties"]["credential_secret_not_loaded"]["const"] is True
        assert capability_schema["properties"]["credential_material_in_artifact"]["const"] is False
        assert capability_schema["properties"]["push_authorized"]["const"] is False
        assert capability_schema["properties"]["production_activation_authorized"]["const"] is False

        policy_schema = json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))
        assert set(policy_schema["properties"]) == set(policy)
        assert set(policy_schema["required"]) == set(policy)
        assert policy_schema["properties"]["provider"]["const"] == "github"
        assert policy_schema["properties"]["repository"]["const"] == "Ternedal/ModelRig"
        assert policy_schema["properties"]["pull_request_write_forbidden"]["const"] is True

        public_parameters = inspect.signature(
            capability.materialize_pilot_exact_task_remote_publication_credential_capability
        ).parameters
        assert tuple(public_parameters) == ("remote_write_reservation",)

        implementation_source = inspect.getsource(
            sys.modules[
                "kaliv_dev_control._improvement_pilot_exact_task_remote_publication_credential_capability_impl"
            ]
        )
        production_source = inspect.getsource(production)
        public_source = inspect.getsource(capability)
        combined = implementation_source + production_source + public_source
        assert "subprocess" not in combined
        assert "shell=True" not in combined
        assert '("push",' not in combined
        assert '("fetch",' not in combined
        assert '"ls-remote"' not in combined
        assert '("update-ref",' not in combined
        assert "create_pull_request" not in combined
        assert "merge_pull_request" not in combined
        assert "Authorization:" not in combined
    finally:
        broker_temp.cleanup()
        ledger_temp.cleanup()
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        local_reservation_temp.cleanup()
        executor_capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
