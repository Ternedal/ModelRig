"""Adversarial contract for ADR-DC-097 product-pilot start authorization."""
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
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_authorization as start_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_readiness as readiness  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_readiness_contract as readiness_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_authorization_contract as deploy_auth_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-authorization-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_start_authorization.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-097 unexpectedly accepted unsafe product-pilot start authority"
    )


def _ready(shared_fixture=None):
    owns_fixture = shared_fixture is None
    fixture = (
        lineage_contract._build_fixture()
        if owns_fixture
        else shared_fixture
    )
    receipt = readiness_contract._ready_from_fixture(
        fixture,
        "2026-09-15T09:54:40Z",
    )
    assert receipt.readiness_authenticated is True
    assert receipt.product_pilot_start_ready is True
    assert receipt.pre_authorization_requirements_satisfied is True
    assert receipt.runtime_preflight_reverified is True
    assert receipt.allowlisted_task_registry_verified is True
    return fixture, receipt, owns_fixture


def _config(receipt, **overrides):
    values = dict(
        repository=receipt.repository,
        repository_id=receipt.repository_id,
    )
    values.update(overrides)
    return start_auth.PilotExactTaskProductPilotStartAuthorizationConfig(**values)


def _payload(
    receipt,
    config,
    *,
    requested="2026-09-15T09:54:41Z",
    expires="2026-09-15T09:58:41Z",
):
    return start_auth._build_authorization_payload(
        product_pilot_start_readiness=receipt,
        authorization_config=config,
        requested_at_utc=requested,
        expires_at_utc=expires,
        operator_actor_id="deploy.operator",
        operator_system_id="offline-deploy-operator",
        operator_key_id="deploy-op-1",
        reviewer_actor_id="deploy.reviewer",
        reviewer_system_id="offline-deploy-reviewer",
        reviewer_key_id="deploy-review-1",
    )


def _dual(payload, *, same_key=False, signed_at="2026-09-15T09:54:42Z"):
    return deploy_auth_contract._dual_authority(
        payload,
        same_key=same_key,
        signed_at=signed_at,
    )


def _ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, start_auth._PilotExactTaskProductPilotStartAuthorizationLedger(root)


def _authorize(
    receipt,
    config,
    payload,
    verifier,
    op_sig,
    review_sig,
    ledger,
    *,
    moments=None,
):
    if moments is None:
        moments = iter(("2026-09-15T09:54:45Z", "2026-09-15T09:54:46Z"))
    return start_auth._authorize_verified_pilot_exact_task_product_pilot_start(
        product_pilot_start_readiness=receipt,
        authorization_config=config,
        authorization_payload=payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        ledger=ledger,
        now_provider=moments.__next__,
    )


