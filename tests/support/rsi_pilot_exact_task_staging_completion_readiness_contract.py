"""Adversarial contract for ADR-DC-091 staging-completion readiness."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_completion_readiness as readiness,
)
import rsi_pilot_exact_task_post_staging_success_status_attestation_contract as post_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-completion-readiness-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_completion_readiness.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-091 unexpectedly accepted unsafe staging-completion evidence"
    )


def _policy(source, **overrides):
    values = {
        "repository": source.repository,
        "repository_id": source.repository_id,
        "staging_environment": "staging",
    }
    values.update(overrides)
    return readiness.PilotExactTaskStagingCompletionPolicy(**values)


def _evaluate(source, policy, *, now="2026-09-15T09:52:10Z", digest=None):
    return readiness._evaluate_verified_pilot_exact_task_staging_completion_readiness(
        post_staging_success_status_attestation=source,
        policy=policy,
        policy_sha256=policy.sha256 if digest is None else digest,
        now_provider=lambda: now,
    )


def _assert_inert(receipt) -> None:
    assert receipt.post_success_attestation_authenticated is True
    assert receipt.staging_completion_policy_host_pinned is True
    assert receipt.durable_completion_satisfied is True
    assert receipt.runtime_build_identity_binding_satisfied is True
    assert receipt.exact_success_status_satisfied is True
    assert receipt.staging_completion_evaluated is True
    assert receipt.staging_completion_authorized is False
    assert receipt.production_promotion_authorized is False
    assert receipt.production_deployment_authorized is False
    assert receipt.production_activation_authorized is False
    assert receipt.success_deployment_status_authorized is False
    assert receipt.deployment_status_mutation_authorized is False
    assert receipt.deployment_mutation_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.release_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.nonce_reusable is False


def _normal_source():
    bundle, plan, auth_temp, authorization = post_contract.tx_contract._authorization()
    tx_temp, tx_ledger = post_contract.tx_contract._ledger(
        "rsi-staging-completion-readiness-tx-"
    )
    recovery_temp, recovery_root = post_contract._empty_recovery_ledger(
        "rsi-staging-completion-readiness-recovery-empty-"
    )
    status_id = authorization.current_deployment_status_id + 1
    post_contract.tx_contract._execute(
        authorization,
        tx_ledger,
        post_contract.tx_contract._observer(plan, status_id=status_id),
        post_contract.tx_contract._Writer(authorization, status_id=status_id),
    )
    source = post_contract._attest(
        authorization,
        tx_root=tx_ledger.root,
        recovery_root=recovery_root,
        auth_root=Path(auth_temp.name) / "ledger",
        transport=post_contract.recovery_contract._Transport(
            authorization,
            states=[post_contract._normal_state(authorization)],
        ),
    )
    assert source.attestation_authenticated is True
    return (
        source,
        bundle,
        auth_temp,
        tx_temp,
        recovery_temp,
    )


def _cleanup_normal(bundle, auth_temp, tx_temp, recovery_temp):
    recovery_temp.cleanup()
    tx_temp.cleanup()
    post_contract.tx_contract._cleanup(bundle, auth_temp)


def run_contract() -> None:
    if os.name == "nt":
        return

    source, bundle, auth_temp, tx_temp, recovery_temp = _normal_source()
    try:
        policy = _policy(source)
        receipt = _evaluate(source, policy)
        assert receipt.evaluation_authenticated is True
        assert receipt.post_staging_success_status_attestation_sha256 == source.sha256
        assert receipt.staging_runtime_build_identity_sha256 == (
            source.staging_runtime_build_identity_sha256
        )
        assert receipt.remote_success_status_observation_sha256 == (
            source.remote_success_status_observation_sha256
        )
        assert receipt.staging_completion_policy_sha256 == policy.sha256
        assert receipt.attestation_age_seconds == 20
        assert receipt.max_attestation_age_seconds == 60
        assert receipt.blocker_codes == ()
        assert receipt.freshness_policy_satisfied is True
        assert receipt.completion_source_policy_satisfied is True
        assert receipt.source_action_policy_satisfied is True
        assert receipt.staging_complete is True
        assert receipt.next_boundary_ready is True
        _assert_inert(receipt)

        serialized = readiness.PilotExactTaskStagingCompletionReadinessReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.evaluation_authenticated is False

        loose_source = (
            post_contract.attestation.PilotExactTaskPostStagingSuccessStatusAttestationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert loose_source.attestation_authenticated is False
        _reject(lambda: _evaluate(loose_source, policy))

        stale = _evaluate(source, policy, now="2026-09-15T09:52:51Z")
        assert stale.attestation_age_seconds == 61
        assert stale.freshness_policy_satisfied is False
        assert stale.blocker_codes == ("post-success-attestation-too-old",)
        assert stale.staging_complete is False
        assert stale.next_boundary_ready is False
        _assert_inert(stale)

        recovery_only = _policy(
            source,
            allowed_completion_sources=("recovery",),
        )
        blocked_source = _evaluate(source, recovery_only)
        assert blocked_source.completion_source_policy_satisfied is False
        assert blocked_source.blocker_codes == (
            "completion-source-not-staging-completion-approved",
        )
        assert blocked_source.staging_complete is False

        recovery_action_only = _policy(
            source,
            allowed_source_actions=("finalize_existing_state",),
        )
        blocked_action = _evaluate(source, recovery_action_only)
        assert blocked_action.source_action_policy_satisfied is False
        assert blocked_action.blocker_codes == (
            "completion-action-not-staging-completion-approved",
        )
        assert blocked_action.staging_complete is False

        wrong_repo = readiness.PilotExactTaskStagingCompletionPolicy(
            repository="other/ModelRig",
            repository_id=source.repository_id,
            staging_environment="staging",
        )
        _reject(lambda: _evaluate(source, wrong_repo))
        _reject(lambda: _evaluate(source, policy, digest="a" * 64))
        _reject(lambda: _evaluate(source, policy, now="2026-09-15T09:51:49Z"))

        for kwargs in (
            {"max_attestation_age_seconds": 61},
            {"max_attestation_age_seconds": 0},
            {"require_durable_completion": False},
            {"require_runtime_build_identity_binding": False},
            {"require_exact_success_status": False},
            {"staging_environment": "production"},
            {"allowed_completion_sources": ("transaction", "recovery")},
        ):
            values = {
                "repository": source.repository,
                "repository_id": source.repository_id,
                "staging_environment": "staging",
            }
            values.update(kwargs)
            _reject(lambda values=values: readiness.PilotExactTaskStagingCompletionPolicy(**values))

        parsed = readiness._parse_policy(policy.canonical_json().encode("utf-8"))
        assert parsed == policy
        _reject(lambda: readiness._parse_policy((policy.canonical_json() + "\n").encode("utf-8")))

        for field, value in (
            ("post_success_attestation_authenticated", False),
            ("staging_completion_policy_host_pinned", False),
            ("durable_completion_satisfied", False),
            ("runtime_build_identity_binding_satisfied", False),
            ("exact_success_status_satisfied", False),
            ("staging_completion_evaluated", False),
            ("staging_complete", False),
            ("next_boundary_ready", False),
            ("staging_completion_authorized", True),
            ("production_promotion_authorized", True),
            ("production_deployment_authorized", True),
            ("production_activation_authorized", True),
            ("deployment_status_mutation_authorized", True),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("remote_write_authorized", True),
            ("release_authorized", True),
            ("merge_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
            ("attestation_age_seconds", 61),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: readiness.PilotExactTaskStagingCompletionReadinessReceipt.from_mapping(
                    raw
                )
            )
    finally:
        _cleanup_normal(bundle, auth_temp, tx_temp, recovery_temp)

    # The write-free ADR-DC-089 path is equally eligible under the default policy.
    fixture = post_contract.recovery_contract._auth_fixture()
    recovery_temp, recovery_ledger = post_contract.recovery_contract._recovery_ledger(
        "rsi-staging-completion-readiness-recovered-"
    )
    try:
        (
            _bundle,
            _plan,
            authorization,
            _auth_temp,
            auth_ledger,
            _tx_temp,
            tx_ledger,
        ) = fixture
        state, _ = post_contract.recovery_contract._inspect(
            authorization,
            auth_ledger,
            tx_ledger,
            post_contract.recovery_contract._Transport(authorization),
        )
        payload = post_contract.recovery_contract._payload(state)
        verifier, op_sig, review_sig = (
            post_contract.recovery_contract.deploy_auth_contract._dual_authority(
                payload,
                signed_at="2026-09-15T09:51:32Z",
            )
        )
        post_contract.recovery_contract._recover(
            payload,
            verifier,
            op_sig,
            review_sig,
            auth_ledger,
            tx_ledger,
            recovery_ledger,
            post_contract.recovery_contract._Transport(authorization),
        )
        source = post_contract._attest(
            authorization,
            tx_root=tx_ledger.root,
            recovery_root=recovery_ledger.root,
            auth_root=auth_ledger.root,
            transport=post_contract.recovery_contract._Transport(authorization),
        )
        assert source.success_status_completion_source == "recovery"
        assert source.success_status_source_action == "finalize_existing_state"
        receipt = _evaluate(source, _policy(source))
        assert receipt.staging_complete is True
        assert receipt.next_boundary_ready is True
        assert receipt.completion_source_policy_satisfied is True
        assert receipt.source_action_policy_satisfied is True
        _assert_inert(receipt)
    finally:
        recovery_temp.cleanup()
        post_contract.recovery_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(readiness.PilotExactTaskStagingCompletionReadinessReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 74

    signature = inspect.signature(
        readiness.evaluate_pilot_exact_task_staging_completion_readiness
    )
    assert list(signature.parameters) == ["post_staging_success_status_attestation"]

    source_text = SOURCE.read_text(encoding="utf-8")
    assert "urllib.request" not in source_text
    assert "subprocess" not in source_text
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
    assert "production_promotion_authorized: bool = False" in source_text
    assert "production_deployment_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text
    assert "remote_write_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
