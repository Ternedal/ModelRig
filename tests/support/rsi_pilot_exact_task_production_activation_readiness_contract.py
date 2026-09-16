"""Adversarial contract for ADR-DC-091 production-activation readiness."""
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

from kaliv_dev_control import improvement_pilot_exact_task_production_activation_readiness as readiness  # noqa: E402
import rsi_pilot_exact_task_post_staging_success_status_attestation_contract as attestation_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_recovery_contract as recovery_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_transaction_contract as tx_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-production-activation-readiness-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_production_activation_readiness.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-091 unexpectedly accepted unsafe production readiness")


def _policy(source, **overrides):
    values = dict(
        repository=source.repository,
        repository_id=source.repository_id,
        source_environment="staging",
        target_environment="production",
        allowed_completion_sources=("recovery", "transaction"),
        allowed_source_actions=("execute_exact_staging_success_status", "finalize_existing_state"),
        max_attestation_age_seconds=900,
    )
    values.update(overrides)
    return readiness.PilotExactTaskProductionActivationReadinessPolicy(**values)


def _evaluate(source, policy, *, now="2026-09-15T09:52:00Z"):
    return readiness._evaluate_verified_pilot_exact_task_production_activation_readiness(
        post_staging_success_status_attestation=source,
        policy=policy,
        policy_sha256=policy.sha256,
        now_provider=lambda: now,
    )


def _normal_source():
    bundle, plan, auth_temp, authorization = tx_contract._authorization()
    tx_temp, tx_ledger = tx_contract._ledger("rsi-production-ready-tx-")
    recovery_temp, recovery_root = attestation_contract._empty_recovery_ledger("rsi-production-ready-empty-recovery-")
    status_id = authorization.current_deployment_status_id + 1
    tx_receipt = tx_contract._execute(
        authorization,
        tx_ledger,
        tx_contract._observer(plan, status_id=status_id),
        tx_contract._Writer(authorization, status_id=status_id),
    )
    transport = recovery_contract._Transport(
        authorization,
        states=[attestation_contract._normal_state(authorization)],
    )
    source = attestation_contract._attest(
        authorization,
        tx_root=tx_ledger.root,
        recovery_root=recovery_root,
        auth_root=Path(auth_temp.name) / "ledger",
        transport=transport,
    )
    return bundle, auth_temp, tx_temp, recovery_temp, source


def _cleanup_normal(fixture) -> None:
    bundle, auth_temp, tx_temp, recovery_temp, _source = fixture
    recovery_temp.cleanup()
    tx_temp.cleanup()
    tx_contract._cleanup(bundle, auth_temp)


def _recovered_source():
    fixture = recovery_contract._auth_fixture()
    recovery_temp, recovery_ledger = recovery_contract._recovery_ledger("rsi-production-ready-recovery-")
    (_bundle, _plan, authorization, _auth_temp, auth_ledger, _tx_temp, tx_ledger) = fixture
    state, durable_authorization = recovery_contract._inspect(
        authorization,
        auth_ledger,
        tx_ledger,
        recovery_contract._Transport(authorization),
    )
    assert durable_authorization.sha256 == authorization.sha256
    payload = recovery_contract._payload(state)
    verifier, op_sig, review_sig = recovery_contract.deploy_auth_contract._dual_authority(
        payload, signed_at="2026-09-15T09:51:32Z"
    )
    recovery_receipt = recovery_contract._recover(
        payload,
        verifier,
        op_sig,
        review_sig,
        auth_ledger,
        tx_ledger,
        recovery_ledger,
        recovery_contract._Transport(authorization),
    )
    assert recovery_receipt.recovery_authenticated is True
    source = attestation_contract._attest(
        authorization,
        tx_root=tx_ledger.root,
        recovery_root=recovery_ledger.root,
        auth_root=auth_ledger.root,
        transport=recovery_contract._Transport(authorization),
    )
    return fixture, recovery_temp, source


def _cleanup_recovered(value) -> None:
    fixture, recovery_temp, _source = value
    recovery_temp.cleanup()
    recovery_contract._cleanup(fixture)


def _assert_inert(receipt) -> None:
    assert receipt.production_activation_readiness_evaluated is True
    assert receipt.production_activation_readiness_authorized is False
    assert receipt.success_deployment_status_authorized is False
    assert receipt.deployment_status_mutation_authorized is False
    assert receipt.deployment_mutation_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.release_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.production_activation_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.nonce_reusable is False


