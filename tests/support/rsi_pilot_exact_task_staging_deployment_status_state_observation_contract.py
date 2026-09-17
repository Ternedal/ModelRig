"""Adversarial contract for ADR-DC-078 read-only Deployment Status observation."""
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
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_status_plan as status_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_deployment_status_state_observation as status_state,
)
import rsi_pilot_exact_task_staging_deployment_status_plan_contract as plan_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-staging-deployment-status-state-observation-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_deployment_status_state_observation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError(
        "ADR-DC-078 unexpectedly accepted unsafe Deployment Status state"
    )


def _normal_plan():
    context = plan_contract._normal_attestation()
    attestation = context[-1]
    config = plan_contract._config(attestation)
    plan = plan_contract._plan(attestation, config)
    assert plan.plan_authenticated is True
    return context, plan


def _recovered_plan():
    context = plan_contract._recovered_attestation()
    attestation = context[-1]
    config = plan_contract._config(attestation)
    plan = plan_contract._plan(attestation, config)
    assert plan.plan_authenticated is True
    return context, plan


def _cleanup(context) -> None:
    plan_contract._cleanup(context)


class _Transport:
    def __init__(
        self,
        plan,
        *,
        state_class="clear",
        deployment_id=None,
        deployment_node_hash=None,
        status_id=5151,
        status_node_hash="a" * 64,
        status_state=None,
        status_environment=None,
        description_sha=None,
        log_url=None,
        environment_url=None,
        created_at="2026-09-15T09:49:56Z",
        updated_at="2026-09-15T09:49:57Z",
        scripted=None,
    ):
        self.plan_sha256 = plan.sha256
        self.credential_config_sha256 = plan.publisher_credential_config_sha256
        self.credential_path_sha256 = plan.publisher_credential_path_sha256
        self.state_class = state_class
        self.deployment_id = plan.deployment_id if deployment_id is None else deployment_id
        self.deployment_node_hash = (
            plan.deployment_node_id_sha256
            if deployment_node_hash is None
            else deployment_node_hash
        )
        self.status_id = status_id
        self.status_node_hash = status_node_hash
        self.status_state = (
            plan.deployment_status_state if status_state is None else status_state
        )
        self.status_environment = (
            plan.deployment_status_environment
            if status_environment is None
            else status_environment
        )
        self.description_sha = (
            plan.deployment_status_description_sha256
            if description_sha is None
            else description_sha
        )
        self.log_url = log_url
        self.environment_url = environment_url
        self.created_at = created_at
        self.updated_at = updated_at
        self.scripted = list(scripted or ())
        self.calls = 0

    def _state(self, plan, state_class):
        if state_class == "clear":
            return status_state._RemoteStagingDeploymentStatusState(
                repository=plan.repository,
                repository_id=plan.repository_id,
                deployment_id=self.deployment_id,
                deployment_node_id_sha256=self.deployment_node_hash,
                deployment_status_lane_state="absent",
                deployment_status_id=None,
                deployment_status_node_id_sha256=None,
                observed_status_state=None,
                observed_status_environment=None,
                observed_status_description_sha256=None,
                observed_status_log_url=None,
                observed_status_environment_url=None,
                status_created_at_utc=None,
                status_updated_at_utc=None,
                remote_state_class="clear",
            )
        if state_class != "exact-existing":
            raise AssertionError("unsupported ADR-DC-078 synthetic state")
        return status_state._RemoteStagingDeploymentStatusState(
            repository=plan.repository,
            repository_id=plan.repository_id,
            deployment_id=self.deployment_id,
            deployment_node_id_sha256=self.deployment_node_hash,
            deployment_status_lane_state="exact",
            deployment_status_id=self.status_id,
            deployment_status_node_id_sha256=self.status_node_hash,
            observed_status_state=self.status_state,
            observed_status_environment=self.status_environment,
            observed_status_description_sha256=self.description_sha,
            observed_status_log_url=self.log_url,
            observed_status_environment_url=self.environment_url,
            status_created_at_utc=self.created_at,
            status_updated_at_utc=self.updated_at,
            remote_state_class="exact-existing",
        )

    def observe(self, plan):
        self.calls += 1
        assert plan.sha256 == self.plan_sha256
        state_class = self.scripted.pop(0) if self.scripted else self.state_class
        return self._state(plan, state_class)


def _observe(plan, transport, *, now="2026-09-15T09:49:58Z"):
    return status_state._observe_verified_pilot_exact_task_staging_deployment_status_state(
        staging_deployment_status_plan=plan,
        transport=transport,
        now_provider=lambda: now,
    )


class _InventoryProbe(
    status_state._GitHubStagingDeploymentStatusStateObserver
):
    def __init__(self, pages):
        self.pages = list(pages)

    def _api_json(self, *, plan, path):
        assert "/statuses?" in path
        return self.pages.pop(0)


