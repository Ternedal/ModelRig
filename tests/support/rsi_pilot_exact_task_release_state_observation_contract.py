"""Adversarial contract for ADR-DC-065 exact remote release-state observation."""
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

from kaliv_dev_control import improvement_pilot_exact_task_release_plan as release_plan  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_release_state_observation as release_state  # noqa: E402
from rsi_pilot_exact_task_post_merge_attestation_contract import (  # noqa: E402
    _attest,
    _cleanup_case,
    _normal_completion,
)
from rsi_pilot_exact_task_release_plan_contract import _config, _plan  # noqa: E402
from rsi_pilot_exact_task_release_readiness_evaluation_contract import (  # noqa: E402
    _Transport as _ReadinessTransport,
    _evaluate,
    _policy,
)

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-release-state-observation-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_release_state_observation.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-065 unexpectedly accepted unsafe remote release state")


class _Transport:
    def __init__(self, plan, readiness, *, state_class="clear"):
        self.plan = plan
        self.credential_config_sha256 = readiness.publisher_credential_config_sha256
        self.credential_path_sha256 = readiness.publisher_credential_path_sha256
        self.state_class = state_class
        self.scripted = []
        self.calls = []

    def _state(self, state_class=None):
        state_class = state_class or self.state_class
        if state_class == "clear":
            return release_state._RemoteReleaseState(
                repository=self.plan.repository,
                repository_id=self.plan.repository_id,
                tag_state="absent",
                tag_target_sha=None,
                release_state="absent",
                release_id=None,
                release_node_id_sha256=None,
                release_tag_name=None,
                release_name=None,
                release_body_sha256=None,
                release_draft=None,
                release_prerelease=None,
                release_asset_count=None,
                remote_state_class="clear",
            )
        if state_class == "exact-existing":
            return release_state._RemoteReleaseState(
                repository=self.plan.repository,
                repository_id=self.plan.repository_id,
                tag_state="exact",
                tag_target_sha=self.plan.tag_target_sha,
                release_state="exact-draft",
                release_id=9001,
                release_node_id_sha256="a" * 64,
                release_tag_name=self.plan.tag_name,
                release_name=self.plan.release_name,
                release_body_sha256=self.plan.release_body_sha256,
                release_draft=True,
                release_prerelease=True,
                release_asset_count=0,
                remote_state_class="exact-existing",
            )
        raise AssertionError("unsupported test state")

    def observe(self, plan):
        self.calls.append("observe")
        assert plan.sha256 == self.plan.sha256
        return self.scripted.pop(0) if self.scripted else self._state()


def _fixture():
    case = _normal_completion()
    (
        _bundle,
        _up_tx,
        _up_recovery,
        auth_temp,
        tx_temp,
        recovery_temp,
        authorization,
        _merge_receipt,
        observer,
    ) = case
    post_merge = _attest(authorization, tx_temp, auth_temp, recovery_temp, observer)
    readiness = _evaluate(
        post_merge,
        _policy(post_merge),
        _ReadinessTransport(post_merge),
    )
    plan = _plan(readiness, _config(readiness))
    return case, readiness, plan


def _observe(plan, transport, *, now="2026-09-15T09:44:00Z"):
    return release_state._observe_verified_pilot_exact_task_release_state(
        release_plan=plan,
        transport=transport,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    case, readiness, plan = _fixture()
    try:
        clear_transport = _Transport(plan, readiness)
        clear = _observe(plan, clear_transport)
        assert clear_transport.calls == ["observe", "observe"]
        assert clear.observation_authenticated is True
        assert clear.release_plan_sha256 == plan.sha256
        assert clear.release_readiness_evaluation_sha256 == readiness.sha256
        assert clear.release_intent_sha256 == plan.release_intent_sha256
        assert clear.publisher_credential_config_sha256 == readiness.publisher_credential_config_sha256
        assert clear.publisher_credential_path_sha256 == readiness.publisher_credential_path_sha256
        assert clear.tag_state == "absent"
        assert clear.release_state == "absent"
        assert clear.remote_state_class == "clear"
        assert clear.release_lane_clear is True
        assert clear.exact_existing_release is False
        assert clear.release_state_acceptable is True
        assert clear.release_authorized is False
        assert clear.deploy_authorized is False
        assert clear.production_activation_authorized is False

        exact = _observe(plan, _Transport(plan, readiness, state_class="exact-existing"))
        assert exact.observation_authenticated is True
        assert exact.tag_state == "exact"
        assert exact.release_state == "exact-draft"
        assert exact.release_id == 9001
        assert exact.release_node_id_sha256 == "a" * 64
        assert exact.remote_state_class == "exact-existing"
        assert exact.release_lane_clear is False
        assert exact.exact_existing_release is True
        assert exact.remote_release_state_sha256 != clear.remote_release_state_sha256

        reloaded = release_state.PilotExactTaskReleaseStateObservationReceipt.from_mapping(
            clear.to_dict()
        )
        assert reloaded == clear
        assert reloaded.observation_authenticated is False

        reloaded_plan = release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
            plan.to_dict()
        )
        assert reloaded_plan.plan_authenticated is False
        _reject(lambda: _observe(reloaded_plan, clear_transport))

        drift = _Transport(plan, readiness)
        drift.scripted = [drift._state("clear"), drift._state("exact-existing")]
        _reject(lambda: _observe(plan, drift))

        credential_drift = _Transport(plan, readiness)
        credential_drift.credential_config_sha256 = "9" * 64
        _reject(lambda: _observe(plan, credential_drift))

        _reject(
            lambda: _observe(
                plan,
                _Transport(plan, readiness),
                now="2026-09-15T09:42:59Z",
            )
        )

        _reject(
            lambda: release_state._RemoteReleaseState(
                repository=plan.repository,
                repository_id=plan.repository_id,
                tag_state="exact",
                tag_target_sha=plan.tag_target_sha,
                release_state="absent",
                release_id=None,
                release_node_id_sha256=None,
                release_tag_name=None,
                release_name=None,
                release_body_sha256=None,
                release_draft=None,
                release_prerelease=None,
                release_asset_count=None,
                remote_state_class="clear",
            )
        )

        for field, value in (
            ("release_plan_authenticated", False),
            ("remote_state_observed", False),
            ("double_observation_matched", False),
            ("release_state_acceptable", False),
            ("tag_write_authorized", True),
            ("release_mutation_authorized", True),
            ("release_authorized", True),
            ("remote_write_authorized", True),
            ("merge_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    release_state.PilotExactTaskReleaseStateObservationReceipt.from_mapping(
                        {**clear.to_dict(), field: value}
                    )
                )
            )

        _reject(
            lambda: release_state.PilotExactTaskReleaseStateObservationReceipt.from_mapping(
                {**clear.to_dict(), "tag_state": "exact"}
            )
        )

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(
            release_state.PilotExactTaskReleaseStateObservationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 51
        assert schema["properties"]["release_authorized"]["const"] is False
        assert schema["properties"]["deploy_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        signature = inspect.signature(release_state.observe_pilot_exact_task_release_state)
        assert list(signature.parameters) == ["release_plan"]

        source_text = code_of(SOURCE)
        assert 'method="POST"' not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert "create_release" not in source_text
        assert "create_ref" not in source_text
        assert "update_ref" not in source_text
        assert "git push" not in source_text
        assert "subprocess" not in source_text
        assert "Ed25519PrivateKey" not in source_text
    finally:
        _cleanup_case(case)


if __name__ == "__main__":
    run_contract()
