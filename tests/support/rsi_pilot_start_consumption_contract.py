"""Adversarial contract for ADR-DC-025 replay-safe pilot-start consumption."""
from __future__ import annotations

import inspect
import json
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

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
import kaliv_dev_control.improvement_pilot_runtime_preflight_attestation as attestation  # noqa: E402
import kaliv_dev_control.improvement_pilot_start_authorization as start_auth  # noqa: E402
import kaliv_dev_control.improvement_pilot_start_consumption as consume  # noqa: E402
import kaliv_dev_control._improvement_pilot_start_consumption_production_boundary as production  # noqa: E402
from rsi_pilot_runtime_preflight_attestation_proof_contract import (  # noqa: E402
    _authority as _preflight_authority,
    _claim as _preflight_claim,
)
from rsi_pilot_start_authorization_contract import _authority as _start_authority  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-start-consumption-receipt-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-025 unexpectedly accepted invalid input")


def _chain():
    preflight_claim = _preflight_claim(all_green=True)
    preflight_verifier, preflight_signature = _preflight_authority(preflight_claim)
    preflight = attestation._verify_pilot_runtime_preflight_attestation(
        attestation=preflight_claim,
        signature=preflight_signature,
        verifier=preflight_verifier,
        now_provider=lambda: "2026-09-14T08:24:00Z",
    )
    authorization = start_auth.build_pilot_start_authorization(
        preflight_proof=preflight,
        authorization_id="pilot-start-consume-025",
        start_authorizer_actor_id="anders",
        authorized_at_utc="2026-09-14T08:25:00Z",
        expires_at_utc="2026-09-14T08:35:00Z",
        start_nonce_sha256="5" * 64,
        notes=("One local consume only.",),
    )
    verifier, authorization_signature = _start_authority(authorization)
    supplied = start_auth._verify_pilot_start_authorization(
        preflight_proof=preflight,
        authorization=authorization,
        signature=authorization_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:26:00Z",
    )
    fresh = start_auth._verify_pilot_start_authorization(
        preflight_proof=preflight,
        authorization=authorization,
        signature=authorization_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-14T08:27:00Z",
    )
    return supplied, fresh, preflight_signature, authorization_signature


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    supplied, fresh, preflight_signature, authorization_signature = _chain()

    with tempfile.TemporaryDirectory(prefix="rsi-pilot-consume-") as raw:
        root = Path(raw).resolve()
        ledger = consume._PilotStartConsumptionLedger(root)
        receipt = consume._consume_verified_pilot_start_authorization(
            supplied_proof=supplied,
            fresh_proof=fresh,
            preflight_signature_sha256=preflight_signature.sha256,
            ledger=ledger,
            now_provider=lambda: "2026-09-14T08:28:00Z",
        )
        assert receipt.schema == consume.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
        assert receipt.authority == consume.PILOT_START_CONSUMPTION_AUTHORITY
        assert receipt.authorization_proof == supplied
        assert receipt.authorization_proof_sha256 == supplied.sha256
        assert receipt.fresh_authorization_proof_sha256 == fresh.sha256
        assert receipt.authorization_sha256 == supplied.authorization_sha256
        assert receipt.authorization_signature_sha256 == authorization_signature.sha256
        assert receipt.preflight_signature_sha256 == preflight_signature.sha256
        assert receipt.start_nonce_sha256 == supplied.start_nonce_sha256
        assert receipt.host_replay_guard_committed is True
        assert receipt.global_replay_safe is False
        assert receipt.one_shot_start_required is True
        assert receipt.start_consumed is True
        assert receipt.start_receipt_issued is True
        assert receipt.pilot_start_authorized is True
        assert receipt.task_execution_authorized is False
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
        assert receipt.transaction_authenticated is True

        reloaded = consume.PilotStartConsumptionReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.transaction_authenticated is False

        _reject(
            lambda: consume._consume_verified_pilot_start_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                preflight_signature_sha256=preflight_signature.sha256,
                ledger=ledger,
                now_provider=lambda: "2026-09-14T08:29:00Z",
            )
        )

    # Structurally valid proof-shaped data cannot substitute for fresh proof identity.
    forged = replace(supplied, signature_sha256="f" * 64)
    _reject(lambda: consume.require_fresh_proof_identity(forged, fresh))

    # Stale before reservation creates no durable replay marker.
    with tempfile.TemporaryDirectory(prefix="rsi-pilot-consume-stale-") as raw:
        root = Path(raw).resolve()
        ledger = consume._PilotStartConsumptionLedger(root)
        _reject(
            lambda: consume._consume_verified_pilot_start_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                preflight_signature_sha256=preflight_signature.sha256,
                ledger=ledger,
                now_provider=lambda: "2026-09-14T08:36:00Z",
            )
        )
        assert tuple(root.iterdir()) == ()

    # Expiry after the irreversible lock fails closed and leaves recovery state.
    with tempfile.TemporaryDirectory(prefix="rsi-pilot-consume-race-") as raw:
        root = Path(raw).resolve()
        ledger = consume._PilotStartConsumptionLedger(root)
        times = iter(("2026-09-14T08:34:59Z", "2026-09-14T08:35:01Z"))
        _reject(
            lambda: consume._consume_verified_pilot_start_authorization(
                supplied_proof=supplied,
                fresh_proof=fresh,
                preflight_signature_sha256=preflight_signature.sha256,
                ledger=ledger,
                now_provider=lambda: next(times),
            )
        )
        names = sorted(path.name for path in root.iterdir())
        assert names == [f".{supplied.start_nonce_sha256}.lock"]

    # Serialized receipt data cannot escalate the consume-only authority boundary.
    with tempfile.TemporaryDirectory(prefix="rsi-pilot-consume-fields-") as raw:
        ledger = consume._PilotStartConsumptionLedger(Path(raw).resolve())
        receipt = consume._consume_verified_pilot_start_authorization(
            supplied_proof=supplied,
            fresh_proof=fresh,
            preflight_signature_sha256=preflight_signature.sha256,
            ledger=ledger,
            now_provider=lambda: "2026-09-14T08:28:00Z",
        )
        for field in (
            "task_execution_authorized",
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
        for field in (
            "host_replay_guard_committed",
            "one_shot_start_required",
            "start_consumed",
            "start_receipt_issued",
            "pilot_start_authorized",
        ):
            _reject(
                lambda field=field: consume.PilotStartConsumptionReceipt.from_mapping(
                    {**receipt.to_dict(), field: False}
                )
            )

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]
    assert set(props) == set(receipt.to_dict())
    assert props["schema"]["const"] == consume.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA
    assert props["ledger_scope"]["const"] == consume.PILOT_START_CONSUMPTION_LEDGER_SCOPE
    assert props["start_consumed"]["const"] is True
    assert props["start_receipt_issued"]["const"] is True
    assert props["task_execution_authorized"]["const"] is False
    assert props["product_pilot_started"]["const"] is False
    assert props["local_commit_authorized"]["const"] is False
    assert props["production_activation_authorized"]["const"] is False
    assert props["authority"]["const"] == consume.PILOT_START_CONSUMPTION_AUTHORITY

    # Production facade must fresh-verify upstream and must not accept caller-selected state.
    with tempfile.TemporaryDirectory(prefix="rsi-pilot-consume-prod-") as raw:
        root = Path(raw).resolve()
        original_verify = production._start_auth.verify_pilot_start_authorization
        original_root = production._canonical_ledger_root
        calls = []

        def fake_verify(**kwargs):
            calls.append(kwargs)
            assert kwargs["preflight_proof"] == supplied.authorization.preflight_proof
            assert kwargs["authorization"] == supplied.authorization
            assert kwargs["signature"] == authorization_signature
            assert kwargs["preflight_signature"] == preflight_signature
            return fresh

        try:
            production._start_auth.verify_pilot_start_authorization = fake_verify
            production._canonical_ledger_root = lambda: root
            prod_receipt = consume.consume_pilot_start_authorization(
                authorization_proof=supplied,
                preflight_signature=preflight_signature,
                authorization_signature=authorization_signature,
            )
            assert len(calls) == 1
            assert prod_receipt.start_consumed is True
            assert prod_receipt.task_execution_authorized is False
            _reject(
                lambda: consume.consume_pilot_start_authorization(
                    authorization_proof=supplied,
                    preflight_signature=preflight_signature,
                    authorization_signature=authorization_signature,
                )
            )
            _reject(
                lambda: consume.consume_pilot_start_authorization(
                    authorization_proof=supplied,
                    preflight_signature=preflight_signature,
                    authorization_signature=authorization_signature,
                    ledger_root=root,
                )
            )
        finally:
            production._start_auth.verify_pilot_start_authorization = original_verify
            production._canonical_ledger_root = original_root

    root_source = inspect.getsource(kaliv_dev_control)
    assert "improvement_pilot_start_consumption" not in root_source
    impl_source = inspect.getsource(consume._implementation).lower()
    for forbidden in (
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "git push",
        "merge_pull_request",
    ):
        assert forbidden not in impl_source, forbidden


if __name__ == "__main__":
    run_contract()
