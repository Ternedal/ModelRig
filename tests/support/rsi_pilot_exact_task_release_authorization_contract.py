"""Adversarial contract for ADR-DC-066 exact one-shot release authorization."""
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
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

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
    improvement_pilot_exact_task_release_authorization as release_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_state_observation as release_state,
)
from rsi_pilot_exact_task_post_merge_attestation_contract import _cleanup_case  # noqa: E402
from rsi_pilot_exact_task_release_state_observation_contract import (  # noqa: E402
    _Transport,
    _fixture,
    _observe,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-release-authorization-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_release_authorization.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-066 unexpectedly accepted unsafe release authority")


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, release_auth._PilotExactTaskReleaseAuthorizationLedger(root)


def _live_clear_observation():
    case, readiness, plan = _fixture()
    observation = _observe(plan, _Transport(plan, readiness))
    assert observation.observation_authenticated is True
    assert observation.remote_state_class == "clear"
    assert observation.release_lane_clear is True
    return case, readiness, plan, observation


def _config(
    observation,
    *,
    repository=None,
    repository_id=None,
    release_base_branch=None,
    required_remote_state_class="clear",
    release_draft=True,
    release_prerelease=True,
    make_latest=False,
):
    return release_auth.PilotExactTaskReleaseAuthorizationConfig(
        repository=observation.repository if repository is None else repository,
        repository_id=(
            observation.repository_id if repository_id is None else repository_id
        ),
        release_base_branch=(
            observation.release_base_branch
            if release_base_branch is None
            else release_base_branch
        ),
        required_remote_state_class=required_remote_state_class,
        release_draft=release_draft,
        release_prerelease=release_prerelease,
        make_latest=make_latest,
    )


def _payload(observation, config):
    return release_auth._build_authorization_payload(
        release_state_observation=observation,
        release_config=config,
        requested_at_utc="2026-09-15T09:44:10Z",
        expires_at_utc="2026-09-15T09:49:10Z",
        operator_actor_id="release.operator",
        operator_system_id="offline-release-operator",
        operator_key_id="release-op-1",
        reviewer_actor_id="release.reviewer",
        reviewer_system_id="offline-release-reviewer",
        reviewer_key_id="release-review-1",
    )


def _dual_authority(payload: bytes, *, signed_at="2026-09-15T09:44:20Z"):
    custody = asymmetric_authority_key_custody_policy_sha256()
    definitions = (
        (
            bytes(range(1, 33)),
            "release-op-1",
            "release.operator",
            "offline-release-operator",
        ),
        (
            bytes(range(33, 65)),
            "release-review-1",
            "release.reviewer",
            "offline-release-reviewer",
        ),
    )
    keys = {}
    signatures = []
    for raw_private, key_id, actor_id, system_id in definitions:
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
    return (
        Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=1),
        signatures[0],
        signatures[1],
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
    now="2026-09-15T09:44:30Z",
):
    return release_auth._authorize_verified_pilot_exact_task_release(
        release_state_observation=observation,
        release_config=config,
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

    case, readiness, plan, observation = _live_clear_observation()
    ledger_temp, ledger = _ledger("rsi-exact-task-release-auth-")
    try:
        config = _config(observation)
        payload = _payload(observation, config)
        verifier, op_sig, review_sig = _dual_authority(payload)
        transport = _Transport(plan, readiness)
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

        assert transport.calls == ["observe", "observe", "observe", "observe"]
        assert receipt.authorization_authenticated is True
        assert receipt.release_key_sha256 == observation.execution_nonce_sha256
        assert receipt.execution_nonce_sha256 == observation.execution_nonce_sha256
        assert receipt.release_state_observation_sha256 == observation.sha256
        assert receipt.release_plan_sha256 == observation.release_plan_sha256
        assert receipt.release_readiness_evaluation_sha256 == (
            observation.release_readiness_evaluation_sha256
        )
        assert receipt.release_intent_sha256 == observation.release_intent_sha256
        assert receipt.release_plan_config_sha256 == observation.release_plan_config_sha256
        assert receipt.remote_release_state_sha256 == observation.remote_release_state_sha256
        assert receipt.release_authorization_config_sha256 == config.sha256
        assert receipt.publisher_credential_config_sha256 == (
            observation.publisher_credential_config_sha256
        )
        assert receipt.publisher_credential_path_sha256 == (
            observation.publisher_credential_path_sha256
        )
        assert receipt.repository == observation.repository
        assert receipt.repository_id == observation.repository_id
        assert receipt.release_base_branch == observation.release_base_branch
        assert receipt.merge_commit_sha == observation.merge_commit_sha
        assert receipt.release_version == observation.release_version
        assert receipt.tag_name == observation.tag_name
        assert receipt.tag_target_sha == observation.tag_target_sha
        assert receipt.release_name == observation.release_name
        assert receipt.release_body_sha256 == observation.release_body_sha256
        assert receipt.release_draft is True
        assert receipt.release_prerelease is True
        assert receipt.make_latest is False
        assert receipt.host_release_guard_committed is True
        assert receipt.release_state_observation_authenticated is True
        assert receipt.release_plan_authenticated is True
        assert receipt.release_lane_clear is True
        assert receipt.release_authorization_config_host_pinned is True
        assert receipt.dual_external_ed25519_authorized is True
        assert receipt.tag_write_authorized is True
        assert receipt.release_mutation_authorized is True
        assert receipt.release_authorized is True
        assert receipt.remote_write_authorized is True
        assert receipt.merge_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.review_submission_authorized is False
        assert receipt.review_thread_mutation_authorized is False
        assert receipt.ready_for_review_authorized is False
        assert receipt.reviewer_request_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.product_pilot_started is False
        assert receipt.nonce_reusable is False

        reloaded = release_auth.PilotExactTaskReleaseAuthorizationReceipt.from_mapping(
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
                _Transport(plan, readiness),
            )
        )

        reloaded_observation = (
            release_state.PilotExactTaskReleaseStateObservationReceipt.from_mapping(
                observation.to_dict()
            )
        )
        assert reloaded_observation.observation_authenticated is False
        fresh_temp, fresh_ledger = _ledger(
            "rsi-exact-task-release-auth-reloaded-"
        )
        try:
            _reject(
                lambda: _authorize(
                    reloaded_observation,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    fresh_ledger,
                    _Transport(plan, readiness),
                )
            )
        finally:
            fresh_temp.cleanup()

        exact_existing = _observe(
            plan,
            _Transport(plan, readiness, state_class="exact-existing"),
            now="2026-09-15T09:44:01Z",
        )
        assert exact_existing.exact_existing_release is True
        _reject(lambda: _payload(exact_existing, _config(exact_existing)))

        for bad_config in (
            _config(observation, repository="other/repo"),
            _config(observation, repository_id="999"),
            _config(observation, release_base_branch="release"),
        ):
            _reject(
                lambda bad_config=bad_config: _payload(observation, bad_config)
            )
        _reject(
            lambda: _config(
                observation,
                required_remote_state_class="exact-existing",
            )
        )
        _reject(lambda: _config(observation, release_draft=False))
        _reject(lambda: _config(observation, release_prerelease=False))
        _reject(lambda: _config(observation, make_latest=True))

        bad_claim = json.loads(payload.decode("utf-8"))
        bad_claim["tag_name"] = "caller-controlled-tag"
        bad_payload = json.dumps(
            bad_claim, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        bad_verifier, bad_op, bad_review = _dual_authority(bad_payload)
        fresh_temp, fresh_ledger = _ledger(
            "rsi-exact-task-release-auth-bad-payload-"
        )
        try:
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    bad_payload,
                    bad_verifier,
                    bad_op,
                    bad_review,
                    fresh_ledger,
                    _Transport(plan, readiness),
                )
            )
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger(
            "rsi-exact-task-release-auth-same-signer-"
        )
        try:
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    op_sig,
                    fresh_ledger,
                    _Transport(plan, readiness),
                )
            )
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger(
            "rsi-exact-task-release-auth-expired-"
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
                    fresh_ledger,
                    _Transport(plan, readiness),
                    now="2026-09-15T09:49:10Z",
                )
            )
            final, lock = fresh_ledger._paths(observation.execution_nonce_sha256)
            assert not final.exists()
            assert not lock.exists()
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger(
            "rsi-exact-task-release-auth-credential-drift-"
        )
        try:
            credential_drift = _Transport(plan, readiness)
            credential_drift.credential_config_sha256 = "9" * 64
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    fresh_ledger,
                    credential_drift,
                )
            )
            final, lock = fresh_ledger._paths(observation.execution_nonce_sha256)
            assert not final.exists()
            assert not lock.exists()
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger(
            "rsi-exact-task-release-auth-post-lock-drift-"
        )
        try:
            drift_transport = _Transport(plan, readiness)
            drift_transport.scripted = [
                drift_transport._state("clear"),
                drift_transport._state("clear"),
                drift_transport._state("clear"),
                drift_transport._state("exact-existing"),
            ]
            _reject(
                lambda: _authorize(
                    observation,
                    config,
                    payload,
                    verifier,
                    op_sig,
                    review_sig,
                    fresh_ledger,
                    drift_transport,
                )
            )
            final, lock = fresh_ledger._paths(observation.execution_nonce_sha256)
            assert not final.exists()
            assert lock.exists()
        finally:
            fresh_temp.cleanup()

        for field, value in (
            ("host_release_guard_committed", False),
            ("release_state_observation_authenticated", False),
            ("release_plan_authenticated", False),
            ("release_lane_clear", False),
            ("release_authorization_config_host_pinned", False),
            ("dual_external_ed25519_authorized", False),
            ("tag_write_authorized", False),
            ("release_mutation_authorized", False),
            ("release_authorized", False),
            ("remote_write_authorized", False),
            ("merge_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    release_auth.PilotExactTaskReleaseAuthorizationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            release_auth.PilotExactTaskReleaseAuthorizationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 62
        assert schema["properties"]["tag_write_authorized"]["const"] is True
        assert schema["properties"]["release_mutation_authorized"]["const"] is True
        assert schema["properties"]["release_authorized"]["const"] is True
        assert schema["properties"]["remote_write_authorized"]["const"] is True
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["deploy_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        build_sig = inspect.signature(
            release_auth.build_pilot_exact_task_release_authorization_payload
        )
        assert list(build_sig.parameters) == [
            "release_state_observation",
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
            release_auth.authorize_pilot_exact_task_release
        )
        assert list(authorize_sig.parameters) == [
            "release_state_observation",
            "authorization_payload",
            "operator_signature",
            "reviewer_signature",
        ]

        source_text = code_of(SOURCE)
        assert "requests" not in source_text
        assert "httpx" not in source_text
        assert "subprocess" not in source_text
        assert "create_release" not in source_text
        assert "create_ref" not in source_text
        assert "update_ref" not in source_text
        assert "git push" not in source_text
        assert "Ed25519PrivateKey" not in source_text
    finally:
        _cleanup_case(case)


if __name__ == "__main__":
    run_contract()
