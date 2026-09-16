"""Adversarial contract for ADR-DC-086 staging success-status state observation."""
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
    improvement_pilot_exact_task_staging_success_status_state_observation as observation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_success_status_plan as success_plan,
)
import rsi_pilot_exact_task_staging_success_status_plan_contract as plan_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-success-status-state-observation-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_success_status_state_observation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-086 unexpectedly accepted unsafe success-status state")


def _live_plan(*, recovered=False):
    bundle, build_identity = plan_contract._live_build_identity(recovered=recovered)
    plan = plan_contract._plan(build_identity)
    assert plan.plan_authenticated is True
    return bundle, plan


def _state(plan, *, exact=False, **overrides):
    values = {
        "repository": plan.repository,
        "repository_id": plan.repository_id,
        "deployment_id": plan.deployment_id,
        "deployment_node_id_sha256": plan.deployment_node_id_sha256,
        "current_deployment_status_id": plan.current_deployment_status_id,
        "current_deployment_status_node_id_sha256": (
            plan.current_deployment_status_node_id_sha256
        ),
        "success_deployment_status_id": None,
        "success_deployment_status_node_id_sha256": None,
        "observed_success_status_state": None,
        "observed_success_status_environment": None,
        "observed_success_status_description_sha256": None,
        "observed_success_status_log_url": None,
        "observed_success_status_environment_url": None,
        "success_status_created_at_utc": None,
        "success_status_updated_at_utc": None,
        "remote_state_class": "clear",
    }
    if exact:
        values.update(
            {
                "success_deployment_status_id": plan.current_deployment_status_id + 1,
                "success_deployment_status_node_id_sha256": "d" * 64,
                "observed_success_status_state": "success",
                "observed_success_status_environment": "staging",
                "observed_success_status_description_sha256": (
                    plan.success_deployment_status_description_sha256
                ),
                "success_status_created_at_utc": "2026-09-15T09:51:03Z",
                "success_status_updated_at_utc": "2026-09-15T09:51:03Z",
                "remote_state_class": "exact-existing",
            }
        )
    values.update(overrides)
    return observation._RemoteStagingSuccessStatusState(**values)


class _Transport:
    def __init__(self, plan, *, states=None):
        self.plan = plan
        self.credential_config_sha256 = plan.publisher_credential_config_sha256
        self.credential_path_sha256 = plan.publisher_credential_path_sha256
        self.states = list(states or [_state(plan)])
        self.calls = 0

    def observe(self, plan):
        assert plan is self.plan
        self.calls += 1
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


