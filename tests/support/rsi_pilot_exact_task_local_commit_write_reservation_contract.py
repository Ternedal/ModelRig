"""Adversarial contract for ADR-DC-045 exact local-write reservation."""
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

from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_local_commit_write_reservation_impl as reservation_impl,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_authorization as auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_object_identity as object_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_requirements as write_requirements,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_reservation as reservation,
)
from rsi_pilot_exact_task_local_commit_authorization_contract import (  # noqa: E402
    _human_authority,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
    _live_plan,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-write-reservation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (reservation.PilotExactTaskLocalCommitWriteReservationError, ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-045 unexpectedly accepted invalid authority")


def _authorized_material():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        _evaluation,
        _execution_receipt,
        _execution_plan,
        local_plan,
        task,
        fixture,
        staged,
    ) = _live_plan()
    blob_sha = "1" * 40
    index_payload = f"100644 {blob_sha} 0\tVERSION\0".encode("ascii")
    _calls, reader = _identity_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        identity = (
            object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                local_commit_plan=local_plan,
                now_provider=lambda: "2026-09-15T06:10:00Z",
            )
        )
    requirements = (
        write_requirements.materialize_pilot_exact_task_local_commit_write_requirements(
            identity
        )
    )
    claim = auth.build_pilot_exact_task_local_commit_authorization(
        local_commit_write_requirements=requirements,
        authorization_id="exact-local-commit-authorization-045-source",
        local_commit_authorizer_actor_id=requirements.execution_authorizer_actor_id,
        authorized_at_utc="2026-09-15T06:11:00Z",
        expires_at_utc="2026-09-15T06:21:00Z",
        local_write_nonce_sha256=(
            __import__("hashlib").sha256(b"local-write-nonce-045").hexdigest()
        ),
        notes=("one exact local commit write only",),
    )
    verifier, signature = _human_authority(claim)
    proof = auth._verify_pilot_exact_task_local_commit_authorization(
        local_commit_write_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:12:00Z",
    )
    fresh = auth._verify_pilot_exact_task_local_commit_authorization(
        local_commit_write_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:12:30Z",
    )
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        identity,
        requirements,
        task,
        fixture,
        staged,
        index_payload,
        claim,
        verifier,
        signature,
        proof,
        fresh,
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
        identity,
        requirements,
        task,
        fixture,
        staged,
        index_payload,
        claim,
        verifier,
        signature,
        proof,
        fresh,
    ) = _authorized_material()
    ledger_temp = TemporaryDirectory(prefix="rsi-local-write-reservation-045-")
    burn_temp = TemporaryDirectory(prefix="rsi-local-write-reservation-burn-045-")
    try:
        reservation.require_fresh_authorization_proof_identity(proof, fresh)
        ledger = reservation._PilotExactTaskLocalCommitWriteReservationLedger(
            Path(ledger_temp.name)
        )
        calls, reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        times = iter(("2026-09-15T06:13:00Z", "2026-09-15T06:14:00Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = reservation._reserve_verified_exact_task_local_commit_write(
                authorization_proof=fresh,
                local_commit_object_identity=identity,
                ledger=ledger,
                now_provider=lambda: next(times),
            )
        assert len(calls) == 14
        assert receipt.reservation_key_sha256 == proof.local_write_nonce_sha256
        assert receipt.authorization_proof_sha256 == fresh.sha256
        assert receipt.authorization_sha256 == claim.sha256
        assert receipt.authorization_signature_sha256 == signature.sha256
        assert receipt.local_commit_write_requirements_sha256 == requirements.sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.execution_nonce_sha256 == proof.execution_nonce_sha256
        assert receipt.local_write_nonce_sha256 == proof.local_write_nonce_sha256
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.fresh_revalidated_at_utc == "2026-09-15T06:13:00Z"
        assert receipt.reserved_at_utc == "2026-09-15T06:14:00Z"
        assert receipt.host_replay_guard_committed is True
        assert receipt.authorization_proof_verified is True
        assert receipt.fresh_live_identity_revalidated is True
        assert receipt.fresh_workspace_snapshot_matched is True
        assert receipt.index_manifest_revalidated is True
        assert receipt.root_tree_revalidated is True
        assert receipt.commit_payload_revalidated is True
        assert receipt.local_write_reserved is True
        assert receipt.one_shot_local_write_required is True
        assert receipt.local_write_authorization_consumed is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.local_commit_created is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.reservation_authenticated is True

        reloaded = reservation.PilotExactTaskLocalCommitWriteReservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.reservation_authenticated is False

        # Reusing the same signed local-write nonce cannot acquire a second slot.
        replay_calls, replay_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        replay_times = iter(("2026-09-15T06:15:00Z", "2026-09-15T06:16:00Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=replay_reader):
            _reject(
                lambda: reservation._reserve_verified_exact_task_local_commit_write(
                    authorization_proof=fresh,
                    local_commit_object_identity=identity,
                    ledger=ledger,
                    now_provider=lambda: next(replay_times),
                )
            )
        assert replay_calls

        # Drift after durable acquire burns the nonce fail-closed.
        burn_ledger = reservation._PilotExactTaskLocalCommitWriteReservationLedger(
            Path(burn_temp.name)
        )
        drift_calls, drift_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
            drift_after_index=True,
        )
        drift_times = iter(("2026-09-15T06:15:10Z", "2026-09-15T06:15:20Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(
                lambda: reservation._reserve_verified_exact_task_local_commit_write(
                    authorization_proof=fresh,
                    local_commit_object_identity=identity,
                    ledger=burn_ledger,
                    now_provider=lambda: next(drift_times),
                )
            )
        assert drift_calls
        _final, _pending, burn_lock = burn_ledger._paths(fresh.local_write_nonce_sha256)
        assert burn_lock.exists()

        stable_calls, stable_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=stable_reader):
            _reject(
                lambda: reservation._reserve_verified_exact_task_local_commit_write(
                    authorization_proof=fresh,
                    local_commit_object_identity=identity,
                    ledger=burn_ledger,
                    now_provider=lambda: "2026-09-15T06:16:00Z",
                )
            )

        # A distinct valid proof is still not the fresh identity of this proof.
        changed_claim = auth.build_pilot_exact_task_local_commit_authorization(
            local_commit_write_requirements=requirements,
            authorization_id="exact-local-commit-authorization-045-changed",
            local_commit_authorizer_actor_id=requirements.execution_authorizer_actor_id,
            authorized_at_utc="2026-09-15T06:11:00Z",
            expires_at_utc="2026-09-15T06:21:00Z",
            local_write_nonce_sha256=claim.local_write_nonce_sha256,
            notes=("different signed authorization payload",),
        )
        changed_verifier, changed_signature = _human_authority(changed_claim)
        changed_proof = auth._verify_pilot_exact_task_local_commit_authorization(
            local_commit_write_requirements=requirements,
            authorization=changed_claim,
            signature=changed_signature,
            verifier=changed_verifier,
            now_provider=lambda: "2026-09-15T06:12:30Z",
        )
        _reject(
            lambda: reservation.require_fresh_authorization_proof_identity(
                proof,
                changed_proof,
            )
        )

        reloaded_identity = object_identity.PilotExactTaskLocalCommitObjectIdentity.from_mapping(
            identity.to_dict()
        )
        assert reloaded_identity.identity_authenticated is False
        _reject(lambda: reservation._require_live_identity(reloaded_identity))

        for field in (
            "host_replay_guard_committed",
            "authorization_proof_verified",
            "fresh_live_identity_revalidated",
            "fresh_workspace_snapshot_matched",
            "index_manifest_revalidated",
            "root_tree_revalidated",
            "commit_payload_revalidated",
            "local_write_reserved",
            "one_shot_local_write_required",
            "local_write_authorization_consumed",
        ):
            _reject(
                lambda field=field: reservation.PilotExactTaskLocalCommitWriteReservationReceipt.from_mapping(
                    {**receipt.to_dict(), field: False}
                )
            )
        for field in (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
            "integration_ready",
            "product_pilot_started",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: reservation.PilotExactTaskLocalCommitWriteReservationReceipt.from_mapping(
                    {**receipt.to_dict(), field: True}
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["local_write_authorization_consumed"]["const"] is True
        assert props["local_write_reserved"]["const"] is True
        assert props["git_object_write_authorized"]["const"] is False
        assert props["local_ref_update_authorized"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["local_commit_created"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            reservation.reserve_pilot_exact_task_local_commit_write
        ).parameters
        assert tuple(public_parameters) == (
            "authorization_proof",
            "authorization_signature",
            "local_commit_object_identity",
        )

        # Production facade must not accept our caller-owned test verifier/keyring.
        _reject(
            lambda: reservation.reserve_pilot_exact_task_local_commit_write(
                authorization_proof=proof,
                authorization_signature=signature,
                local_commit_object_identity=identity,
            )
        )

        source = inspect.getsource(reservation_impl)
        facade_source = inspect.getsource(reservation)
        for forbidden in (
            "subprocess",
            "shell=True",
            '"write-tree"',
            '"commit-tree"',
            '("commit",',
            '("update-ref",',
            '("push",',
            '("reset",',
            '("clean",',
        ):
            assert forbidden not in source
            assert forbidden not in facade_source
    finally:
        burn_temp.cleanup()
        ledger_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
