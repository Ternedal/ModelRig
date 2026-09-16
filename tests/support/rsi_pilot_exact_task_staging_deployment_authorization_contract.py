"""Adversarial contract for ADR-DC-073 one-shot staging deployment authorization."""
from __future__ import annotations

import hashlib
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
from source_code import code_of  # noqa: E402

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_authorization as deploy_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_state_observation as deploy_state,
)
import rsi_pilot_exact_task_staging_deployment_state_observation_contract as state_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-staging-deployment-authorization-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_staging_deployment_authorization.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-073 unexpectedly accepted unsafe deployment authority")


def _fixture():
    items, readiness, plan = state_contract._live_plan()
    transport = state_contract._Transport(plan, readiness)
    observation = state_contract._observe(plan, transport)
    assert observation.observation_authenticated is True
    assert observation.deployment_lane_clear is True
    return items, readiness, plan, observation


def _config(observation, **overrides):
    values = dict(
        repository=observation.repository,
        repository_id=observation.repository_id,
        deployment_environment="staging",
        required_remote_state_class="clear",
        deployment_task="deploy",
        auto_merge=False,
        required_contexts=(),
        transient_environment=False,
        production_environment=False,
    )
    values.update(overrides)
    return deploy_auth.PilotExactTaskStagingDeploymentAuthorizationConfig(**values)


def _payload(observation, config):
    return deploy_auth._build_authorization_payload(
        deployment_state_observation=observation,
        deployment_config=config,
        requested_at_utc="2026-09-15T09:49:10Z",
        expires_at_utc="2026-09-15T09:54:10Z",
        operator_actor_id="deploy.operator",
        operator_system_id="offline-deploy-operator",
        operator_key_id="deploy-op-1",
        reviewer_actor_id="deploy.reviewer",
        reviewer_system_id="offline-deploy-reviewer",
        reviewer_key_id="deploy-review-1",
    )


def _dual_authority(payload: bytes, *, same_key=False, signed_at="2026-09-15T09:49:20Z"):
    custody = asymmetric_authority_key_custody_policy_sha256()
    defs = (
        (bytes(range(1, 33)), "deploy-op-1", "deploy.operator", "offline-deploy-operator"),
        (
            bytes(range(1, 33)) if same_key else bytes(range(33, 65)),
            "deploy-op-1" if same_key else "deploy-review-1",
            "deploy.operator" if same_key else "deploy.reviewer",
            "offline-deploy-operator" if same_key else "offline-deploy-reviewer",
        ),
    )
    keys = {}
    signatures = []
    for raw_private, key_id, actor_id, system_id in defs:
        private = Ed25519PrivateKey.from_private_bytes(raw_private)
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        trusted = TrustedEd25519AuthorityKey(
            key_id=key_id,
            issuer_actor_id=actor_id,
            issuer_system_id=system_id,
            public_key_hex=public.hex(),
            valid_from_utc="2026-01-01T00:00:00Z",
            valid_until_utc="2027-01-01T00:00:00Z",
            keyring_epoch=1,
            custody_policy_sha256=custody,
        )
        keys[key_id] = trusted
        message = authority_signing_message(
            key_id=trusted.key_id,
            issuer_actor_id=trusted.issuer_actor_id,
            issuer_system_id=trusted.issuer_system_id,
            keyring_epoch=trusted.keyring_epoch,
            custody_policy_sha256=custody,
            payload=payload,
        )
        signatures.append(
            DetachedEd25519AuthoritySignature(
                key_id=trusted.key_id,
                issuer_actor_id=trusted.issuer_actor_id,
                issuer_system_id=trusted.issuer_system_id,
                keyring_epoch=trusted.keyring_epoch,
                custody_policy_sha256=custody,
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                signature_hex=private.sign(message).hex(),
                signed_at_utc=signed_at,
            )
        )
    return Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=1), signatures[0], signatures[1]


def _ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, deploy_auth._PilotExactTaskStagingDeploymentAuthorizationLedger(root)


