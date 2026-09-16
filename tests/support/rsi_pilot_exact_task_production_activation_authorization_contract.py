"""Adversarial contract for ADR-DC-092 production-activation authorization."""
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

from kaliv_dev_control import improvement_pilot_exact_task_production_activation_authorization as activation_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_production_activation_readiness as readiness  # noqa: E402
import rsi_pilot_exact_task_production_activation_readiness_contract as readiness_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_authorization_contract as deploy_auth_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-production-activation-authorization-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_production_activation_authorization.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-092 unexpectedly accepted unsafe production activation authority")


def _ready_from_normal():
    fixture = readiness_contract._normal_source()
    source = fixture[-1]
    receipt = readiness_contract._evaluate(source, readiness_contract._policy(source))
    assert receipt.evaluation_authenticated is True
    assert receipt.production_activation_ready is True
    return fixture, receipt


def _config(receipt, **overrides):
    values = dict(
        repository=receipt.repository,
        repository_id=receipt.repository_id,
        promotion_gate_sha256="a" * 64,
        promotion_controller_sha256="b" * 64,
    )
    values.update(overrides)
    return activation_auth.PilotExactTaskProductionActivationAuthorizationConfig(**values)


def _payload(receipt, config, *, requested="2026-09-15T09:52:01Z", expires="2026-09-15T09:57:01Z"):
    return activation_auth._build_authorization_payload(
        production_activation_readiness=receipt,
        activation_config=config,
        requested_at_utc=requested,
        expires_at_utc=expires,
        operator_actor_id="deploy.operator",
        operator_system_id="offline-deploy-operator",
        operator_key_id="deploy-op-1",
        reviewer_actor_id="deploy.reviewer",
        reviewer_system_id="offline-deploy-reviewer",
        reviewer_key_id="deploy-review-1",
    )


def _dual(payload, *, same_key=False, signed_at="2026-09-15T09:52:02Z"):
    return deploy_auth_contract._dual_authority(
        payload,
        same_key=same_key,
        signed_at=signed_at,
    )


def _ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, activation_auth._PilotExactTaskProductionActivationAuthorizationLedger(root)


def _authorize(receipt, config, payload, verifier, op_sig, review_sig, ledger, *, now_provider=None):
    if now_provider is None:
        now_provider = lambda: "2026-09-15T09:52:10Z"
    return activation_auth._authorize_verified_pilot_exact_task_production_activation(
        production_activation_readiness=receipt,
        activation_config=config,
        authorization_payload=payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        ledger=ledger,
        now_provider=now_provider,
    )


def _assert_authority(receipt) -> None:
    assert receipt.authorization_authenticated is True
    assert receipt.host_production_activation_guard_committed is True
    assert receipt.production_activation_readiness_authenticated is True
    assert receipt.production_activation_candidate_bound is True
    assert receipt.production_activation_authorization_config_host_pinned is True
    assert receipt.machine_gate_identity_host_pinned is True
    assert receipt.dual_external_ed25519_authorized is True
    assert receipt.promotion_gate_execution_authorized is True
    assert receipt.production_env_mutation_authorized is True
    assert receipt.appliance_restart_authorized is True
    assert receipt.production_receipt_write_authorized is True
    assert receipt.production_activation_authorized is True
    assert receipt.remote_write_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.release_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.nonce_reusable is False


