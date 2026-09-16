"""Adversarial contract for ADR-DC-087 staging success-status authorization."""
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

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_success_status_authorization as success_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_success_status_state_observation as success_state,
)
import rsi_pilot_exact_task_staging_deployment_authorization_contract as deploy_auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_state_observation_contract as state_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-success-status-authorization-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_success_status_authorization.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-087 unexpectedly accepted unsafe success-status authority")


def _fixture(*, recovered=False):
    bundle, plan = state_contract._live_plan(recovered=recovered)
    observation = state_contract._observe(
        plan,
        state_contract._Transport(plan),
        now="2026-09-15T09:51:10Z",
    )
    assert observation.observation_authenticated is True
    assert observation.remote_state_class == "clear"
    assert observation.success_status_lane_clear is True
    return bundle, plan, observation


def _config(observation, **overrides):
    values = dict(
        repository=observation.repository,
        repository_id=observation.repository_id,
        deployment_environment="staging",
        required_remote_state_class="clear",
        deployment_status_state="success",
        deployment_status_environment="staging",
        deployment_status_auto_inactive=False,
        allow_log_url=False,
        allow_environment_url=False,
    )
    values.update(overrides)
    return success_auth.PilotExactTaskStagingSuccessStatusAuthorizationConfig(**values)


def _payload(observation, config):
    return success_auth._build_authorization_payload(
        success_status_state_observation=observation,
        success_status_config=config,
        requested_at_utc="2026-09-15T09:51:11Z",
        expires_at_utc="2026-09-15T09:56:11Z",
        operator_actor_id="deploy.operator",
        operator_system_id="offline-deploy-operator",
        operator_key_id="deploy-op-1",
        reviewer_actor_id="deploy.reviewer",
        reviewer_system_id="offline-deploy-reviewer",
        reviewer_key_id="deploy-review-1",
    )


def _dual_authority(payload, *, same_key=False, signed_at="2026-09-15T09:51:12Z"):
    return deploy_auth_contract._dual_authority(
        payload,
        same_key=same_key,
        signed_at=signed_at,
    )


def _ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return (
        temp,
        success_auth._PilotExactTaskStagingSuccessStatusAuthorizationLedger(root),
    )


