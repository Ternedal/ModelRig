"""Adversarial contract for ADR-DC-093 production Deployment state observation."""
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
from source_code import code_of  # noqa: E402

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_production_deployment_plan as production_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_production_deployment_state_observation as production_state,
)
import rsi_pilot_exact_task_production_deployment_plan_contract as plan_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-production-deployment-state-observation-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_production_deployment_state_observation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-093 unexpectedly accepted unsafe production Deployment state"
    )


def _live_plan():
    readiness_contract = plan_contract.readiness_contract
    post_source, bundle, auth_temp, tx_temp, recovery_temp = (
        readiness_contract._normal_source()
    )
    readiness = readiness_contract._evaluate(
        post_source,
        readiness_contract._policy(post_source),
    )
    plan = plan_contract._plan(readiness, plan_contract._config(readiness))
    assert readiness.evaluation_authenticated is True
    assert plan.plan_authenticated is True
    return (
        plan,
        readiness,
        bundle,
        auth_temp,
        tx_temp,
        recovery_temp,
    )


class _Transport:
    def __init__(
        self,
        plan,
        readiness,
        *,
        state_class="clear",
        deployment_id=5252,
        node_hash="e" * 64,
        deployment_sha=None,
        payload_sha=None,
        description_sha=None,
        scripted=None,
    ):
        self.plan = plan
        self.credential_config_sha256 = readiness.publisher_credential_config_sha256
        self.credential_path_sha256 = readiness.publisher_credential_path_sha256
        self.state_class = state_class
        self.deployment_id = deployment_id
        self.node_hash = node_hash
        self.deployment_sha = (
            plan.merge_commit_sha if deployment_sha is None else deployment_sha
        )
        self.payload_sha = (
            plan.production_deployment_payload_sha256
            if payload_sha is None
            else payload_sha
        )
        self.description_sha = (
            plan.production_deployment_description_sha256
            if description_sha is None
            else description_sha
        )
        self.scripted = list(scripted or ())
        self.calls = 0

    def _state(self, state_class):
        if state_class == "clear":
            return production_state._RemoteProductionDeploymentState(
                repository=self.plan.repository,
                repository_id=self.plan.repository_id,
                merge_commit_sha=self.plan.merge_commit_sha,
                deployment_environment="production",
                deployment_ref=self.plan.production_deployment_ref,
                deployment_task="deploy",
                deployment_state="absent",
                deployment_id=None,
                deployment_node_id_sha256=None,
                deployment_sha=None,
                observed_payload_sha256=None,
                observed_description_sha256=None,
                transient_environment=None,
                production_environment=None,
                remote_state_class="clear",
            )
        if state_class != "exact-existing":
            raise AssertionError("unsupported ADR-DC-093 test state")
        return production_state._RemoteProductionDeploymentState(
            repository=self.plan.repository,
            repository_id=self.plan.repository_id,
            merge_commit_sha=self.plan.merge_commit_sha,
            deployment_environment="production",
            deployment_ref=self.plan.production_deployment_ref,
            deployment_task="deploy",
            deployment_state="exact",
            deployment_id=self.deployment_id,
            deployment_node_id_sha256=self.node_hash,
            deployment_sha=self.deployment_sha,
            observed_payload_sha256=self.payload_sha,
            observed_description_sha256=self.description_sha,
            transient_environment=False,
            production_environment=True,
            remote_state_class="exact-existing",
        )

    def observe(self, plan):
        self.calls += 1
        assert plan.sha256 == self.plan.sha256
        state = self.scripted.pop(0) if self.scripted else self.state_class
        return self._state(state)


def _observe(plan, transport, *, now="2026-09-15T09:52:40Z"):
    return production_state._observe_verified_pilot_exact_task_production_deployment_state(
        production_deployment_plan=plan,
        transport=transport,
        now_provider=lambda: now,
    )


