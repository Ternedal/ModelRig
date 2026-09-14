"""Adversarial contract for ADR-DC-025 one-shot pilot-start consumption."""
from __future__ import annotations

import inspect
import json
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_start_consumption_production_boundary as production_boundary,
)
from kaliv_dev_control import catalog  # noqa: E402
from kaliv_dev_control.durable_publication import create_once_file  # noqa: E402
import kaliv_dev_control.improvement_pilot_start_authorization as start_auth  # noqa: E402
import kaliv_dev_control.improvement_pilot_start_consumption as consume  # noqa: E402
from rsi_pilot_start_authorization_contract import (  # noqa: E402
    _authority,
    _preflight_proof,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-start-consumption-receipt-v1.schema.json"
)


def _proof(*, nonce: str = "d" * 64):
    preflight = _preflight_proof()
    authorization = start_auth.build_pilot_start_authorization(
        preflight_proof=preflight,
        authorization_id="pilot-start-025",
        start_authorizer_actor_id="anders",
        authorized_at_utc="2026-09-14T08:25:00Z",
        expires_at_utc="2026-09-14T08:35:00Z",
        start_nonce_sha256=nonce,
        notes=("One host-local consume only.",),
    )
    verifier, signature = _authority(authorization)
    proof = start_auth._verify_pilot_start_authorization(
        preflight_proof=preflight,
        authorization=authorization,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:26:00Z",
    )
    return proof, signature


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-025 unexpectedly accepted invalid input")


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    temp = Path(tempfile.mkdtemp(prefix="pilot-start-consume-"))
    try:
        ledger_root = temp / "ledger"
        ledger_root.mkdir()
        ledger = consume.PilotStartConsumptionLedger(root=ledger_root)
        _reject(
            lambda: consume.PilotStartConsumptionLedger(
                root=ledger_root,
                ledger_id="alternate-pilot-start-ledger",
            )
        )
        proof, signature = _proof()

        receipt = consume._consume_pilot_start_authorization(
            proof=proof,
            ledger=ledger,
            now_provider=lambda: "2026-09-14T08:27:00Z",
        )
        assert receipt.schema == consume.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
        assert receipt.authority == consume.PILOT_START_CONSUMPTION_AUTHORITY
        assert receipt.authorization_proof == proof
        assert receipt.authorization_proof_sha256 == proof.sha256
        assert receipt.authorization_sha256 == proof.authorization_sha256
        assert receipt.authorization_signature_sha256 == proof.signature_sha256
        assert receipt.start_nonce_sha256 == proof.start_nonce_sha256
        assert receipt.ledger_id == consume.PILOT_START_CONSUMPTION_LEDGER_ID
        assert receipt.host_local_replay_guard_committed is True
        assert receipt.global_replay_safe is False
        assert receipt.one_shot_start_required is True
        assert receipt.start_consumed is True
        assert receipt.pilot_start_authorized is True
        assert receipt.pilot_execution_authorized is False
        assert receipt.integration_ready is False
        assert receipt.product_pilot_started is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert consume.PilotStartConsumptionReceipt.from_mapping(receipt.to_dict()) == receipt
        assert ledger.load(proof.start_nonce_sha256) == receipt

        # Same nonce/proof is one-shot even if every caller byte is identical.
        _reject(
            lambda: consume._consume_pilot_start_authorization(
                proof=proof,
                ledger=ledger,
                now_provider=lambda: "2026-09-14T08:28:00Z",
            )
        )

        # Expiry is checked again at consumption time, not only at ADR-024 verify time.
        expired_root = temp / "expired"
        expired_root.mkdir()
        expired_ledger = consume.PilotStartConsumptionLedger(root=expired_root)
        expired_proof, _ = _proof(nonce="e" * 64)
        _reject(
            lambda: consume._consume_pilot_start_authorization(
                proof=expired_proof,
                ledger=expired_ledger,
                now_provider=lambda: "2026-09-14T08:36:00Z",
            )
        )
        assert not any(expired_root.iterdir())

        # A durable/uncertain reservation is never reusable even without final receipt.
        uncertain_root = temp / "uncertain"
        uncertain_root.mkdir()
        uncertain_ledger = consume.PilotStartConsumptionLedger(root=uncertain_root)
        uncertain_proof, _ = _proof(nonce="f" * 64)
        lock = uncertain_root / f".{uncertain_proof.start_nonce_sha256}.lock"
        create_once_file(lock, b"uncertain-consumed-state")
        _reject(
            lambda: consume._consume_pilot_start_authorization(
                proof=uncertain_proof,
                ledger=uncertain_ledger,
                now_provider=lambda: "2026-09-14T08:27:00Z",
            )
        )
        _reject(lambda: uncertain_ledger.load(uncertain_proof.start_nonce_sha256))

        # Public production facade does not accept caller-selected replay state.
        _reject(
            lambda: consume.consume_pilot_start_authorization(
                proof=proof,
                signature=signature,
                preflight_signature=object(),
                ledger=consume.PilotStartConsumptionLedger(root=expired_root),
            )
        )

        # Production consumption must freshly call ADR-DC-024's host-pinned
        # verifier (which itself re-verifies ADR-DC-023 provenance), forward the
        # detached preflight signature, and only then reach canonical replay state.
        public_sig = inspect.signature(consume.consume_pilot_start_authorization)
        assert public_sig.parameters["preflight_signature"].default is inspect.Parameter.empty
        assert "ledger_root" not in public_sig.parameters
        assert "now_provider" not in public_sig.parameters

        production_root = temp / "production-ledger"
        production_root.mkdir()
        production_proof, production_signature = _proof(nonce="9" * 64)
        preflight_signature_marker = object()
        seen: dict[str, object] = {}
        original_verify = production_boundary.verify_pilot_start_authorization
        original_root = production_boundary._host_controlled_pilot_start_consumption_root
        original_now = consume._implementation._now_utc_seconds
        try:
            def _fresh_verify(*, preflight_proof, authorization, signature, preflight_signature):
                seen["preflight_proof"] = preflight_proof
                seen["authorization"] = authorization
                seen["signature"] = signature
                seen["preflight_signature"] = preflight_signature
                return production_proof

            production_boundary.verify_pilot_start_authorization = _fresh_verify
            production_boundary._host_controlled_pilot_start_consumption_root = (
                lambda: production_root
            )
            consume._implementation._now_utc_seconds = lambda: "2026-09-14T08:27:00Z"

            production_receipt = consume.consume_pilot_start_authorization(
                proof=production_proof,
                signature=production_signature,
                preflight_signature=preflight_signature_marker,
            )
            assert seen["preflight_proof"] == production_proof.authorization.preflight_proof
            assert seen["authorization"] == production_proof.authorization
            assert seen["signature"] == production_signature
            assert seen["preflight_signature"] is preflight_signature_marker
            assert production_receipt.authorization_proof == production_proof
            assert production_receipt.start_consumed is True
            assert production_receipt.pilot_execution_authorized is False

            # Even if a compromised/stubbed fresh verifier returns the presented
            # proof, a different detached ADR-DC-024 signature cannot reach the ledger.
            drift_root = temp / "signature-drift-ledger"
            drift_root.mkdir()
            drift_proof, drift_signature = _proof(nonce="8" * 64)
            production_boundary._host_controlled_pilot_start_consumption_root = (
                lambda: drift_root
            )
            production_boundary.verify_pilot_start_authorization = (
                lambda **_: drift_proof
            )
            _reject(
                lambda: consume.consume_pilot_start_authorization(
                    proof=drift_proof,
                    signature=replace(drift_signature, signature_hex="0" * 128),
                    preflight_signature=preflight_signature_marker,
                )
            )
            assert not any(drift_root.iterdir())

            # Fresh proof metadata must reproduce the presented ADR-DC-024
            # identity before replay state can be mutated. verified_at may change;
            # signer/key/scope/authority identity may not.
            identity_root = temp / "identity-drift-ledger"
            identity_root.mkdir()
            identity_proof, identity_signature = _proof(nonce="7" * 64)
            production_boundary._host_controlled_pilot_start_consumption_root = (
                lambda: identity_root
            )
            production_boundary.verify_pilot_start_authorization = (
                lambda **_: replace(identity_proof, key_id="forged-start-key")
            )
            _reject(
                lambda: consume.consume_pilot_start_authorization(
                    proof=identity_proof,
                    signature=identity_signature,
                    preflight_signature=preflight_signature_marker,
                )
            )
            assert not any(identity_root.iterdir())
        finally:
            production_boundary.verify_pilot_start_authorization = original_verify
            production_boundary._host_controlled_pilot_start_consumption_root = original_root
            consume._implementation._now_utc_seconds = original_now

        # Proof-shaped authority escalation cannot enter the consumption boundary.
        for field in (
            "start_consumed",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: consume._consume_pilot_start_authorization(
                    proof=replace(proof, **{field: True}),
                    ledger=expired_ledger,
                    now_provider=lambda: "2026-09-14T08:27:00Z",
                )
            )

        # Receipt replay may not turn consumption into execution or wider authority.
        for field in (
            "pilot_execution_authorized",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "global_replay_safe",
        ):
            _reject(
                lambda field=field: consume.PilotStartConsumptionReceipt.from_mapping(
                    {**receipt.to_dict(), field: True}
                )
            )
        _reject(
            lambda: consume.PilotStartConsumptionReceipt.from_mapping(
                {**receipt.to_dict(), "start_consumed": False}
            )
        )
        _reject(
            lambda: consume.PilotStartConsumptionReceipt.from_mapping(
                {**receipt.to_dict(), "authorization_proof_sha256": "1" * 64}
            )
        )
        _reject(
            lambda: consume.PilotStartConsumptionReceipt.from_mapping(
                {**receipt.to_dict(), "ledger_id": "alternate-pilot-start-ledger"}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert props["schema"]["const"] == consume.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
        assert props["ledger_id"]["const"] == consume.PILOT_START_CONSUMPTION_LEDGER_ID
        assert props["host_local_replay_guard_committed"]["const"] is True
        assert props["global_replay_safe"]["const"] is False
        assert props["start_consumed"]["const"] is True
        assert props["pilot_start_authorized"]["const"] is True
        assert props["pilot_execution_authorized"]["const"] is False
        assert props["product_pilot_started"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False
        assert props["authority"]["const"] == consume.PILOT_START_CONSUMPTION_AUTHORITY

        source = inspect.getsource(consume._implementation).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
        ):
            assert forbidden not in source, forbidden
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    run_contract()