def run_contract() -> None:
    if os.name == "nt":
        return

    normal, ready = _ready_from_normal()
    temp, ledger = _ledger("rsi-production-activation-auth-")
    try:
        config = _config(ready)
        payload = _payload(ready, config)
        verifier, op_sig, review_sig = _dual(payload)
        receipt = _authorize(ready, config, payload, verifier, op_sig, review_sig, ledger)
        _assert_authority(receipt)
        assert receipt.production_activation_key_sha256 == ready.production_activation_candidate_sha256
        assert receipt.production_activation_readiness_sha256 == ready.sha256
        assert receipt.production_activation_readiness_policy_sha256 == ready.production_activation_readiness_policy_sha256
        assert receipt.production_activation_candidate_sha256 == ready.production_activation_candidate_sha256
        assert receipt.staging_runtime_build_identity_sha256 == ready.staging_runtime_build_identity_sha256
        assert receipt.success_deployment_status_intent_sha256 == ready.success_deployment_status_intent_sha256
        assert receipt.candidate_branch == activation_auth.CANDIDATE_BRANCH
        assert receipt.promotion_branch == activation_auth.PROMOTION_BRANCH
        assert receipt.promotion_gate_path == activation_auth.PROMOTION_GATE_PATH
        assert receipt.promotion_controller_path == activation_auth.PROMOTION_CONTROLLER_PATH
        assert receipt.required_switches_sha256 == activation_auth.REQUIRED_SWITCHES_SHA256

        serialized = activation_auth.PilotExactTaskProductionActivationAuthorizationReceipt.from_mapping(receipt.to_dict())
        assert serialized == receipt
        assert serialized.authorization_authenticated is False

        _reject(lambda: _authorize(ready, config, payload, verifier, op_sig, review_sig, ledger))

        stale = readiness.PilotExactTaskProductionActivationReadinessReceipt.from_mapping(ready.to_dict())
        assert stale.evaluation_authenticated is False
        stale_temp, stale_ledger = _ledger("rsi-production-activation-auth-stale-")
        try:
            _reject(lambda: _authorize(stale, config, payload, verifier, op_sig, review_sig, stale_ledger))
        finally:
            stale_temp.cleanup()

        source = normal[-1]
        blocked = readiness_contract._evaluate(
            source,
            readiness_contract._policy(source, allowed_completion_sources=("recovery",)),
        )
        assert blocked.production_activation_ready is False
        _reject(lambda: _payload(blocked, _config(blocked)))

        for bad in (
            dict(target_environment="staging"),
            dict(candidate_branch="other"),
            dict(promotion_branch="other"),
            dict(promotion_gate_path="scripts/other.py"),
            dict(promotion_controller_path="scripts/other.ps1"),
            dict(required_switches_sha256="c" * 64),
            dict(require_bodyrig_machine_evidence=False),
            dict(require_agent3_write_pilot=False),
            dict(require_allowlisted_promotion_tree=False),
            dict(require_recovery_first_restart=False),
            dict(require_live_post_restart_health=False),
        ):
            _reject(lambda bad=bad: _config(ready, **bad))

        foreign = _config(ready, repository="other/repo")
        foreign_temp, foreign_ledger = _ledger("rsi-production-activation-auth-foreign-")
        try:
            foreign_payload = _payload(ready, config)
            _reject(lambda: _authorize(ready, foreign, foreign_payload, verifier, op_sig, review_sig, foreign_ledger))
        finally:
            foreign_temp.cleanup()

        bad_raw = json.loads(payload.decode("utf-8"))
        bad_raw["promotion_branch"] = "feat/other"
        bad_bytes = json.dumps(
            bad_raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        bad_verifier, bad_op, bad_review = _dual(bad_bytes)
        tamper_temp, tamper_ledger = _ledger("rsi-production-activation-auth-tamper-")
        try:
            _reject(lambda: _authorize(ready, config, bad_bytes, bad_verifier, bad_op, bad_review, tamper_ledger))
        finally:
            tamper_temp.cleanup()

        collapse_verifier, collapse_op, collapse_review = _dual(payload, same_key=True)
        collapse_temp, collapse_ledger = _ledger("rsi-production-activation-auth-collapse-")
        try:
            _reject(lambda: _authorize(ready, config, payload, collapse_verifier, collapse_op, collapse_review, collapse_ledger))
        finally:
            collapse_temp.cleanup()

        expired_temp, expired_ledger = _ledger("rsi-production-activation-auth-expired-")
        try:
            _reject(
                lambda: _authorize(
                    ready,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    expired_ledger,
                    now_provider=lambda: "2026-09-15T09:57:02Z",
                )
            )
        finally:
            expired_temp.cleanup()

        race_payload = _payload(
            ready,
            config,
            requested="2026-09-15T09:52:01Z",
            expires="2026-09-15T09:52:20Z",
        )
        race_verifier, race_op, race_review = _dual(race_payload)
        race_temp, race_ledger = _ledger("rsi-production-activation-auth-post-lock-expiry-")
        moments = iter(("2026-09-15T09:52:10Z", "2026-09-15T09:52:21Z"))
        try:
            _reject(
                lambda: _authorize(
                    ready,
                    config,
                    race_payload,
                    race_verifier,
                    race_op,
                    race_review,
                    race_ledger,
                    now_provider=lambda: next(moments),
                )
            )
            final_path, lock_path = race_ledger._paths(ready.production_activation_candidate_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
        finally:
            race_temp.cleanup()

        for field, value in (
            ("production_activation_authorized", False),
            ("promotion_gate_execution_authorized", False),
            ("production_env_mutation_authorized", False),
            ("appliance_restart_authorized", False),
            ("production_receipt_write_authorized", False),
            ("remote_write_authorized", True),
            ("deploy_authorized", True),
            ("promotion_branch", "other"),
            ("required_switches_sha256", "c" * 64),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: activation_auth.PilotExactTaskProductionActivationAuthorizationReceipt.from_mapping(raw)
            )
    finally:
        temp.cleanup()
        readiness_contract._cleanup_normal(normal)

    recovered = readiness_contract._recovered_source()
    recovered_temp, recovered_ledger = _ledger("rsi-production-activation-auth-recovered-")
    try:
        source = recovered[-1]
        ready = readiness_contract._evaluate(source, readiness_contract._policy(source))
        assert ready.production_activation_ready is True
        assert ready.success_status_completion_source == "recovery"
        config = _config(ready)
        payload = _payload(ready, config)
        verifier, op_sig, review_sig = _dual(payload)
        receipt = _authorize(ready, config, payload, verifier, op_sig, review_sig, recovered_ledger)
        _assert_authority(receipt)
        assert receipt.success_status_completion_source == "recovery"
        assert receipt.success_status_source_action == "finalize_existing_state"
    finally:
        recovered_temp.cleanup()
        readiness_contract._cleanup_recovered(recovered)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(activation_auth.PilotExactTaskProductionActivationAuthorizationReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 67

    build_signature = inspect.signature(
        activation_auth.build_pilot_exact_task_production_activation_authorization_payload
    )
    assert list(build_signature.parameters) == [
        "production_activation_readiness",
        "requested_at_utc",
        "expires_at_utc",
        "operator_actor_id",
        "operator_system_id",
        "operator_key_id",
        "reviewer_actor_id",
        "reviewer_system_id",
        "reviewer_key_id",
    ]
    auth_signature = inspect.signature(
        activation_auth.authorize_pilot_exact_task_production_activation
    )
    assert list(auth_signature.parameters) == [
        "production_activation_readiness",
        "authorization_payload",
        "operator_signature",
        "reviewer_signature",
    ]

    source_text = SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "urllib.",
        "requests.",
        "httpx.",
        "subprocess",
        'method="POST"',
        "method='POST'",
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
    ):
        assert forbidden not in source_text
    assert "production_activation_authorized: bool = True" in source_text
    assert "remote_write_authorized: bool = False" in source_text
    assert "deploy_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
