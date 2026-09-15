"""Adversarial contract for ADR-DC-057 host-pinned PR credential capability."""
from __future__ import annotations

import hashlib
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_state_observation as observation  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_credential_capability_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_pr_state_observation_contract import _reservation_material  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-credential-capability-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrCredentialCapabilityError,
        production.PilotExactTaskPrCredentialCapabilityProductionBoundaryError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-057 unexpectedly accepted unsafe PR credential state")


def _descriptor(path: Path) -> dict[str, str]:
    absolute = Path(path).absolute()
    return {
        "broker_policy_sha256": hashlib.sha256(b"policy-057").hexdigest(),
        "broker_executable_path": os.fspath(absolute),
        "broker_executable_path_sha256": hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(absolute)))).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(b"broker-057").hexdigest(),
        "broker_version": "1.0.0",
        "credential_protocol": "github-rest-broker-v1",
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "api_origin": "https://api.github.com",
    }


def _live_observation(receipt):
    def reader(*, head_branch):
        url = observation._query_url(head_branch=head_branch)
        payload = b"[]"
        etag = 'W/"fixture-057"'
        return {
            "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "open_pr_match_count": 0,
        }

    return observation._observe_verified_pilot_exact_task_pr_state(
        pr_mutation_reservation=receipt,
        reader=reader,
        now_provider=lambda: "2026-09-15T06:23:30Z",
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    material = _reservation_material()
    (
        receipt,
        identity,
        requirements,
        ledger_temp,
        broker_temp,
        remote_reservation_temp,
        transaction_temp,
        source_reservation_temp,
        execution_temp,
        local_reservation_temp,
        executor_capability_temp,
        admission_ledger_temp,
        source_temp,
    ) = material
    try:
        state = _live_observation(receipt)
        assert state.observation_authenticated is True
        descriptor = _descriptor(Path(broker_temp.name) / "rsi-github-pr-broker-v1")
        result = capability._materialize_verified_pilot_exact_task_pr_credential_capability(
            pr_state_observation=state,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:23:40Z",
        )

        assert result.capability_authenticated is True
        assert result.pr_state_observation_sha256 == state.sha256
        assert result.pr_mutation_reservation_sha256 == receipt.sha256
        assert result.pr_mutation_requirements_sha256 == requirements.sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.repository == "Ternedal/ModelRig"
        assert result.base_branch == "main"
        assert result.head_branch == requirements.head_branch
        assert result.pr_mutation_nonce_sha256 == receipt.pr_mutation_nonce_sha256
        assert result.credential_protocol == "github-rest-broker-v1"
        assert result.secret_source == "host-secret-store-only"
        assert result.secret_transport == "broker-owned-https-only"
        assert result.api_origin == "https://api.github.com"
        assert result.materialized_at_utc == "2026-09-15T06:23:40Z"

        for field in (
            "pr_mutation_slot_reserved",
            "no_existing_open_pr_verified",
            "credential_broker_host_pinned",
            "credential_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "one_shot_draft_pr_create_required",
            "fresh_pr_state_revalidation_before_create_required",
            "post_create_readback_verification_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_created",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = capability.PilotExactTaskPrCredentialCapability.from_mapping(result.to_dict())
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        reloaded_observation = observation.PilotExactTaskPrStateObservation.from_mapping(state.to_dict())
        assert reloaded_observation.observation_authenticated is False
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_credential_capability(
            pr_state_observation=reloaded_observation,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:23:41Z",
        ))

        bad_protocol = dict(descriptor)
        bad_protocol["credential_protocol"] = "git-askpass-v1"
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_credential_capability(
            pr_state_observation=state,
            broker_descriptor=bad_protocol,
            now_provider=lambda: "2026-09-15T06:23:42Z",
        ))

        bad_path_hash = dict(descriptor)
        bad_path_hash["broker_executable_path_sha256"] = "1" * 64
        _reject(lambda: capability._materialize_verified_pilot_exact_task_pr_credential_capability(
            pr_state_observation=state,
            broker_descriptor=bad_path_hash,
            now_provider=lambda: "2026-09-15T06:23:43Z",
        ))

        policy_path = Path(descriptor["broker_executable_path"])
        policy = {
            "schema": production.PILOT_EXACT_TASK_PR_CREDENTIAL_BROKER_POLICY_SCHEMA,
            "provider": "github",
            "api_origin": "https://api.github.com",
            "repository": "Ternedal/ModelRig",
            "credential_protocol": "github-rest-broker-v1",
            "broker_version": "1.0.0",
            "broker_executable_path": os.fspath(policy_path),
            "broker_executable_sha256": hashlib.sha256(b"broker-057").hexdigest(),
            "secret_source": "host-secret-store-only",
            "secret_transport": "broker-owned-https-only",
            "pull_request_write_required": True,
            "repository_contents_write_forbidden": True,
            "administration_write_forbidden": True,
            "merge_write_forbidden": True,
            "release_write_forbidden": True,
        }
        payload = production._canonical_bytes(policy)
        parsed = production._parse_policy(payload, broker_path=policy_path)
        assert parsed == policy

        unsafe_policy = dict(policy)
        unsafe_policy["merge_write_forbidden"] = False
        _reject(lambda: production._parse_policy(
            production._canonical_bytes(unsafe_policy),
            broker_path=policy_path,
        ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(result.to_dict())
        assert set(schema["required"]) == set(result.to_dict())
        assert schema["properties"]["credential_secret_not_loaded"]["const"] is True
        assert schema["properties"]["pull_request_create_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(capability.materialize_pilot_exact_task_pr_credential_capability).parameters
        assert tuple(public_parameters) == ("pr_state_observation",)

        impl_source = inspect.getsource(sys.modules["kaliv_dev_control._improvement_pilot_exact_task_pr_credential_capability_impl"])
        prod_source = inspect.getsource(production)
        assert "urllib.request" not in impl_source
        assert "requests." not in impl_source
        assert "create_pull_request(" not in impl_source
        assert "update_pull_request(" not in impl_source
        assert "Authorization" not in impl_source
        assert "Bearer " not in impl_source
        assert "token=" not in impl_source.lower()
        assert "repository_contents_write_forbidden" in prod_source
        assert "administration_write_forbidden" in prod_source
        assert "merge_write_forbidden" in prod_source
        assert "release_write_forbidden" in prod_source
    finally:
        ledger_temp.cleanup()
        broker_temp.cleanup()
        remote_reservation_temp.cleanup()
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        local_reservation_temp.cleanup()
        executor_capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