def _observe(plan, transport, *, now="2026-09-15T09:51:10Z"):
    return observation._observe_verified_pilot_exact_task_staging_success_status_state(
        staging_success_status_plan=plan,
        transport=transport,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle, plan = _live_plan()
    try:
        clear_transport = _Transport(plan)
        clear = _observe(plan, clear_transport)
        assert clear_transport.calls == 2
        assert clear.observation_authenticated is True
        assert clear.staging_success_status_plan_sha256 == plan.sha256
        assert clear.staging_runtime_build_identity_sha256 == (
            plan.staging_runtime_build_identity_sha256
        )
        assert clear.success_deployment_status_intent_sha256 == (
            plan.success_deployment_status_intent_sha256
        )
        assert clear.repository == plan.repository
        assert clear.repository_id == plan.repository_id
        assert clear.deployment_id == plan.deployment_id
        assert clear.merge_commit_sha == plan.merge_commit_sha
        assert clear.current_deployment_status_id == plan.current_deployment_status_id
        assert clear.remote_state_class == "clear"
        assert clear.success_status_lane_clear is True
        assert clear.exact_existing_success_status is False
        assert clear.success_deployment_status_id is None
        assert clear.current_in_progress_status_verified is True
        assert clear.success_deployment_status_ready is True
        assert clear.success_deployment_status_authorized is False
        assert clear.deployment_status_mutation_authorized is False
        assert clear.remote_write_authorized is False
        assert clear.production_activation_authorized is False
        assert clear.nonce_reusable is False

        exact_transport = _Transport(plan, states=[_state(plan, exact=True)])
        exact = _observe(plan, exact_transport)
        assert exact_transport.calls == 2
        assert exact.observation_authenticated is True
        assert exact.remote_state_class == "exact-existing"
        assert exact.success_status_lane_clear is False
        assert exact.exact_existing_success_status is True
        assert exact.success_deployment_status_id == plan.current_deployment_status_id + 1
        assert exact.observed_success_status_state == "success"
        assert exact.observed_success_status_environment == "staging"
        assert exact.observed_success_status_description_sha256 == (
            plan.success_deployment_status_description_sha256
        )
        assert exact.success_deployment_status_authorized is False

        serialized = (
            observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(
                clear.to_dict()
            )
        )
        assert serialized == clear
        assert serialized.observation_authenticated is False

        serialized_plan = success_plan.PilotExactTaskStagingSuccessStatusPlanReceipt.from_mapping(
            plan.to_dict()
        )
        assert serialized_plan.plan_authenticated is False
        stale_transport = _Transport(plan)
        _reject(
            lambda: observation._observe_verified_pilot_exact_task_staging_success_status_state(
                staging_success_status_plan=serialized_plan,
                transport=stale_transport,
                now_provider=lambda: "2026-09-15T09:51:10Z",
            )
        )
        assert stale_transport.calls == 0

        wrong_credential = _Transport(plan)
        wrong_credential.credential_config_sha256 = "8" * 64
        _reject(lambda: _observe(plan, wrong_credential))
        assert wrong_credential.calls == 0

        wrong_path = _Transport(plan)
        wrong_path.credential_path_sha256 = "9" * 64
        _reject(lambda: _observe(plan, wrong_path))
        assert wrong_path.calls == 0

        wrong_current = _Transport(
            plan,
            states=[
                _state(
                    plan,
                    current_deployment_status_id=plan.current_deployment_status_id + 50,
                )
            ],
        )
        _reject(lambda: _observe(plan, wrong_current))
        assert wrong_current.calls == 1

        wrong_current_node = _Transport(
            plan,
            states=[
                _state(
                    plan,
                    current_deployment_status_node_id_sha256="e" * 64,
                )
            ],
        )
        _reject(lambda: _observe(plan, wrong_current_node))

        wrong_success = _Transport(
            plan,
            states=[
                _state(
                    plan,
                    exact=True,
                    observed_success_status_description_sha256="f" * 64,
                )
            ],
        )
        _reject(lambda: _observe(plan, wrong_success))

        drift = _Transport(
            plan,
            states=[_state(plan), _state(plan, exact=True)],
        )
        _reject(lambda: _observe(plan, drift))
        assert drift.calls == 2

        _reject(
            lambda: _observe(
                plan,
                _Transport(plan),
                now="2026-09-15T09:50:59Z",
            )
        )

        for field in (
            "plan_authenticated",
            "parent_deployment_verified",
            "remote_repository_verified",
            "current_in_progress_status_verified",
            "status_inventory_bounded",
            "success_status_state_verified",
            "double_observation_matched",
            "success_status_state_acceptable",
            "success_deployment_status_ready",
        ):
            value = clear.to_dict()
            value[field] = False
            _reject(
                lambda value=value: (
                    observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(
                        value
                    )
                )
            )

        for field in (
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        ):
            value = clear.to_dict()
            value[field] = True
            _reject(
                lambda value=value: (
                    observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(
                        value
                    )
                )
            )
    finally:
        plan_contract._cleanup(bundle)

    recovered_bundle, recovered_plan = _live_plan(recovered=True)
    try:
        recovered = _observe(recovered_plan, _Transport(recovered_plan))
        assert recovered.observation_authenticated is True
        assert recovered.status_recovery_lock_sha256 is not None
        assert recovered.current_in_progress_status_verified is True
        assert recovered.success_status_lane_clear is True
        assert recovered.success_deployment_status_authorized is False
    finally:
        plan_contract._cleanup(recovered_bundle)

    schema = json.loads(code_of(SCHEMA))
    fields = set(
        observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 62

    signature = inspect.signature(
        observation.observe_pilot_exact_task_staging_success_status_state
    )
    assert list(signature.parameters) == ["staging_success_status_plan"]

    source_text = code_of(SOURCE)
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
        "create_once_file",
    ):
        assert forbidden not in source_text
    assert 'method="GET"' in source_text
    assert "if len(statuses) > 2:" in source_text
    assert "attested in_progress status disappeared" in source_text
    assert "success_deployment_status_authorized: bool = False" in source_text
    assert "deployment_status_mutation_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
