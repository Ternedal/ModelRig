"""Adversarial contract for ADR-DC-074 reviewer-write credential capability."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_pr_reviewer_write_credential_capability_impl as implementation,
)
from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_pr_reviewer_write_credential_capability_production_boundary as production,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pr_reviewer_request_preflight as preflight,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pr_reviewer_write_credential_capability as capability,
)
import rsi_pilot_exact_task_pr_reviewer_request_preflight_contract as parent_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-write-credential-capability-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        capability.PilotExactTaskPrReviewerWriteCredentialCapabilityError,
        preflight.PilotExactTaskPrReviewerRequestPreflightError,
        production.PilotExactTaskPrReviewerWriteCredentialCapabilityProductionBoundaryError,
        ValueError,
        TypeError,
        OSError,
    ):
        return
    raise AssertionError("ADR-DC-074 unexpectedly accepted unsafe reviewer-write capability")


def _live_preflight():
    precondition_value, identity_value, broker_temp, cleanup = (
        parent_contract._live_precondition()
    )
    value = parent_contract._run(
        precondition_value,
        parent_contract._reader(identity_value, precondition_value),
        times=("2026-09-15T06:25:37Z", "2026-09-15T06:25:38Z"),
    )
    assert value.observation_authenticated is True
    return value, broker_temp, cleanup


def _descriptor(path: Path, broker_bytes: bytes) -> dict[str, str]:
    return {
        "broker_policy_sha256": hashlib.sha256(b"write-policy-074").hexdigest(),
        "broker_executable_path": os.fspath(path),
        "broker_executable_path_sha256": hashlib.sha256(
            os.fsencode(os.path.abspath(os.fspath(path)))
        ).hexdigest(),
        "broker_executable_sha256": hashlib.sha256(broker_bytes).hexdigest(),
        "broker_version": "1",
        "credential_protocol": "github-rest-reviewer-write-broker-v1",
        "operation": "request-pull-request-reviewer",
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "api_origin": "https://api.github.com",
        "credential_account": "Ternedal",
        "request_path_template": (
            "/repos/Ternedal/ModelRig/pulls/{pull_request_number}/requested_reviewers"
        ),
    }


def _policy(path: Path, broker_bytes: bytes) -> dict[str, object]:
    return {
        "schema": production.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": "https://api.github.com",
        "repository": "Ternedal/ModelRig",
        "credential_account": "Ternedal",
        "operation": "request-pull-request-reviewer",
        "credential_protocol": "github-rest-reviewer-write-broker-v1",
        "broker_version": "1",
        "broker_executable_path": os.fspath(path),
        "broker_executable_sha256": hashlib.sha256(broker_bytes).hexdigest(),
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "request_path_template": (
            "/repos/Ternedal/ModelRig/pulls/{pull_request_number}/requested_reviewers"
        ),
        "individual_reviewer_write_only": True,
        "team_reviewer_write_forbidden": True,
        "collaborator_permission_read_forbidden": True,
        "other_repository_reads_forbidden": True,
        "pull_request_create_forbidden": True,
        "pull_request_metadata_write_forbidden": True,
        "ready_for_review_write_forbidden": True,
        "label_write_forbidden": True,
        "merge_write_forbidden": True,
        "repository_contents_write_forbidden": True,
        "administration_write_forbidden": True,
        "release_write_forbidden": True,
        "deployment_write_forbidden": True,
        "redirect_following_forbidden": True,
    }


def _materialize(preflight_value, descriptor, *, at="2026-09-15T06:25:39Z"):
    return capability._materialize_verified_pilot_exact_task_pr_reviewer_write_credential_capability(
        reviewer_request_preflight=preflight_value,
        broker_descriptor=descriptor,
        now_provider=lambda: at,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent_contract.run_contract()

    preflight_value, parent_broker_temp, cleanup = _live_preflight()
    write_temp = TemporaryDirectory(prefix="rsi-reviewer-write-074-")
    try:
        broker_path = Path(write_temp.name) / "reviewer-write-broker"
        broker_bytes = b"reviewer-write-broker-074-fixture"
        broker_path.write_bytes(broker_bytes)
        broker_path.chmod(0o755)
        descriptor = _descriptor(broker_path, broker_bytes)

        result = _materialize(preflight_value, descriptor)
        assert result.capability_authenticated is True
        assert result.reviewer_request_preflight_sha256 == preflight_value.sha256
        assert (
            result.reviewer_requestability_precondition_sha256
            == preflight_value.reviewer_requestability_precondition_sha256
        )
        assert result.reviewer_request_nonce_sha256 == preflight_value.reviewer_request_nonce_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == preflight_value.pull_request_number
        assert result.predicted_commit_sha == preflight_value.predicted_commit_sha
        assert result.reviewer_login == preflight_value.reviewer_login
        assert result.reviewer_user_id == preflight_value.reviewer_user_id
        assert result.pull_request_author_user_id == preflight_value.pull_request_author_user_id
        assert result.credential_protocol == "github-rest-reviewer-write-broker-v1"
        assert result.credential_operation == "request-pull-request-reviewer"
        assert result.materialized_at_utc == "2026-09-15T06:25:39Z"
        assert result.fresh_pr_state_observed_at_utc == "2026-09-15T06:25:38Z"
        assert result.broker_policy_sha256 == descriptor["broker_policy_sha256"]
        assert result.broker_executable_sha256 == descriptor["broker_executable_sha256"]
        assert os.fspath(broker_path) not in result.canonical_json()

        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "reviewer_requestability_precondition_verified",
            "fresh_exact_pr_state_revalidated",
            "no_requested_reviewers_verified",
            "reviewer_not_pr_author_verified",
            "reviewer_write_credential_capability_materialized",
            "write_broker_host_pinned",
            "write_broker_binary_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "individual_reviewer_write_only",
            "team_reviewers_forbidden",
            "collaborator_permission_read_forbidden",
            "other_repository_reads_forbidden",
            "pull_request_create_forbidden",
            "pull_request_metadata_write_forbidden",
            "ready_for_review_write_forbidden",
            "label_write_forbidden",
            "merge_write_forbidden",
            "repository_contents_write_forbidden",
            "administration_write_forbidden",
            "release_write_forbidden",
            "deployment_write_forbidden",
            "redirect_following_forbidden",
            "one_shot_reviewer_request_transaction_required",
            "post_request_readback_verification_required",
        ):
            assert getattr(result, field) is True

        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = capability.PilotExactTaskPrReviewerWriteCredentialCapability.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.capability_authenticated is False

        replayed_preflight = preflight.PilotExactTaskPrReviewerRequestPreflight.from_mapping(
            preflight_value.to_dict()
        )
        assert replayed_preflight.observation_authenticated is False
        _reject(lambda: capability._require_live_preflight(replayed_preflight))

        _reject(
            lambda: _materialize(
                preflight_value,
                descriptor,
                at="2026-09-15T06:25:54Z",
            )
        )

        for name, wrong in (
            ("credential_protocol", "github-rest-reviewer-requestability-broker-v1"),
            ("operation", "get-collaborator-permission"),
            ("credential_account", "someone-else"),
            ("api_origin", "https://example.invalid"),
            ("request_path_template", "/repos/Ternedal/ModelRig/pulls/{pull_request_number}"),
        ):
            changed = dict(descriptor)
            changed[name] = wrong
            _reject(lambda changed=changed: _materialize(preflight_value, changed))

        relative = dict(descriptor)
        relative["broker_executable_path"] = "reviewer-write-broker"
        relative["broker_executable_path_sha256"] = hashlib.sha256(
            b"reviewer-write-broker"
        ).hexdigest()
        _reject(lambda: _materialize(preflight_value, relative))

        wrong_path_hash = dict(descriptor)
        wrong_path_hash["broker_executable_path_sha256"] = "1" * 64
        _reject(lambda: _materialize(preflight_value, wrong_path_hash))

        policy_path = Path(write_temp.name) / "policy.json"
        policy_value = _policy(broker_path, broker_bytes)
        policy_payload = json.dumps(
            policy_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        policy_path.write_bytes(policy_payload)
        loaded = production._load_broker_descriptor_at(
            policy_path,
            broker_path,
            require_host_control=False,
        )
        assert loaded["operation"] == "request-pull-request-reviewer"
        assert loaded["credential_protocol"] == "github-rest-reviewer-write-broker-v1"
        assert loaded["request_path_template"] == (
            "/repos/Ternedal/ModelRig/pulls/{pull_request_number}/requested_reviewers"
        )

        changed_policy = dict(policy_value)
        changed_policy["collaborator_permission_read_forbidden"] = False
        changed_payload = json.dumps(
            changed_policy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _reject(
            lambda: production._parse_policy(
                changed_payload,
                broker_path=broker_path,
            )
        )

        pretty_payload = json.dumps(
            policy_value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        _reject(
            lambda: production._parse_policy(
                pretty_payload,
                broker_path=broker_path,
            )
        )

        original_bytes = broker_path.read_bytes()
        broker_path.write_bytes(b"tampered-reviewer-write-broker")
        broker_path.chmod(0o755)
        _reject(
            lambda: production._load_broker_descriptor_at(
                policy_path,
                broker_path,
                require_host_control=False,
            )
        )
        broker_path.write_bytes(original_bytes)
        broker_path.chmod(0o755)

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            capability.PilotExactTaskPrReviewerWriteCredentialCapability.__dataclass_fields__
        )
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["individual_reviewer_write_only"]["const"] is True
        assert schema["properties"]["collaborator_permission_read_forbidden"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                capability.materialize_pilot_exact_task_pr_reviewer_write_credential_capability
            ).parameters
        ) == ("reviewer_request_preflight",)

        implementation_source = inspect.getsource(implementation)
        for forbidden in (
            "import subprocess",
            "subprocess.",
            "run_bounded_subprocess",
            "urllib",
            "requests.",
            "http.client",
            "Authorization",
            "GITHUB_TOKEN",
            "GH_TOKEN",
        ):
            assert forbidden not in implementation_source

        production_source = inspect.getsource(production)
        for forbidden in (
            "run_bounded_subprocess",
            "request_pull_request_reviewers(",
            "merge_pull_request(",
            'method="POST"',
            "urllib",
            "requests.",
        ):
            assert forbidden not in production_source
        assert "request-pull-request-reviewer" in production_source
        assert "team_reviewer_write_forbidden" in production_source
        assert "collaborator_permission_read_forbidden" in production_source
    finally:
        write_temp.cleanup()
        parent_broker_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
