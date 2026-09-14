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

        public_sig = inspect.signature(consume.consume_pilot_start_authorization)
        assert "ledger_root" not in public_sig.parameters
        assert "now_provider" not in public_sig.parameters
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
