"""Adversarial contract for ADR-DC-057 durable PR-mutation reservation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pull_request_mutation_reservation as reservation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pull_request_state_observation as state,
)
from rsi_pilot_exact_task_pull_request_mutation_authorization_contract import (  # noqa: E402
    _material,
)
from rsi_pilot_exact_task_pull_request_state_observation_contract import (  # noqa: E402
    _Transport,
    _proof,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pull-request-mutation-reservation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        reservation.PilotExactTaskPullRequestMutationReservationError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-057 unexpectedly accepted unsafe PR reservation")


def _observation_material():
    material = _material()
    requirements = material[-1]
    _claim_value, _verifier, signature, supplied_proof, fresh_proof = _proof(
        requirements
    )
    transport = _Transport(requirements)
    times = iter(("2026-09-15T06:24:20Z", "2026-09-15T06:24:30Z"))
    supplied = state._observe_verified_pilot_exact_task_pull_request_state(
        authorization_proof=supplied_proof,
        fresh_authorization_proof=fresh_proof,
        transport=transport,
        now_provider=lambda: next(times),
    )
    assert supplied.observation_authenticated is True
    return material, signature, supplied_proof, fresh_proof, supplied


def run_contract() -> None:
    if os.name == "nt":
        return

    material, _signature, supplied_proof, fresh_proof, supplied = (
        _observation_material()
    )
    requirements = material[-1]
    source_material = material[0]
    ledger_temp = TemporaryDirectory(prefix="rsi-pr-mutation-reservation-057-")
    try:
        ledger = reservation._PilotExactTaskPullRequestMutationReservationLedger(
            Path(ledger_temp.name)
        )
        fresh_calls = 0

        def fresh_observer():
            nonlocal fresh_calls
            fresh_calls += 1
            fresh_times = iter(("2026-09-15T06:24:40Z", "2026-09-15T06:24:50Z"))
            return state._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied_proof,
                fresh_authorization_proof=fresh_proof,
                transport=_Transport(requirements),
                now_provider=lambda: next(fresh_times),
            )

        reserve_times = iter(("2026-09-15T06:24:35Z", "2026-09-15T06:24:55Z"))
        receipt = reservation._reserve_verified_pilot_exact_task_pull_request_mutation(
            state_observation=supplied,
            fresh_observer=fresh_observer,
            ledger=ledger,
            now_provider=lambda: next(reserve_times),
        )
        assert fresh_calls == 1
        assert receipt.ledger_root_path_sha256 == ledger.root_sha256
        assert receipt.reservation_key_sha256 == supplied.pr_mutation_nonce_sha256
        assert receipt.state_observation_sha256 == supplied.sha256
        assert receipt.fresh_state_observation_sha256 != supplied.sha256
        assert (
            receipt.pull_request_mutation_authorization_proof_sha256
            == supplied.pull_request_mutation_authorization_proof_sha256
        )
        assert (
            receipt.pull_request_mutation_requirements_sha256
            == supplied.pull_request_mutation_requirements_sha256
        )
        assert (
            receipt.remote_publication_write_transaction_sha256
            == supplied.remote_publication_write_transaction_sha256
        )
        assert receipt.remote_publication_nonce_sha256 == supplied.remote_publication_nonce_sha256
        assert receipt.pr_mutation_nonce_sha256 == supplied.pr_mutation_nonce_sha256
        assert receipt.predicted_commit_sha == supplied.predicted_commit_sha
        assert receipt.repository == "Ternedal/ModelRig"
        assert receipt.api_host == "api.github.com"
        assert receipt.base_ref == "main"
        assert receipt.head_owner == "Ternedal"
        assert receipt.head_ref == supplied.head_ref
        assert receipt.head_branch == supplied.head_branch
        assert receipt.query_sha256 == supplied.query_sha256
        assert receipt.supplied_observed_at_utc == "2026-09-15T06:24:30Z"
        assert receipt.fresh_observed_at_utc == "2026-09-15T06:24:50Z"
        assert receipt.reserved_at_utc == "2026-09-15T06:24:55Z"
        assert receipt.reservation_authenticated is True

        for field in (
            "host_replay_guard_committed",
            "fresh_pr_state_revalidated",
            "remote_head_sha_matches_exact_candidate",
            "existing_open_pull_request_absent",
            "pr_mutation_authorization_consumed",
            "pr_mutation_slot_reserved",
            "pr_mutation_transaction_required",
            "fresh_pr_state_revalidation_before_write_required",
            "draft_pull_request_required",
            "create_only_pull_request_required",
            "host_pinned_pr_credential_capability_required",
            "merge_separately_authorized_required",
        ):
            assert getattr(receipt, field) is True
        for field in (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_update_authorized",
            "ready_for_review_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(receipt, field) is False

        marker = Path(ledger_temp.name) / f"{receipt.pr_mutation_nonce_sha256}.json"
        assert marker.is_file()
        payload = marker.read_bytes()
        assert payload == receipt.canonical_json().encode("utf-8")
        assert json.loads(payload.decode("utf-8")) == receipt.to_dict()

        reloaded = reservation.PilotExactTaskPullRequestMutationReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.reservation_authenticated is False

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["pr_mutation_authorization_consumed"]["const"] is True
        assert schema["properties"]["pr_mutation_slot_reserved"]["const"] is True
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["pull_request_create_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        # Permanent create-once replay guard: a second reservation of the same
        # human-signed PR mutation nonce must collide even with a fresh safe read.
        replay_times = iter(("2026-09-15T06:24:36Z", "2026-09-15T06:24:56Z"))
        _reject(
            lambda: reservation._reserve_verified_pilot_exact_task_pull_request_mutation(
                state_observation=supplied,
                fresh_observer=fresh_observer,
                ledger=ledger,
                now_provider=lambda: next(replay_times),
            )
        )

        # An observation older than one minute cannot be converted into a slot.
        old_ledger_temp = TemporaryDirectory(prefix="rsi-pr-old-057-")
        try:
            old_ledger = reservation._PilotExactTaskPullRequestMutationReservationLedger(
                Path(old_ledger_temp.name)
            )
            _reject(
                lambda: reservation._reserve_verified_pilot_exact_task_pull_request_mutation(
                    state_observation=supplied,
                    fresh_observer=fresh_observer,
                    ledger=old_ledger,
                    now_provider=iter(("2026-09-15T06:25:31Z", "2026-09-15T06:25:32Z")).__next__,
                )
            )
            assert not list(Path(old_ledger_temp.name).iterdir())
        finally:
            old_ledger_temp.cleanup()

        # Fresh PR state must still be absent; an existing PR makes reservation fail.
        def unsafe_fresh_observer():
            fresh_times = iter(("2026-09-15T06:24:40Z", "2026-09-15T06:24:50Z"))
            return state._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied_proof,
                fresh_authorization_proof=fresh_proof,
                transport=_Transport(
                    requirements,
                    pulls=[{"number": 999, "state": "open"}],
                ),
                now_provider=lambda: next(fresh_times),
            )

        other_ledger_temp = TemporaryDirectory(prefix="rsi-pr-unsafe-057-")
        try:
            other_ledger = reservation._PilotExactTaskPullRequestMutationReservationLedger(
                Path(other_ledger_temp.name)
            )
            _reject(
                lambda: reservation._reserve_verified_pilot_exact_task_pull_request_mutation(
                    state_observation=supplied,
                    fresh_observer=unsafe_fresh_observer,
                    ledger=other_ledger,
                    now_provider=iter(("2026-09-15T06:24:35Z", "2026-09-15T06:24:55Z")).__next__,
                )
            )
            assert not list(Path(other_ledger_temp.name).iterdir())
        finally:
            other_ledger_temp.cleanup()

        changed = dict(receipt.to_dict())
        changed["reservation_key_sha256"] = "a" * 64
        _reject(
            lambda: reservation.PilotExactTaskPullRequestMutationReservationReceipt.from_mapping(
                changed
            )
        )
        changed = dict(receipt.to_dict())
        changed["pr_mutation_authorized"] = True
        _reject(
            lambda: reservation.PilotExactTaskPullRequestMutationReservationReceipt.from_mapping(
                changed
            )
        )
        changed = dict(receipt.to_dict())
        changed["pull_request_create_authorized"] = True
        _reject(
            lambda: reservation.PilotExactTaskPullRequestMutationReservationReceipt.from_mapping(
                changed
            )
        )

        # Live authority is tied to the exact durable marker bytes.
        marker.write_bytes(b"tampered\n")
        assert receipt.reservation_authenticated is False

        public_parameters = inspect.signature(
            reservation.reserve_pilot_exact_task_pull_request_mutation
        ).parameters
        assert tuple(public_parameters) == (
            "state_observation",
            "authorization_signature",
        )

        source = inspect.getsource(reservation)
        for forbidden in (
            "create_pull_request",
            "update_pull_request",
            "merge_pull_request",
            'method="POST"',
            'method="PATCH"',
            'method="PUT"',
            'method="DELETE"',
        ):
            assert forbidden not in source
    finally:
        ledger_temp.cleanup()
        material[2].cleanup()
        material[1].cleanup()
        source_material[6].cleanup()
        source_material[5].cleanup()
        source_material[4].cleanup()
        source_material[3].cleanup()
        source_material[2].cleanup()
        source_material[1].cleanup()
        source_material[0].cleanup()


if __name__ == "__main__":
    run_contract()