def run_contract() -> None:
    if os.name == "nt":
        return

    context, plan = _normal_plan()
    try:
        clear_transport = _Transport(plan)
        clear = _observe(plan, clear_transport)
        assert clear_transport.calls == 2
        assert clear.observation_authenticated is True
        assert clear.staging_deployment_status_plan_sha256 == plan.sha256
        assert clear.deployment_status_intent_sha256 == plan.deployment_status_intent_sha256
        assert clear.deployment_id == plan.deployment_id
        assert clear.deployment_node_id_sha256 == plan.deployment_node_id_sha256
        assert clear.deployment_status_state_planned == "in_progress"
        assert clear.deployment_status_environment_planned == "staging"
        assert clear.deployment_status_auto_inactive_planned is False
        assert clear.deployment_status_log_url_planned is None
        assert clear.deployment_status_environment_url_planned is None
        assert clear.deployment_status_lane_state == "absent"
        assert clear.remote_state_class == "clear"
        assert clear.deployment_status_id is None
        assert clear.status_lane_clear is True
        assert clear.exact_existing_status is False
        assert clear.deployment_status_mutation_authorized is False
        assert clear.remote_write_authorized is False
        assert clear.production_activation_authorized is False
        assert clear.nonce_reusable is False

        serialized = status_state.PilotExactTaskStagingDeploymentStatusStateObservationReceipt.from_mapping(
            clear.to_dict()
        )
        assert serialized == clear
        assert serialized.observation_authenticated is False

        exact_transport = _Transport(plan, state_class="exact-existing")
        exact = _observe(plan, exact_transport)
        assert exact_transport.calls == 2
        assert exact.observation_authenticated is True
        assert exact.deployment_status_lane_state == "exact"
        assert exact.remote_state_class == "exact-existing"
        assert exact.deployment_status_id == 5151
        assert exact.deployment_status_node_id_sha256 == "a" * 64
        assert exact.observed_status_state == "in_progress"
        assert exact.observed_status_environment == "staging"
        assert (
            exact.observed_status_description_sha256
            == plan.deployment_status_description_sha256
        )
        assert exact.observed_status_log_url is None
        assert exact.observed_status_environment_url is None
        assert exact.status_lane_clear is False
        assert exact.exact_existing_status is True
        assert exact.deployment_status_mutation_authorized is False
        assert exact.production_activation_authorized is False

        stale_plan = status_plan.PilotExactTaskStagingDeploymentStatusPlanReceipt.from_mapping(
            plan.to_dict()
        )
        assert stale_plan.plan_authenticated is False
        _reject(lambda: _observe(stale_plan, _Transport(plan)))

        credential_drift = _Transport(plan)
        credential_drift.credential_path_sha256 = "8" * 64
        _reject(lambda: _observe(plan, credential_drift))
        assert credential_drift.calls == 0

        wrong_parent = _Transport(plan, deployment_id=plan.deployment_id + 1)
        _reject(lambda: _observe(plan, wrong_parent))

        wrong_state = _Transport(
            plan,
            state_class="exact-existing",
            status_state="success",
        )
        _reject(lambda: _observe(plan, wrong_state))

        wrong_environment = _Transport(
            plan,
            state_class="exact-existing",
            status_environment="production",
        )
        _reject(lambda: _observe(plan, wrong_environment))

        wrong_description = _Transport(
            plan,
            state_class="exact-existing",
            description_sha="b" * 64,
        )
        _reject(lambda: _observe(plan, wrong_description))

        forbidden_log = _Transport(
            plan,
            state_class="exact-existing",
            log_url="https://example.invalid/log",
        )
        _reject(lambda: _observe(plan, forbidden_log))

        race = _Transport(
            plan,
            scripted=["clear", "exact-existing"],
        )
        _reject(lambda: _observe(plan, race))
        assert race.calls == 2

        _reject(
            lambda: _observe(
                plan,
                _Transport(plan),
                now="2026-09-15T09:49:49Z",
            )
        )

        duplicate_probe = _InventoryProbe(
            [[{"id": 1}, {"id": 2}]]
        )
        _reject(lambda: duplicate_probe._list_statuses(plan))

        for field, value in (
            ("status_state_acceptable", False),
            ("deployment_status_mutation_authorized", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
        ):
            raw = clear.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: status_state.PilotExactTaskStagingDeploymentStatusStateObservationReceipt.from_mapping(
                    raw
                )
            )
    finally:
        _cleanup(context)

    recovered_context, recovered_plan = _recovered_plan()
    try:
        transport = _Transport(recovered_plan)
        receipt = _observe(recovered_plan, transport)
        assert receipt.observation_authenticated is True
        assert receipt.completion_source == "recovery"
        assert receipt.source_action == "finalize_existing_state"
        assert receipt.source_remote_write_performed is False
        assert receipt.recovery_lock_sha256 is not None
        assert receipt.remote_state_class == "clear"
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
    finally:
        _cleanup(recovered_context)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    dataclass_fields = set(
        status_state.PilotExactTaskStagingDeploymentStatusStateObservationReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == dataclass_fields
    assert set(schema["properties"]) == dataclass_fields
    assert len(dataclass_fields) == 84

    signature = inspect.signature(
        status_state.observe_pilot_exact_task_staging_deployment_status_state
    )
    assert list(signature.parameters) == ["staging_deployment_status_plan"]

    source = code_of(SOURCE)
    for forbidden in (
        'method="POST"', "method='POST'",
        'method="PUT"', "method='PUT'",
        'method="PATCH"', "method='PATCH'",
        'method="DELETE"', "method='DELETE'",
    ):
        assert forbidden not in source
    assert 'method="GET"' in source
    assert "/statuses?" in source
    assert "create_once_file" not in source


if __name__ == "__main__":
    run_contract()
