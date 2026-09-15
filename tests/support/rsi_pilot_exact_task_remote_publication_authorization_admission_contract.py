"""Adversarial contract for ADR-DC-052 remote-publication authorization admission."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_authorization as authorization  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_authorization_admission as admission  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_head_observation as observation  # noqa: E402
from rsi_pilot_exact_task_remote_publication_human_authorization_contract import (  # noqa: E402
    ISSUER,
    _authority,
    _live_observation,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-authorization-admission-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-052 unexpectedly admitted unsafe remote authority")


def _proof():
    values = _live_observation()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
        object_ledger_temp,
        ref_ledger_temp,
        ref_receipt,
        identity,
        task,
        fixture,
        base_reader,
        requirements,
        remote_observation,
    ) = values
    nonce = __import__("hashlib").sha256(
        b"adr-dc-052-remote-publication-nonce"
    ).hexdigest()
    claim = authorization.build_pilot_exact_task_remote_publication_authorization(
        remote_head_observation=remote_observation,
        authorization_id="remote-publication-authorization-052",
        remote_publication_authorizer_actor_id=ISSUER,
        authorized_at_utc="2026-09-15T05:35:00Z",
        expires_at_utc="2026-09-15T05:42:00Z",
        remote_publication_nonce_sha256=nonce,
        notes=("reviewed exact remote branch publication for admission",),
    )
    signature, verifier = _authority(claim)
    supplied = authorization._verify_pilot_exact_task_remote_publication_authorization(
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T05:36:00Z",
    )
    fresh = authorization._verify_pilot_exact_task_remote_publication_authorization(
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T05:36:10Z",
    )
    return (*values, claim, signature, supplied, fresh)


def run_contract() -> None:
    if os.name == "nt":
        return

    values = _proof()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
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
    ledger_temp = tempfile.TemporaryDirectory(
        prefix="rsi-remote-publication-admission-"
    )
    try:
        ledger = admission._PilotExactTaskRemotePublicationAuthorizationAdmissionLedger(
            Path(ledger_temp.name)
        )
        times = iter(("2026-09-15T05:36:11Z", "2026-09-15T05:36:12Z"))
        receipt = (
            admission._admit_verified_pilot_exact_task_remote_publication_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                remote_head_observation=remote_observation,
                ledger=ledger,
                now_provider=lambda: next(times),
            )
        )

        assert receipt.admission_authenticated is True
        assert receipt.admission_key_sha256 == supplied.remote_publication_nonce_sha256
        assert receipt.authorization_proof_sha256 == supplied.sha256
        assert receipt.authorization_sha256 == claim.sha256
        assert receipt.authorization_signature_sha256 == signature.sha256
        assert receipt.remote_head_observation_sha256 == remote_observation.sha256
        assert receipt.observation_key_sha256 == remote_observation.observation_key_sha256
        assert receipt.requirements_sha256 == requirements.sha256
        assert receipt.requirements_key_sha256 == requirements.requirements_key_sha256
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.local_commit_sha == identity.predicted_commit_sha
        assert receipt.destination_ref == requirements.destination_ref
        assert receipt.remote_head_present is True
        assert receipt.remote_head_sha == task.base_sha
        assert receipt.publication_mode == remote_observation.publication_mode
        assert receipt.human_remote_publication_authorization_verified is True
        assert receipt.remote_publication_authorization_admitted is True
        assert receipt.remote_publication_authorization_consumed is False
        assert receipt.fresh_remote_head_revalidation_before_push_required is True
        assert receipt.credential_material_present is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = (
            admission.PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.admission_authenticated is False

        # Exact same one-shot nonce can never obtain a second host slot.
        _reject(
            lambda: admission._admit_verified_pilot_exact_task_remote_publication_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                remote_head_observation=remote_observation,
                ledger=ledger,
                now_provider=lambda: "2026-09-15T05:36:13Z",
            )
        )

        reloaded_observation = observation.PilotExactTaskRemoteHeadObservation.from_mapping(
            remote_observation.to_dict()
        )
        assert reloaded_observation.observation_authenticated is False
        other_ledger_temp = tempfile.TemporaryDirectory(
            prefix="rsi-remote-publication-admission-reloaded-"
        )
        try:
            other_ledger = (
                admission._PilotExactTaskRemotePublicationAuthorizationAdmissionLedger(
                    Path(other_ledger_temp.name)
                )
            )
            _reject(
                lambda: admission._admit_verified_pilot_exact_task_remote_publication_authorization(
                    supplied_proof=supplied,
                    fresh_proof=fresh,
                    remote_head_observation=reloaded_observation,
                    ledger=other_ledger,
                    now_provider=lambda: "2026-09-15T05:36:14Z",
                )
            )
        finally:
            other_ledger_temp.cleanup()

        for field, value in (
            ("host_replay_guard_committed", False),
            ("human_remote_publication_authorization_verified", False),
            ("remote_publication_authorization_admitted", False),
            ("remote_publication_authorization_consumed", True),
            ("exact_live_remote_observation_bound", False),
            ("fresh_authorization_reverified", False),
            ("fresh_remote_head_revalidation_before_push_required", False),
            ("credential_material_present", True),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: admission.PilotExactTaskRemotePublicationAuthorizationAdmissionReceipt.from_mapping(
                    {**receipt.to_dict(), field: value}
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["remote_publication_authorization_admitted"]["const"] is True
        assert schema["properties"]["push_authorized"]["const"] is False

        public_api = inspect.signature(
            admission.admit_pilot_exact_task_remote_publication_authorization
        ).parameters
        assert tuple(public_api) == (
            "authorization_proof",
            "authorization_signature",
            "remote_head_observation",
        )
        source = inspect.getsource(admission)
        assert "Ed25519PrivateKey" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("push",' not in source
        assert '"ls-remote"' not in source
        assert '"fetch"' not in source
    finally:
        ledger_temp.cleanup()
        ref_ledger_temp.cleanup()
        object_ledger_temp.cleanup()
        consume_temp.cleanup()
        local_admission_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
