"""Adversarial contract for ADR-DC-079 first Deployment Status authorization."""
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
    improvement_pilot_exact_task_staging_deployment_status_authorization as status_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_status_state_observation as status_state,
)
import rsi_pilot_exact_task_staging_deployment_authorization_contract as deploy_auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_status_state_observation_contract as state_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-staging-deployment-status-authorization-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_deployment_status_authorization.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-079 unexpectedly accepted unsafe Deployment Status authority"
    )


def _fixture(*, recovered=False):
    if recovered:
        context, plan = state_contract._recovered_plan()
    else:
        context, plan = state_contract._normal_plan()
    observation = state_contract._observe(plan, state_contract._Transport(plan))
    assert observation.observation_authenticated is True
    assert observation.remote_state_class == "clear"
    assert observation.status_lane_clear is True
    return context, plan, observation


def _config(observation, **overrides):
    values = dict(
        repository=observation.repository,
        repository_id=observation.repository_id,
        deployment_environment="staging",
        required_remote_state_class="clear",
        deployment_status_state="in_progress",
        deployment_status_environment="staging",
        deployment_status_auto_inactive=False,
        allow_log_url=False,
        allow_environment_url=False,
    )
    values.update(overrides)
    return status_auth.PilotExactTaskStagingDeploymentStatusAuthorizationConfig(
        **values
    )


def _payload(observation, config):
    return status_auth._build_authorization_payload(
        deployment_status_state_observation=observation,
        deployment_status_config=config,
        requested_at_utc="2026-09-15T09:49:59Z",
        expires_at_utc="2026-09-15T09:54:59Z",
        operator_actor_id="deploy.operator",
        operator_system_id="offline-deploy-operator",
        operator_key_id="deploy-op-1",
        reviewer_actor_id="deploy.reviewer",
        reviewer_system_id="offline-deploy-reviewer",
        reviewer_key_id="deploy-review-1",
    )