def _assert_inert(receipt) -> None:
    assert receipt.production_deployment_plan_authenticated is True
    assert receipt.remote_state_observed is True
    assert receipt.remote_repository_verified is True
    assert receipt.exact_merge_commit_verified is True
    assert receipt.deployment_inventory_bounded is True
    assert receipt.deployment_state_verified is True
    assert receipt.double_observation_matched is True
    assert receipt.deployment_state_acceptable is True
    assert receipt.production_promotion_authorized is False
    assert receipt.production_deployment_authorized is False
    assert receipt.production_activation_authorized is False
    assert receipt.deployment_status_mutation_authorized is False
    assert receipt.deployment_mutation_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.release_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.nonce_reusable is False


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        plan,
        readiness,
        bundle,
        auth_temp,
        tx_temp,
        recovery_temp,
    ) = _live_plan()
    try:
        clear_transport = _Transport(plan, readiness)
        clear = _observe(plan, clear_transport)
        assert clear.observation_authenticated is True
        assert clear.production_deployment_plan_sha256 == plan.sha256
        assert clear.production_deployment_intent_sha256 == (
            plan.production_deployment_intent_sha256
        )
        assert clear.staging_runtime_build_identity_sha256 == (
            plan.staging_runtime_build_identity_sha256
        )
        assert clear.publisher_credential_config_sha256 == (
            readiness.publisher_credential_config_sha256
        )
        assert clear.publisher_credential_path_sha256 == (
            readiness.publisher_credential_path_sha256
        )
        assert clear.remote_state_class == "clear"
        assert clear.deployment_state == "absent"
        assert clear.deployment_id is None
        assert clear.deployment_lane_clear is True
        assert clear.exact_existing_deployment is False
        assert clear.source_completion_source == "transaction"
        assert clear.source_completion_action == (
            "execute_exact_staging_success_status"
        )
        assert clear.source_remote_write_performed is True
        assert clear_transport.calls == 2
        _assert_inert(clear)

        exact_transport = _Transport(plan, readiness, state_class="exact-existing")
        exact = _observe(plan, exact_transport, now="2026-09-15T09:52:41Z")
        assert exact.observation_authenticated is True
        assert exact.remote_state_class == "exact-existing"
        assert exact.deployment_state == "exact"
        assert exact.deployment_id == 5252
        assert exact.deployment_node_id_sha256 == "e" * 64
        assert exact.deployment_sha == plan.merge_commit_sha
        assert exact.observed_payload_sha256 == (
            plan.production_deployment_payload_sha256
        )
        assert exact.observed_description_sha256 == (
            plan.production_deployment_description_sha256
        )
        assert exact.transient_environment is False
        assert exact.production_environment is True
        assert exact.deployment_lane_clear is False
        assert exact.exact_existing_deployment is True
        assert exact_transport.calls == 2
        _assert_inert(exact)

        serialized = (
            production_state.PilotExactTaskProductionDeploymentStateObservationReceipt.from_mapping(
                clear.to_dict()
            )
        )
        assert serialized == clear
        assert serialized.observation_authenticated is False

        stale_plan = production_plan.PilotExactTaskProductionDeploymentPlanReceipt.from_mapping(
            plan.to_dict()
        )
        assert stale_plan.plan_authenticated is False
        _reject(lambda: _observe(stale_plan, _Transport(plan, readiness)))

        credential = _Transport(plan, readiness)
        credential.credential_path_sha256 = "8" * 64
        _reject(lambda: _observe(plan, credential))
        assert credential.calls == 0

        _reject(
            lambda: _observe(
                plan,
                _Transport(
                    plan,
                    readiness,
                    state_class="exact-existing",
                    deployment_sha="a" * 40,
                ),
            )
        )
        _reject(
            lambda: _observe(
                plan,
                _Transport(
                    plan,
                    readiness,
                    state_class="exact-existing",
                    payload_sha="b" * 64,
                ),
            )
        )
        _reject(
            lambda: _observe(
                plan,
                _Transport(
                    plan,
                    readiness,
                    state_class="exact-existing",
                    description_sha="c" * 64,
                ),
            )
        )
        race = _Transport(
            plan,
            readiness,
            scripted=["clear", "exact-existing"],
        )
        _reject(lambda: _observe(plan, race))
        assert race.calls == 2
        _reject(
            lambda: _observe(
                plan,
                _Transport(plan, readiness),
                now="2026-09-15T09:52:29Z",
            )
        )

        for field, value in (
            ("production_deployment_plan_authenticated", False),
            ("remote_state_observed", False),
            ("remote_repository_verified", False),
            ("exact_merge_commit_verified", False),
            ("deployment_inventory_bounded", False),
            ("deployment_state_verified", False),
            ("double_observation_matched", False),
            ("deployment_state_acceptable", False),
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
            ("source_completion_action", "finalize_existing_state"),
            ("source_remote_write_performed", False),
        ):
            raw = clear.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: (
                    production_state.PilotExactTaskProductionDeploymentStateObservationReceipt.from_mapping(
                        raw
                    )
                )
            )

        _reject(
            lambda: production_state.PilotExactTaskProductionDeploymentStateObservationReceipt.from_mapping(
                {
                    **clear.to_dict(),
                    "remote_state_class": "exact-existing",
                    "deployment_state": "exact",
                }
            )
        )
        _reject(
            lambda: production_state.PilotExactTaskProductionDeploymentStateObservationReceipt.from_mapping(
                {
                    **exact.to_dict(),
                    "observed_payload_sha256": "f" * 64,
                }
            )
        )
    finally:
        plan_contract.readiness_contract._cleanup_normal(
            bundle,
            auth_temp,
            tx_temp,
            recovery_temp,
        )

    schema = json.loads(code_of(SCHEMA))
    fields = set(
        production_state.PilotExactTaskProductionDeploymentStateObservationReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 64

    signature = inspect.signature(
        production_state.observe_pilot_exact_task_production_deployment_state
    )
    assert list(signature.parameters) == ["production_deployment_plan"]

    source_text = code_of(SOURCE)
    assert 'method="GET"' in source_text
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
    assert "/deployments?" in source_text
    assert "multiple GitHub Deployments occupy deterministic production lane" in source_text
    assert "create_deployment" not in source_text
    assert "create_deployment_status" not in source_text
    assert "production_deployment_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
