"""Adversarial contract for ADR-DC-051 durable remote-write reservation."""
from __future__ import annotations

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

from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_state_observation as state  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_write_reservation as reservation  # noqa: E402
from rsi_pilot_exact_task_remote_publication_state_observation_contract import (  # noqa: E402
    _attested_material,
    _observation_reader,
)

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-remote-publication-write-reservation-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        reservation.PilotExactTaskRemotePublicationWriteReservationError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-051 unexpectedly accepted unsafe reservation")


def run_contract() -> None:
    if os.name == "nt":
        return

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
    ledger_temp = TemporaryDirectory(prefix="rsi-remote-write-reservation-051-")
    try:
        calls, remote_args, reader = _observation_reader(
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
        assert observation.observation_authenticated is True
        assert calls.count(remote_args) == 1

        ledger = reservation._PilotExactTaskRemotePublicationWriteReservationLedger(
            Path(ledger_temp.name)
        )
        fresh_calls, fresh_remote_args, fresh_reader = _observation_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            completed=completed,
            attestation=attestation,
        )
        times = iter(
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
                now_provider=lambda: next(times),
            )

        assert fresh_calls.count(fresh_remote_args) == 1
        assert receipt.reservation_key_sha256 == observation.remote_publication_nonce_sha256
        assert receipt.remote_publication_nonce_sha256 == observation.remote_publication_nonce_sha256
        assert receipt.state_observation_sha256 == observation.sha256
        assert receipt.fresh_state_observation_sha256 != observation.sha256
        assert receipt.target_attestation_sha256 == observation.target_attestation_sha256
        assert receipt.authorization_proof_sha256 == observation.authorization_proof_sha256
        assert receipt.local_commit_publication_requirements_sha256 == requirements.sha256
        assert receipt.local_commit_write_transaction_sha256 == completed.sha256
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.destination_ref == observation.destination_ref
        assert receipt.expected_old_remote_sha == "0" * 40
        assert receipt.supplied_observed_at_utc == "2026-09-15T06:21:00Z"
        assert receipt.fresh_observed_at_utc == "2026-09-15T06:21:30Z"
        assert receipt.reserved_at_utc == "2026-09-15T06:21:40Z"
        assert receipt.reservation_authenticated is True

        for field in (
            "host_replay_guard_committed",
            "fresh_remote_state_revalidated",
            "remote_destination_ref_absent",
            "create_only_remote_ref_required",
            "remote_publication_authorization_consumed",
            "remote_write_slot_reserved",
            "remote_write_transaction_required",
            "fresh_remote_state_revalidation_before_write_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            assert getattr(receipt, field) is True
        for field in (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(receipt, field) is False

        marker = Path(ledger_temp.name) / f"{receipt.remote_publication_nonce_sha256}.json"
        assert marker.read_bytes() == receipt.canonical_json().encode("utf-8")

        reloaded = reservation.PilotExactTaskRemotePublicationWriteReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.reservation_authenticated is False

        replay_calls, _replay_remote_args, replay_reader = _observation_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            completed=completed,
            attestation=attestation,
        )
        replay_times = iter(
            (
                "2026-09-15T06:21:41Z",
                "2026-09-15T06:21:42Z",
                "2026-09-15T06:21:43Z",
                "2026-09-15T06:21:44Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=replay_reader):
            _reject(
                lambda: reservation._reserve_verified_pilot_exact_task_remote_publication_write(
                    state_observation=observation,
                    ledger=ledger,
                    now_provider=lambda: next(replay_times),
                )
            )
        assert replay_calls

        _reject(
            lambda: reservation._require_reservation_window(
                observation,
                at_utc="2026-09-15T06:23:00Z",
            )
        )

        for field in (
            "host_replay_guard_committed",
            "fresh_remote_state_revalidated",
            "remote_destination_ref_absent",
            "create_only_remote_ref_required",
            "remote_publication_authorization_consumed",
            "remote_write_slot_reserved",
            "remote_write_transaction_required",
            "fresh_remote_state_revalidation_before_write_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            changed = receipt.to_dict()
            changed[field] = False
            _reject(
                lambda changed=changed: reservation.PilotExactTaskRemotePublicationWriteReservationReceipt.from_mapping(
                    changed
                )
            )
        for field in (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            changed = receipt.to_dict()
            changed[field] = True
            _reject(
                lambda changed=changed: reservation.PilotExactTaskRemotePublicationWriteReservationReceipt.from_mapping(
                    changed
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["remote_publication_authorization_consumed"]["const"] is True
        assert schema["properties"]["remote_write_slot_reserved"]["const"] is True
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            reservation.reserve_pilot_exact_task_remote_publication_write
        ).parameters
        assert tuple(public_parameters) == ("state_observation",)

        source = inspect.getsource(reservation)
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("push",' not in source
        assert '("fetch",' not in source
        assert '("update-ref",' not in source
        assert "create_pull_request" not in source
        assert "merge_pull_request" not in source
    finally:
        ledger_temp.cleanup()
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        local_reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