def _dual_authority(payload, *, same_key=False, signed_at="2026-09-15T09:50:00Z"):
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
        status_auth._PilotExactTaskStagingDeploymentStatusAuthorizationLedger(root),
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
    now="2026-09-15T09:50:10Z",
):
    return status_auth._authorize_verified_pilot_exact_task_staging_deployment_status(
        deployment_status_state_observation=observation,
        deployment_status_config=config,
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

    context, plan, observation = _fixture()
    ledger_temp, ledger = _ledger("rsi-staging-status-auth-")
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
        assert (
            receipt.deployment_status_key_sha256
            == observation.deployment_status_intent_sha256
        )
        assert receipt.deployment_status_state_observation_sha256 == observation.sha256
        assert receipt.staging_deployment_status_plan_sha256 == plan.sha256
        assert (
            receipt.deployment_status_intent_sha256
            == observation.deployment_status_intent_sha256
        )
        assert (
            receipt.remote_deployment_status_state_sha256
            == observation.remote_deployment_status_state_sha256
        )
        assert receipt.deployment_status_authorization_config_sha256 == config.sha256
        assert receipt.deployment_id == plan.deployment_id
        assert receipt.deployment_node_id_sha256 == plan.deployment_node_id_sha256
        assert receipt.deployment_status_state == "in_progress"
        assert receipt.deployment_status_environment == "staging"
        assert receipt.deployment_status_description == plan.deployment_status_description
        assert receipt.deployment_status_body == plan.deployment_status_body
        assert receipt.deployment_status_auto_inactive is False
        assert receipt.deployment_status_log_url is None
        assert receipt.deployment_status_environment_url is None
        assert receipt.required_remote_state_class == "clear"
        assert receipt.host_status_guard_committed is True
        assert receipt.deployment_status_state_observation_authenticated is True
        assert receipt.staging_deployment_status_plan_authenticated is True
        assert receipt.status_lane_clear is True
        assert receipt.dual_external_ed25519_authorized is True
        assert receipt.first_deployment_status_authorized is True
        assert receipt.deployment_status_mutation_authorized is True
        assert receipt.remote_write_authorized is True
        assert receipt.deployment_mutation_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = (
            status_auth.PilotExactTaskStagingDeploymentStatusAuthorizationReceipt.from_mapping(
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
            status_state.PilotExactTaskStagingDeploymentStatusStateObservationReceipt.from_mapping(
                observation.to_dict()
            )
        )
        assert stale.observation_authenticated is False
        stale_temp, stale_ledger = _ledger("rsi-staging-status-auth-stale-")
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
                    state_contract._Transport(plan),
                )
            )
        finally:
            stale_temp.cleanup()

        for bad in (
            dict(repository="other/repo"),
            dict(deployment_environment="production"),
            dict(required_remote_state_class="exact-existing"),
            dict(deployment_status_state="success"),
            dict(deployment_status_environment="production"),
            dict(deployment_status_auto_inactive=True),
            dict(allow_log_url=True),
            dict(allow_environment_url=True),
        ):
            _reject(lambda bad=bad: _config(observation, **bad))

        exact = state_contract._observe(
            plan,
            state_contract._Transport(plan, state_class="exact-existing"),
            now="2026-09-15T09:50:01Z",
        )
        assert exact.remote_state_class == "exact-existing"
        _reject(lambda: _payload(exact, config))

        bad_raw = json.loads(payload.decode("utf-8"))
        bad_raw["deployment_status_state"] = "success"
        bad_bytes = json.dumps(
            bad_raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        bad_verifier, bad_op, bad_review = _dual_authority(bad_bytes)
        tamper_temp, tamper_ledger = _ledger("rsi-staging-status-auth-tamper-")
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
        collapse_temp, collapse_ledger = _ledger("rsi-staging-status-auth-collapse-")
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

        expired_temp, expired_ledger = _ledger("rsi-staging-status-auth-expired-")
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
                    now="2026-09-15T09:55:00Z",
                )
            )
        finally:
            expired_temp.cleanup()

        credential_temp, credential_ledger = _ledger(
            "rsi-staging-status-auth-credential-"
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

        race_temp, race_ledger = _ledger("rsi-staging-status-auth-race-")
        try:
            race_transport = state_contract._Transport(
                plan,
                scripted=["clear", "clear", "exact-existing", "exact-existing"],
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
                observation.deployment_status_intent_sha256
            )
            assert lock_path.exists()
            assert not final_path.exists()
        finally:
            race_temp.cleanup()

        for field, value in (
            ("host_status_guard_committed", False),
            ("deployment_status_state_observation_authenticated", False),
            ("staging_deployment_status_plan_authenticated", False),
            ("status_lane_clear", False),
            ("deployment_status_authorization_config_host_pinned", False),
            ("dual_external_ed25519_authorized", False),
            ("first_deployment_status_authorized", False),
            ("deployment_status_mutation_authorized", False),
            ("remote_write_authorized", False),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("release_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("deployment_status_state", "success"),
            ("deployment_status_environment", "production"),
            ("deployment_status_auto_inactive", True),
            ("deployment_status_log_url", "https://example.invalid/log"),
            ("deployment_status_environment_url", "https://example.invalid/env"),
            ("required_remote_state_class", "exact-existing"),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: status_auth.PilotExactTaskStagingDeploymentStatusAuthorizationReceipt.from_mapping(
                    raw
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            status_auth.PilotExactTaskStagingDeploymentStatusAuthorizationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 87

        build_sig = inspect.signature(
            status_auth.build_pilot_exact_task_staging_deployment_status_authorization_payload
        )
        assert list(build_sig.parameters) == [
            "deployment_status_state_observation",
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
            status_auth.authorize_pilot_exact_task_staging_deployment_status
        )
        assert list(authorize_sig.parameters) == [
            "deployment_status_state_observation",
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
        ):
            assert forbidden not in source_text
        assert "create_deployment_status(" not in source_text
        assert "urllib.request" not in source_text
        assert "deployment_status_mutation_authorized: bool = True" in source_text
        assert "deployment_mutation_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        ledger_temp.cleanup()
        state_contract._cleanup(context)

    recovered_context, recovered_plan, recovered_observation = _fixture(
        recovered=True
    )
    recovered_temp, recovered_ledger = _ledger(
        "rsi-staging-status-auth-recovered-"
    )
    try:
        config = _config(recovered_observation)
        payload = _payload(recovered_observation, config)
        verifier, op_sig, review_sig = _dual_authority(payload)
        receipt = _authorize(
            recovered_observation,
            config,
            payload,
            verifier,
            op_sig,
            review_sig,
            recovered_ledger,
            state_contract._Transport(recovered_plan),
        )
        assert receipt.authorization_authenticated is True
        assert receipt.completion_source == "recovery"
        assert receipt.source_action == "finalize_existing_state"
        assert receipt.source_remote_write_performed is False
        assert receipt.recovery_lock_sha256 is not None
        assert receipt.status_lane_clear is True
        assert receipt.first_deployment_status_authorized is True
        assert receipt.deployment_status_mutation_authorized is True
        assert receipt.deployment_mutation_authorized is False
        assert receipt.production_activation_authorized is False
    finally:
        recovered_temp.cleanup()
        state_contract._cleanup(recovered_context)


if __name__ == "__main__":
    run_contract()