def run_contract() -> None:
    if os.name == "nt":
        return

    normal = _normal_source()
    try:
        source = normal[-1]
        assert source.attestation_authenticated is True
        policy = _policy(source)
        receipt = _evaluate(source, policy)
        assert receipt.evaluation_authenticated is True
        assert receipt.production_activation_ready is True
        assert receipt.blocker_codes == ()
        assert receipt.source_environment == "staging"
        assert receipt.target_environment == "production"
        assert receipt.staging_runtime_build_identity_sha256 == source.staging_runtime_build_identity_sha256
        assert receipt.post_staging_success_status_attestation_sha256 == source.sha256
        assert receipt.production_activation_candidate_sha256 != source.sha256
        assert receipt.completion_source_policy_satisfied is True
        assert receipt.source_action_policy_satisfied is True
        assert receipt.attestation_freshness_policy_satisfied is True
        _assert_inert(receipt)

        serialized = readiness.PilotExactTaskProductionActivationReadinessReceipt.from_mapping(receipt.to_dict())
        assert serialized == receipt
        assert serialized.evaluation_authenticated is False

        stale_source = attestation_contract.attestation.PilotExactTaskPostStagingSuccessStatusAttestationReceipt.from_mapping(source.to_dict())
        assert stale_source.attestation_authenticated is False
        _reject(lambda: _evaluate(stale_source, policy))

        source_block_policy = _policy(source, allowed_completion_sources=("recovery",))
        blocked = _evaluate(source, source_block_policy)
        assert blocked.production_activation_ready is False
        assert blocked.blocker_codes == ("completion-source-not-production-approved",)
        _assert_inert(blocked)

        action_block_policy = _policy(source, allowed_source_actions=("finalize_existing_state",))
        action_blocked = _evaluate(source, action_block_policy)
        assert action_blocked.production_activation_ready is False
        assert action_blocked.blocker_codes == ("completion-action-not-production-approved",)

        freshness_policy = _policy(source, max_attestation_age_seconds=5)
        expired = _evaluate(source, freshness_policy, now="2026-09-15T09:52:00Z")
        assert expired.production_activation_ready is False
        assert expired.blocker_codes == ("staging-success-attestation-too-old",)

        _reject(lambda: _evaluate(source, policy, now="2026-09-15T09:51:49Z"))
        _reject(lambda: _policy(source, repository="other/repo"))
        _reject(lambda: _policy(source, target_environment="staging"))
        _reject(lambda: _policy(source, require_exact_staging_success=False))
        _reject(lambda: _policy(source, require_runtime_build_identity_binding=False))
        _reject(lambda: _policy(source, require_no_residual_mutation_authority=False))

        for field, value in (
            ("production_activation_candidate_sha256", "a" * 64),
            ("production_activation_readiness_authorized", True),
            ("production_activation_authorized", True),
            ("remote_write_authorized", True),
            ("deploy_authorized", True),
            ("target_environment", "staging"),
            ("exact_staging_success_satisfied", False),
            ("runtime_build_identity_bound", False),
            ("no_residual_mutation_authority_satisfied", False),
            ("production_activation_ready", False),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(lambda raw=raw: readiness.PilotExactTaskProductionActivationReadinessReceipt.from_mapping(raw))
    finally:
        _cleanup_normal(normal)

    recovered = _recovered_source()
    try:
        source = recovered[-1]
        assert source.success_status_completion_source == "recovery"
        receipt = _evaluate(source, _policy(source))
        assert receipt.evaluation_authenticated is True
        assert receipt.production_activation_ready is True
        assert receipt.success_status_completion_source == "recovery"
        assert receipt.success_status_source_action == "finalize_existing_state"
        assert receipt.success_status_source_remote_write_performed is False
        assert receipt.success_status_recovery_lock_sha256 is not None
        _assert_inert(receipt)
    finally:
        _cleanup_recovered(recovered)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(readiness.PilotExactTaskProductionActivationReadinessReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 66

    signature = inspect.signature(readiness.evaluate_pilot_exact_task_production_activation_readiness)
    assert list(signature.parameters) == ["post_staging_success_status_attestation"]

    source_text = SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        'method="POST"', "method='POST'", 'method="PUT"', "method='PUT'",
        'method="PATCH"', "method='PATCH'", 'method="DELETE"', "method='DELETE'",
        "urllib.request", "subprocess", "create_once_file", "create_deployment_status",
    ):
        assert forbidden not in source_text
    assert "production_activation_readiness_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text
    assert "remote_write_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