def _assert_authority(receipt) -> None:
    assert receipt.authorization_authenticated is True
    assert receipt.host_product_pilot_start_guard_committed is True
    assert receipt.product_pilot_start_readiness_authenticated is True
    assert receipt.product_pilot_start_intent_bound is True
    assert receipt.product_pilot_start_authorization_config_host_pinned is True
    assert receipt.dual_external_ed25519_authorized is True
    assert receipt.product_pilot_start_authorized is True
    assert receipt.product_pilot_started is False
    assert receipt.production_activation is True
    assert receipt.production_activation_attested is True
    assert receipt.production_activation_authorized is False
    assert receipt.promotion_gate_execution_authorized is False
    assert receipt.production_env_mutation_authorized is False
    assert receipt.appliance_restart_authorized is False
    assert receipt.production_receipt_write_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.release_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.nonce_reusable is False


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    fixture, ready, owns_fixture = _ready(shared_fixture)
    temp, ledger = _ledger("rsi-product-pilot-start-auth-")
    try:
        config = _config(ready)
        payload = _payload(ready, config)
        verifier, op_sig, review_sig = _dual(payload)
        receipt = _authorize(
            ready, config, payload, verifier, op_sig, review_sig, ledger
        )
        _assert_authority(receipt)
        assert receipt.product_pilot_start_readiness_sha256 == ready.sha256
        assert (
            receipt.post_production_activation_attestation_sha256
            == ready.post_production_activation_attestation_sha256
        )
        assert (
            receipt.production_activation_candidate_sha256
            == ready.production_activation_candidate_sha256
        )
        assert receipt.environment_after_sha256 == ready.environment_after_sha256
        assert receipt.output_state_sha256 == ready.output_state_sha256
        assert (
            receipt.machine_production_receipt_sha256
            == ready.machine_production_receipt_sha256
        )
        assert receipt.product_pilot_id == start_auth.PRODUCT_PILOT_ID
        assert (
            receipt.product_pilot_start_key_sha256
            == receipt.product_pilot_start_intent_sha256
        )

        serialized = (
            start_auth.PilotExactTaskProductPilotStartAuthorizationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.authorization_authenticated is False

        _reject(
            lambda: _authorize(
                ready, config, payload, verifier, op_sig, review_sig, ledger
            )
        )

        stale = readiness.PilotExactTaskProductPilotStartReadinessReceipt.from_mapping(
            ready.to_dict()
        )
        assert stale.readiness_authenticated is False
        stale_temp, stale_ledger = _ledger("rsi-product-pilot-start-auth-stale-")
        try:
            _reject(
                lambda: _authorize(
                    stale,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    stale_ledger,
                )
            )
        finally:
            stale_temp.cleanup()

        for bad in (
            dict(product_pilot_id="other-pilot"),
            dict(require_exact_post_production_state=False),
            dict(require_live_readiness_provenance=False),
            dict(require_dual_external_ed25519=False),
        ):
            _reject(lambda bad=bad: _config(ready, **bad))

        foreign = _config(ready, repository="other/repo")
        foreign_temp, foreign_ledger = _ledger(
            "rsi-product-pilot-start-auth-foreign-"
        )
        try:
            _reject(
                lambda: _authorize(
                    ready,
                    foreign,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    foreign_ledger,
                )
            )
        finally:
            foreign_temp.cleanup()

        bad_raw = json.loads(payload.decode("utf-8"))
        bad_raw["product_pilot_id"] = "other-pilot"
        bad_bytes = json.dumps(
            bad_raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        bad_verifier, bad_op, bad_review = _dual(bad_bytes)
        tamper_temp, tamper_ledger = _ledger(
            "rsi-product-pilot-start-auth-tamper-"
        )
        try:
            _reject(
                lambda: _authorize(
                    ready,
                    config,
                    bad_bytes,
                    bad_verifier,
                    bad_op,
                    bad_review,
                    tamper_ledger,
                )
            )
        finally:
            tamper_temp.cleanup()

        collapse_verifier, collapse_op, collapse_review = _dual(
            payload, same_key=True
        )
        collapse_temp, collapse_ledger = _ledger(
            "rsi-product-pilot-start-auth-collapse-"
        )
        try:
            _reject(
                lambda: _authorize(
                    ready,
                    config,
                    payload,
                    collapse_verifier,
                    collapse_op,
                    collapse_review,
                    collapse_ledger,
                )
            )
        finally:
            collapse_temp.cleanup()

        expired_temp, expired_ledger = _ledger(
            "rsi-product-pilot-start-auth-expired-"
        )
        try:
            moments = iter(
                ("2026-09-15T09:58:42Z", "2026-09-15T09:58:43Z")
            )
            _reject(
                lambda: _authorize(
                    ready,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    expired_ledger,
                    moments=moments,
                )
            )
        finally:
            expired_temp.cleanup()

        late_payload = _payload(
            ready,
            config,
            requested="2026-09-15T09:54:41Z",
            expires="2026-09-15T09:55:30Z",
        )
        late_verifier, late_op, late_review = _dual(late_payload)
        late_temp, late_ledger = _ledger(
            "rsi-product-pilot-start-auth-post-lock-expiry-"
        )
        moments = iter(("2026-09-15T09:54:45Z", "2026-09-15T09:55:31Z"))
        try:
            _reject(
                lambda: _authorize(
                    ready,
                    config,
                    late_payload,
                    late_verifier,
                    late_op,
                    late_review,
                    late_ledger,
                    moments=moments,
                )
            )
            intent = start_auth._start_intent_sha256(ready, config)
            final_path, lock_path = late_ledger._paths(intent)
            assert lock_path.exists()
            assert not final_path.exists()
        finally:
            late_temp.cleanup()

        for field, value in (
            ("product_pilot_start_authorized", False),
            ("product_pilot_started", True),
            ("production_activation_authorized", True),
            ("promotion_gate_execution_authorized", True),
            ("production_env_mutation_authorized", True),
            ("appliance_restart_authorized", True),
            ("production_receipt_write_authorized", True),
            ("remote_write_authorized", True),
            ("deploy_authorized", True),
            ("release_authorized", True),
            ("merge_authorized", True),
            ("nonce_reusable", True),
            ("product_pilot_id", "other-pilot"),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: start_auth.PilotExactTaskProductPilotStartAuthorizationReceipt.from_mapping(
                    raw
                )
            )
    finally:
        temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        start_auth.PilotExactTaskProductPilotStartAuthorizationReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 60

    build_signature = inspect.signature(
        start_auth.build_pilot_exact_task_product_pilot_start_authorization_payload
    )
    assert list(build_signature.parameters) == [
        "product_pilot_start_readiness",
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
        start_auth.authorize_pilot_exact_task_product_pilot_start
    )
    assert list(auth_signature.parameters) == [
        "product_pilot_start_readiness",
        "authorization_payload",
        "operator_signature",
        "reviewer_signature",
    ]

    source_code = code_of(SOURCE)
    for forbidden in (
        "urllib.",
        "requests.",
        "httpx.",
        "subprocess.",
        'method="POST"',
        "method='POST'",
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
        "execute_pilot_exact_task_product_pilot_start(",
        "start_product_pilot(",
    ):
        assert forbidden not in source_code
    assert "product_pilot_start_authorized: bool = True" in source_code
    assert "product_pilot_started: bool = False" in source_code
    assert "remote_write_authorized: bool = False" in source_code


if __name__ == "__main__":
    run_contract()