def _authorize(observation, config, payload, verifier, op_sig, review_sig, ledger, transport, *, now="2026-09-15T09:49:30Z"):
    return deploy_auth._authorize_verified_pilot_exact_task_staging_deployment(
        deployment_state_observation=observation,
        deployment_config=config,
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

    items, readiness, plan, observation = _fixture()
    ledger_temp, ledger = _ledger("rsi-staging-deploy-auth-")
    try:
        config = _config(observation)
        payload = _payload(observation, config)
        verifier, op_sig, review_sig = _dual_authority(payload)
        transport = state_contract._Transport(plan, readiness)
        receipt = _authorize(
            observation, config, payload, verifier, op_sig, review_sig, ledger, transport
        )
        assert transport.calls == 4
        assert receipt.authorization_authenticated is True
        assert receipt.deployment_key_sha256 == observation.execution_nonce_sha256
        assert receipt.deployment_state_observation_sha256 == observation.sha256
        assert receipt.staging_deployment_plan_sha256 == observation.staging_deployment_plan_sha256
        assert receipt.deployment_intent_sha256 == observation.deployment_intent_sha256
        assert receipt.remote_deployment_state_sha256 == observation.remote_deployment_state_sha256
        assert receipt.deployment_authorization_config_sha256 == config.sha256
        assert receipt.deployment_environment == "staging"
        assert receipt.deployment_ref == plan.deployment_ref
        assert receipt.deployment_task == "deploy"
        assert receipt.deployment_payload_sha256 == plan.deployment_payload_sha256
        assert receipt.deployment_description_sha256 == plan.deployment_description_sha256
        assert receipt.host_deployment_guard_committed is True
        assert receipt.dual_external_ed25519_authorized is True
        assert receipt.deployment_mutation_authorized is True
        assert receipt.deploy_authorized is True
        assert receipt.remote_write_authorized is True
        assert receipt.release_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = deploy_auth.PilotExactTaskStagingDeploymentAuthorizationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.authorization_authenticated is False

        _reject(
            lambda: _authorize(
                observation,
                config,
                payload,
                verifier,
                op_sig,
                review_sig,
                ledger,
                state_contract._Transport(plan, readiness),
            )
        )

        stale = deploy_state.PilotExactTaskStagingDeploymentStateObservationReceipt.from_mapping(
            observation.to_dict()
        )
        assert stale.observation_authenticated is False
        stale_temp, stale_ledger = _ledger("rsi-staging-deploy-auth-stale-")
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
                    state_contract._Transport(plan, readiness),
                )
            )
        finally:
            stale_temp.cleanup()

        for bad in (
            dict(repository="other/repo"),
            dict(deployment_environment="production"),
            dict(required_remote_state_class="exact-existing"),
            dict(deployment_task="other"),
            dict(auto_merge=True),
            dict(required_contexts=("ci",)),
            dict(transient_environment=True),
            dict(production_environment=True),
        ):
            _reject(lambda bad=bad: _config(observation, **bad))

        exact = state_contract._observe(
            plan,
            state_contract._Transport(plan, readiness, state_class="exact-existing"),
            now="2026-09-15T09:49:01Z",
        )
        _reject(lambda: _payload(exact, config))

        bad_payload = json.loads(payload.decode())
        bad_payload["deployment_ref"] = "other-tag"
        bad_bytes = json.dumps(
            bad_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        bad_verifier, bad_op, bad_review = _dual_authority(bad_bytes)
        tamper_temp, tamper_ledger = _ledger("rsi-staging-deploy-auth-tamper-")
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
                    state_contract._Transport(plan, readiness),
                )
            )
        finally:
            tamper_temp.cleanup()

        collapse_verifier, collapse_op, collapse_review = _dual_authority(payload, same_key=True)
        collapse_temp, collapse_ledger = _ledger("rsi-staging-deploy-auth-collapse-")
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
                    state_contract._Transport(plan, readiness),
                )
            )
        finally:
            collapse_temp.cleanup()

        expired_temp, expired_ledger = _ledger("rsi-staging-deploy-auth-expired-")
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
                    state_contract._Transport(plan, readiness),
                    now="2026-09-15T09:55:00Z",
                )
            )
        finally:
            expired_temp.cleanup()

        race_temp, race_ledger = _ledger("rsi-staging-deploy-auth-race-")
        try:
            race_transport = state_contract._Transport(
                plan,
                readiness,
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
            final_path, lock_path = race_ledger._paths(observation.execution_nonce_sha256)
            assert lock_path.exists()
            assert not final_path.exists()
        finally:
            race_temp.cleanup()

        for field, value in (
            ("host_deployment_guard_committed", False),
            ("deployment_state_observation_authenticated", False),
            ("staging_deployment_plan_authenticated", False),
            ("deployment_lane_clear", False),
            ("deployment_authorization_config_host_pinned", False),
            ("dual_external_ed25519_authorized", False),
            ("deploy_readiness_authorized", True),
            ("deployment_mutation_authorized", False),
            ("deploy_authorized", False),
            ("remote_write_authorized", False),
            ("release_authorized", True),
            ("tag_write_authorized", True),
            ("release_mutation_authorized", True),
            ("merge_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    deploy_auth.PilotExactTaskStagingDeploymentAuthorizationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(
            deploy_auth.PilotExactTaskStagingDeploymentAuthorizationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 78

        build_sig = inspect.signature(
            deploy_auth.build_pilot_exact_task_staging_deployment_authorization_payload
        )
        assert list(build_sig.parameters) == [
            "deployment_state_observation",
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
            deploy_auth.authorize_pilot_exact_task_staging_deployment
        )
        assert list(authorize_sig.parameters) == [
            "deployment_state_observation",
            "authorization_payload",
            "operator_signature",
            "reviewer_signature",
        ]

        source_text = code_of(SOURCE)
        assert 'method="POST"' not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "create_deployment(" not in source_text
        assert "create_deployment_status(" not in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        ledger_temp.cleanup()
        state_contract.plan_contract.ready_contract._cleanup_source(items)


if __name__ == "__main__":
    run_contract()
