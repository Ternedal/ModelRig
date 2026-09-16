"""Adversarial contract for ADR-DC-086 staging success-status lane observation."""
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
    improvement_pilot_exact_task_staging_success_status_state_observation as observation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_success_status_plan as success_plan,
)
import rsi_pilot_exact_task_staging_success_status_plan_contract as success_plan_contract  # noqa: E402

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
    raise AssertionError("ADR-DC-086 unexpectedly accepted unsafe status-lane evidence")


def _live_plan(*, recovered=False):
    bundle, build = success_plan_contract._live_build_identity(recovered=recovered)
    plan = success_plan_contract._plan(build)
    assert plan.plan_authenticated is True
    return bundle, plan


def _cleanup(bundle) -> None:
    success_plan_contract._cleanup(bundle)


class _Transport:
    def __init__(self, plan, *, scripted=None):
        self.plan = plan
        _plan, self.post = observation._require_live_plan(plan)
        self.credential_config_sha256 = plan.publisher_credential_config_sha256
        self.credential_path_sha256 = plan.publisher_credential_path_sha256
        self.scripted = list(scripted or ())
        self.calls = 0

    def _state(self, overrides=None):
        values = {
            "repository": self.plan.repository,
            "repository_id": self.plan.repository_id,
            "deployment_id": self.plan.deployment_id,
            "deployment_node_id_sha256": self.plan.deployment_node_id_sha256,
            "status_inventory_count": 1,
            "deployment_status_id": self.plan.current_deployment_status_id,
            "deployment_status_node_id_sha256": self.plan.current_deployment_status_node_id_sha256,
            "observed_status_state": "in_progress",
            "observed_status_environment": "staging",
            "observed_status_description_sha256": self.post.deployment_status_description_sha256,
            "observed_status_log_url": None,
            "observed_status_environment_url": None,
            "status_created_at_utc": self.post.status_created_at_utc,
            "status_updated_at_utc": self.post.status_updated_at_utc,
            "remote_state_class": "ready",
        }
        if overrides:
            values.update(overrides)
        return observation._RemoteStagingSuccessStatusLaneState(**values)

    def observe(self, plan):
        self.calls += 1
        assert plan.sha256 == self.plan.sha256
        overrides = self.scripted.pop(0) if self.scripted else None
        return self._state(overrides)


def _observe(plan, transport=None, *, now="2026-09-15T09:51:10Z"):
    transport = transport or _Transport(plan)
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
        transport = _Transport(plan)
        receipt = _observe(plan, transport)
        assert transport.calls == 2
        assert receipt.observation_authenticated is True
        assert receipt.staging_success_status_plan_sha256 == plan.sha256
        assert receipt.repository == plan.repository
        assert receipt.repository_id == plan.repository_id
        assert receipt.merge_commit_sha == plan.merge_commit_sha
        assert receipt.deployment_id == plan.deployment_id
        assert receipt.current_deployment_status_id == plan.current_deployment_status_id
        assert receipt.current_deployment_status_node_id_sha256 == plan.current_deployment_status_node_id_sha256
        assert receipt.current_deployment_status_state == "in_progress"
        assert receipt.current_deployment_status_environment == "staging"
        assert receipt.status_inventory_count == 1
        assert receipt.remote_state_class == "ready"
        assert receipt.success_deployment_status_state_planned == "success"
        assert receipt.success_deployment_status_environment_planned == "staging"
        assert receipt.success_transition_ready is True
        assert receipt.success_deployment_status_authorized is False
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.observation_authenticated is False

        serialized_plan = success_plan.PilotExactTaskStagingSuccessStatusPlanReceipt.from_mapping(
            plan.to_dict()
        )
        assert serialized_plan.plan_authenticated is False
        stale_transport = _Transport(plan)
        _reject(lambda: _observe(serialized_plan, stale_transport))
        assert stale_transport.calls == 0

        wrong_id = _Transport(plan, scripted=[
            {"deployment_status_id": plan.current_deployment_status_id + 1},
            {"deployment_status_id": plan.current_deployment_status_id + 1},
        ])
        _reject(lambda: _observe(plan, wrong_id))
        assert wrong_id.calls == 1

        wrong_node = _Transport(plan, scripted=[
            {"deployment_status_node_id_sha256": "a" * 64},
            {"deployment_status_node_id_sha256": "a" * 64},
        ])
        _reject(lambda: _observe(plan, wrong_node))

        wrong_description = _Transport(plan, scripted=[
            {"observed_status_description_sha256": "b" * 64},
            {"observed_status_description_sha256": "b" * 64},
        ])
        _reject(lambda: _observe(plan, wrong_description))

        success_already_exists = _Transport(plan, scripted=[
            {"observed_status_state": "success"},
        ])
        _reject(lambda: _observe(plan, success_already_exists))

        duplicate_lane = _Transport(plan, scripted=[
            {"status_inventory_count": 2},
        ])
        _reject(lambda: _observe(plan, duplicate_lane))

        drift = _Transport(plan, scripted=[
            {},
            {"status_updated_at_utc": "2026-09-15T09:50:41Z"},
        ])
        _reject(lambda: _observe(plan, drift))
        assert drift.calls == 2

        bad_credential = _Transport(plan)
        bad_credential.credential_config_sha256 = "c" * 64
        _reject(lambda: _observe(plan, bad_credential))
        assert bad_credential.calls == 0

        bad_path = _Transport(plan)
        bad_path.credential_path_sha256 = "d" * 64
        _reject(lambda: _observe(plan, bad_path))
        assert bad_path.calls == 0

        _reject(lambda: _observe(
            plan,
            _Transport(plan),
            now="2026-09-15T09:50:59Z",
        ))

        for field in (
            "staging_success_status_plan_authenticated",
            "current_status_attestation_authenticated",
            "parent_deployment_verified",
            "remote_repository_verified",
            "status_inventory_bounded",
            "exact_current_in_progress_status_verified",
            "current_status_identity_verified",
            "current_status_description_verified",
            "current_status_urls_absent_verified",
            "no_additional_statuses_verified",
            "double_observation_matched",
            "success_transition_ready",
        ):
            data = receipt.to_dict()
            data[field] = False
            _reject(
                lambda data=data: observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(data)
            )

        for field in (
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        ):
            data = receipt.to_dict()
            data[field] = True
            _reject(
                lambda data=data: observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.from_mapping(data)
            )
    finally:
        _cleanup(bundle)

    recovered_bundle, recovered_plan = _live_plan(recovered=True)
    try:
        recovered = _observe(recovered_plan)
        assert recovered.observation_authenticated is True
        assert recovered_plan.status_recovery_lock_sha256 is not None
        assert recovered.status_inventory_count == 1
        assert recovered.remote_state_class == "ready"
        assert recovered.success_transition_ready is True
        assert recovered.success_deployment_status_authorized is False
    finally:
        _cleanup(recovered_bundle)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        observation.PilotExactTaskStagingSuccessStatusStateObservationReceipt.__dataclass_fields__
    )
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 84

    signature = inspect.signature(
        observation.observe_pilot_exact_task_staging_success_status_state
    )
    assert list(signature.parameters) == ["staging_success_status_plan"]

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
        "create_once_file",
    ):
        assert forbidden not in source_text
    assert 'method="GET"' in source_text
    assert "ProxyHandler({})" in source_text
    assert "/statuses?" in source_text
    assert "len(matches) > 1" in source_text
    assert "len(matches) != 1" in source_text
    assert 'item.get("state") != "in_progress"' in source_text
    assert "success_deployment_status_authorized: bool = False" in source_text
    assert "production_activation_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()