def _authorize(
    observation,
    config,
    payload,
    verifier,
    op_sig,
    review_sig,
    ledger,
    transport,
    *,
    now="2026-09-15T09:51:20Z",
):
    return success_auth._authorize_verified_pilot_exact_task_staging_success_status(
        success_status_state_observation=observation,
        success_status_config=config,
        authorization_payload=payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        ledger=ledger,
        transport=transport,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle, plan, observation = _fixture()
    ledger_temp, ledger = _ledger("rsi-staging-success-status-auth-")
    try:
        config = _config(observation)
        payload = _payload(observation, config)
        verifier, op_sig, review_sig = _dual_authority(payload)
        transport = state_contract._Transport(plan)
        receipt = _authorize(
            observation,
            config,
            payload,
            verifier,
            op_sig,
            review_sig,
            ledger,
            transport,
        )
        assert transport.calls == 4
        assert receipt.authorization_authenticated is True
        assert receipt.success_status_key_sha256 == (
            observation.success_deployment_status_intent_sha256
        )
        assert receipt.success_status_state_observation_sha256 == observation.sha256
        assert receipt.staging_success_status_plan_sha256 == plan.sha256
        assert receipt.staging_runtime_build_identity_sha256 == (
            observation.staging_runtime_build_identity_sha256
        )
        assert receipt.success_deployment_status_intent_sha256 == (
            observation.success_deployment_status_intent_sha256
        )
        assert receipt.remote_success_status_state_sha256 == (
            observation.remote_success_status_state_sha256
        )
        assert receipt.success_status_authorization_config_sha256 == config.sha256
        assert receipt.deployment_environment == "staging"
        assert receipt.deployment_id == plan.deployment_id
        assert receipt.current_deployment_status_id == plan.current_deployment_status_id
        assert receipt.success_deployment_status_state == "success"
        assert receipt.success_deployment_status_environment == "staging"
        assert receipt.success_deployment_status_description == (
            plan.success_deployment_status_description
        )
        assert receipt.success_deployment_status_body == plan.success_deployment_status_body
        assert receipt.success_deployment_status_auto_inactive is False
        assert receipt.success_deployment_status_log_url is None
        assert receipt.success_deployment_status_environment_url is None
        assert receipt.required_remote_state_class == "clear"
        assert receipt.host_success_status_guard_committed is True
        assert receipt.success_status_state_observation_authenticated is True
        assert receipt.staging_success_status_plan_authenticated is True
        assert receipt.success_status_lane_clear is True
        assert receipt.success_status_authorization_config_host_pinned is True
        assert receipt.dual_external_ed25519_authorized is True
        assert receipt.success_deployment_status_authorized is True
        assert receipt.deployment_status_mutation_authorized is True
        assert receipt.remote_write_authorized is True
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.release_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = (
            success_auth.PilotExactTaskStagingSuccessStatusAuthorizationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.authorization_authenticated is False

        replay_transport = state_contract._Transport(plan)
        _reject(
            lambda: _authorize(
                observation,
                config,
                payload,
                verifier,
                op_sig,
                review_sig,
                ledger,
                replay_transport,
            )
        )

        stale = (
            success_state.PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(
                observation.to_dict()
            )
        )
        assert stale.observation_authenticated is False
        stale_temp, stale_ledger = _ledger("rsi-staging-success-status-auth-stale-")
        try:
            stale_transport = state_contract._Transport(plan)
            _reject(
                lambda: _authorize(
                    stale,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    stale_ledger,
                    stale_transport,
                )
            )
            assert stale_transport.calls == 0
        finally:
            stale_temp.cleanup()

        for bad in (
            dict(repository="other/repo"),
            dict(deployment_environment="production"),
            dict(required_remote_state_class="exact-existing"),
            dict(deployment_status_state="in_progress"),
            dict(deployment_status_environment="production"),
            dict(deployment_status_auto_inactive=True),
            dict(allow_log_url=True),
            dict(allow_environment_url=True),
        ):
            _reject(lambda bad=bad: _config(observation, **bad))

        exact = state_contract._observe(
            plan,
            state_contract._Transport(
                plan,
                states=[state_contract._state(plan, exact=True)],
            ),
            now="2026-09-15T09:51:11Z",
        )
        assert exact.remote_state_class == "exact-existing"
        _reject(lambda: _payload(exact, config))

        bad_raw = json.loads(payload.decode("utf-8"))
        bad_raw["success_deployment_status_state"] = "failure"
        bad_bytes = json.dumps(
            bad_raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        bad_verifier, bad_op, bad_review = _dual_authority(bad_bytes)
        tamper_temp, tamper_ledger = _ledger("rsi-staging-success-status-auth-tamper-")
        try:
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    bad_bytes,
                    bad_verifier,
                    bad_op,
                    bad_review,
                    tamper_ledger,
                    state_contract._Transport(plan),
                )
            )
        finally:
            tamper_temp.cleanup()

        collapse_verifier, collapse_op, collapse_review = _dual_authority(
            payload, same_key=True
        )
        collapse_temp, collapse_ledger = _ledger(
            "rsi-staging-success-status-auth-collapse-"
        )
        try:
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    payload,
                    collapse_verifier,
                    collapse_op,
                    collapse_review,
                    collapse_ledger,
                    state_contract._Transport(plan),
                )
            )
        finally:
            collapse_temp.cleanup()

        expired_temp, expired_ledger = _ledger(
            "rsi-staging-success-status-auth-expired-"
        )
        try:
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    expired_ledger,
                    state_contract._Transport(plan),
                    now="2026-09-15T09:56:12Z",
                )
            )
        finally:
            expired_temp.cleanup()

        credential_temp, credential_ledger = _ledger(
            "rsi-staging-success-status-auth-credential-"
        )
        try:
            credential_transport = state_contract._Transport(plan)
            credential_transport.credential_path_sha256 = "8" * 64
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    credential_ledger,
                    credential_transport,
                )
            )
            assert credential_transport.calls == 0
        finally:
            credential_temp.cleanup()

        race_temp, race_ledger = _ledger("rsi-staging-success-status-auth-race-")
        try:
            race_transport = state_contract._Transport(
                plan,
                states=[
                    state_contract._state(plan),
                    state_contract._state(plan),
                    state_contract._state(plan, exact=True),
                    state_contract._state(plan, exact=True),
                ],
            )
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    race_ledger,
                    race_transport,
                )
            )
            final_path, lock_path = race_ledger._paths(
                observation.success_deployment_status_intent_sha256
            )
            assert lock_path.exists()
            assert not final_path.exists()
        finally:
            race_temp.cleanup()

        for field, value in (
            ("host_success_status_guard_committed", False),
            ("success_status_state_observation_authenticated", False),
            ("staging_success_status_plan_authenticated", False),
            ("success_status_lane_clear", False),
            ("success_status_authorization_config_host_pinned", False),
            ("dual_external_ed25519_authorized", False),
            ("success_deployment_status_authorized", False),
            ("deployment_status_mutation_authorized", False),
            ("remote_write_authorized", False),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("release_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("success_deployment_status_state", "failure"),
            ("success_deployment_status_environment", "production"),
            ("success_deployment_status_auto_inactive", True),
            ("success_deployment_status_log_url", "https://example.invalid/log"),
            ("success_deployment_status_environment_url", "https://example.invalid/env"),
            ("required_remote_state_class", "exact-existing"),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: (
                    success_auth.PilotExactTaskStagingSuccessStatusAuthorizationReceipt.from_mapping(
                        raw
                    )
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            success_auth.PilotExactTaskStagingSuccessStatusAuthorizationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 67

        build_sig = inspect.signature(
            success_auth.build_pilot_exact_task_staging_success_status_authorization_payload
        )
        assert list(build_sig.parameters) == [
            "success_status_state_observation",
            "requested_at_utc",
            "expires_at_utc",
            "operator_actor_id",
            "operator_system_id",
            "operator_key_id",
            "reviewer_actor_id",
            "reviewer_system_id",
            "reviewer_key_id",
        ]
        authorize_sig = inspect.signature(
            success_auth.authorize_pilot_exact_task_staging_success_status
        )
        assert list(authorize_sig.parameters) == [
            "success_status_state_observation",
            "authorization_payload",
            "operator_signature",
            "reviewer_signature",
        ]

        source_text = SOURCE.read_text(encoding="utf-8")
        for forbidden in (
            'method="POST"',
            "method='POST'",
            'method="PUT"',
            "method='PUT'",
            'method="PATCH"',
            "method='PATCH'",
            'method="DELETE"',
            "method='DELETE'",
            "create_deployment_status(",
        ):
            assert forbidden not in source_text
        assert "create_once_file" in source_text
        assert "success_deployment_status_authorized: bool = True" in source_text
        assert "deployment_status_mutation_authorized: bool = True" in source_text
        assert "remote_write_authorized: bool = True" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        ledger_temp.cleanup()
        state_contract.plan_contract._cleanup(bundle)

    recovered_bundle, recovered_plan, recovered_observation = _fixture(recovered=True)
    recovered_temp, recovered_ledger = _ledger(
        "rsi-staging-success-status-auth-recovered-"
    )
    try:
        recovered_config = _config(recovered_observation)
        recovered_payload = _payload(recovered_observation, recovered_config)
        verifier, op_sig, review_sig = _dual_authority(recovered_payload)
        recovered = _authorize(
            recovered_observation,
            recovered_config,
            recovered_payload,
            verifier,
            op_sig,
            review_sig,
            recovered_ledger,
            state_contract._Transport(recovered_plan),
        )
        assert recovered.authorization_authenticated is True
        assert recovered.status_recovery_lock_sha256 is not None
        assert recovered.success_deployment_status_authorized is True
        assert recovered.deployment_status_mutation_authorized is True
        assert recovered.production_activation_authorized is False
    finally:
        recovered_temp.cleanup()
        state_contract.plan_contract._cleanup(recovered_bundle)


if __name__ == "__main__":
    run_contract()
