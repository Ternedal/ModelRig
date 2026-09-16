"""Adversarial contract for ADR-DC-072 exact staging deployment-state observation."""
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
    improvement_pilot_exact_task_staging_deployment_plan as deploy_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_state_observation as deploy_state,
)
import rsi_pilot_exact_task_deploy_readiness_evaluation_contract as ready_contract  # noqa: E402
import rsi_pilot_exact_task_staging_deployment_plan_contract as plan_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-staging-deployment-state-observation-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_deployment_state_observation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-072 unexpectedly accepted unsafe deployment state")


def _live_plan():
    items, readiness = plan_contract._live_readiness()
    config = plan_contract._config(readiness)
    plan = plan_contract._materialize(readiness, config)
    assert plan.plan_authenticated is True
    return items, readiness, plan


class _Transport:
    def __init__(
        self,
        plan,
        readiness,
        *,
        state_class: str = "clear",
        deployment_id: int = 4242,
        node_hash: str = "d" * 64,
        deployment_sha: str | None = None,
        payload_sha: str | None = None,
        description_sha: str | None = None,
        scripted: list[str] | None = None,
    ):
        self.plan = plan
        self.credential_config_sha256 = readiness.publisher_credential_config_sha256
        self.credential_path_sha256 = readiness.publisher_credential_path_sha256
        self.state_class = state_class
        self.deployment_id = deployment_id
        self.node_hash = node_hash
        self.deployment_sha = plan.merge_commit_sha if deployment_sha is None else deployment_sha
        self.payload_sha = plan.deployment_payload_sha256 if payload_sha is None else payload_sha
        self.description_sha = (
            plan.deployment_description_sha256
            if description_sha is None
            else description_sha
        )
        self.scripted = list(scripted or ())
        self.calls = 0

    def _state(self, state_class: str):
        if state_class == "clear":
            return deploy_state._RemoteStagingDeploymentState(
                repository=self.plan.repository,
                repository_id=self.plan.repository_id,
                tag_target_sha=self.plan.tag_target_sha,
                deployment_environment="staging",
                deployment_ref=self.plan.deployment_ref,
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
            raise AssertionError("unsupported ADR-DC-072 test state")
        return deploy_state._RemoteStagingDeploymentState(
            repository=self.plan.repository,
            repository_id=self.plan.repository_id,
            tag_target_sha=self.plan.tag_target_sha,
            deployment_environment="staging",
            deployment_ref=self.plan.deployment_ref,
            deployment_task="deploy",
            deployment_state="exact",
            deployment_id=self.deployment_id,
            deployment_node_id_sha256=self.node_hash,
            deployment_sha=self.deployment_sha,
            observed_payload_sha256=self.payload_sha,
            observed_description_sha256=self.description_sha,
            transient_environment=False,
            production_environment=False,
            remote_state_class="exact-existing",
        )

    def observe(self, plan):
        self.calls += 1
        assert plan.sha256 == self.plan.sha256
        state = self.scripted.pop(0) if self.scripted else self.state_class
        return self._state(state)


def _observe(plan, transport, *, now="2026-09-15T09:49:00Z"):
    return deploy_state._observe_verified_pilot_exact_task_staging_deployment_state(
        staging_deployment_plan=plan,
        transport=transport,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    items, readiness, plan = _live_plan()
    try:
        clear_transport = _Transport(plan, readiness)
        clear = _observe(plan, clear_transport)
        assert clear.observation_authenticated is True
        assert clear.staging_deployment_plan_sha256 == plan.sha256
        assert clear.deployment_intent_sha256 == plan.deployment_intent_sha256
        assert clear.publisher_credential_config_sha256 == readiness.publisher_credential_config_sha256
        assert clear.publisher_credential_path_sha256 == readiness.publisher_credential_path_sha256
        assert clear.remote_state_class == "clear"
        assert clear.deployment_state == "absent"
        assert clear.deployment_id is None
        assert clear.deployment_node_id_sha256 is None
        assert clear.deployment_lane_clear is True
        assert clear.exact_existing_deployment is False
        assert clear.deploy_authorized is False
        assert clear.deployment_mutation_authorized is False
        assert clear.remote_write_authorized is False
        assert clear.production_activation_authorized is False
        assert clear_transport.calls == 2

        exact_transport = _Transport(plan, readiness, state_class="exact-existing")
        exact = _observe(plan, exact_transport, now="2026-09-15T09:49:01Z")
        assert exact.observation_authenticated is True
        assert exact.remote_state_class == "exact-existing"
        assert exact.deployment_state == "exact"
        assert exact.deployment_id == 4242
        assert exact.deployment_node_id_sha256 == "d" * 64
        assert exact.deployment_sha == plan.merge_commit_sha
        assert exact.observed_payload_sha256 == plan.deployment_payload_sha256
        assert exact.observed_description_sha256 == plan.deployment_description_sha256
        assert exact.deployment_lane_clear is False
        assert exact.exact_existing_deployment is True
        assert exact_transport.calls == 2

        reloaded = (
            deploy_state.PilotExactTaskStagingDeploymentStateObservationReceipt.from_mapping(
                clear.to_dict()
            )
        )
        assert reloaded == clear
        assert reloaded.observation_authenticated is False

        stale = deploy_plan.PilotExactTaskStagingDeploymentPlanReceipt.from_mapping(
            plan.to_dict()
        )
        assert stale.plan_authenticated is False
        _reject(lambda: _observe(stale, _Transport(plan, readiness)))

        cred = _Transport(plan, readiness)
        cred.credential_path_sha256 = "8" * 64
        _reject(lambda: _observe(plan, cred))

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
        _reject(
            lambda: _observe(
                plan,
                _Transport(
                    plan,
                    readiness,
                    scripted=["clear", "exact-existing"],
                ),
            )
        )
        _reject(
            lambda: _observe(
                plan,
                _Transport(plan, readiness),
                now="2026-09-15T09:47:00Z",
            )
        )

        for field, value in (
            ("staging_deployment_plan_authenticated", False),
            ("remote_state_observed", False),
            ("remote_repository_verified", False),
            ("exact_release_tag_verified", False),
            ("deployment_inventory_bounded", False),
            ("deployment_state_verified", False),
            ("double_observation_matched", False),
            ("deployment_state_acceptable", False),
            ("deployment_mutation_authorized", True),
            ("deploy_authorized", True),
            ("remote_write_authorized", True),
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
                    deploy_state.PilotExactTaskStagingDeploymentStateObservationReceipt.from_mapping(
                        {**clear.to_dict(), field: value}
                    )
                )
            )

        _reject(
            lambda: deploy_state.PilotExactTaskStagingDeploymentStateObservationReceipt.from_mapping(
                {
                    **clear.to_dict(),
                    "remote_state_class": "exact-existing",
                    "deployment_state": "exact",
                }
            )
        )
        _reject(
            lambda: deploy_state.PilotExactTaskStagingDeploymentStateObservationReceipt.from_mapping(
                {
                    **exact.to_dict(),
                    "observed_payload_sha256": "e" * 64,
                }
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            deploy_state.PilotExactTaskStagingDeploymentStateObservationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 73

        signature = inspect.signature(
            deploy_state.observe_pilot_exact_task_staging_deployment_state
        )
        assert list(signature.parameters) == ["staging_deployment_plan"]

        source_text = SOURCE.read_text(encoding="utf-8")
        assert 'method="GET"' in source_text
        assert 'method="POST"' not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "/deployments?" in source_text
        assert "multiple GitHub Deployments occupy deterministic staging lane" in source_text
        assert "create_deployment" not in source_text
        assert "create_deployment_status" not in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        ready_contract._cleanup_source(items)


if __name__ == "__main__":
    run_contract()
