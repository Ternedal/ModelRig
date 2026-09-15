"""Adversarial contract for ADR-DC-072 reviewer requestability preflight."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_requestability_preflight as preflight  # noqa: E402
from kaliv_dev_control.bounded_subprocess import BoundedStreamEvidence, BoundedSubprocessResult  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_request_credential_capability_contract import (  # noqa: E402
    _descriptor,
    _live_observation,
)

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-requestability-preflight-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        preflight.PilotExactTaskPrReviewerRequestabilityPreflightError,
        capability.PilotExactTaskPrReviewerRequestCredentialCapabilityError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-072 unexpectedly accepted unsafe requestability evidence")


def _stream(payload: bytes) -> BoundedStreamEvidence:
    return BoundedStreamEvidence(
        prefix=payload,
        total_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        truncated=False,
    )


def _live_capability():
    state, cleanup = _live_observation()
    broker_temp = TemporaryDirectory(prefix="rsi-reviewer-requestability-072-")
    broker_path = Path(broker_temp.name) / "rsi-github-pr-reviewer-request-broker-v1"
    broker_path.write_bytes(b"#!/bin/sh\nexit 0\n")
    broker_path.chmod(0o700)
    cap = capability._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
        reviewer_identity_state_observation=state,
        broker_descriptor=_descriptor(broker_path),
        now_provider=lambda: "2026-09-15T06:25:41Z",
    )
    assert cap.capability_authenticated is True
    return cap, broker_path, (broker_temp, *cleanup)


def _broker_runner(*, cap, calls, permission="read", role_name="read"):
    def run(
        command,
        *,
        cwd,
        env,
        stdin_bytes,
        timeout_seconds,
        max_output_bytes,
        stdout_prefix_bytes,
        stderr_prefix_bytes,
    ):
        args = tuple(command)
        environment = dict(env)
        request = json.loads(stdin_bytes.decode("utf-8"))
        request_sha256 = hashlib.sha256(stdin_bytes).hexdigest()
        calls.append((args, Path(cwd), environment, request))
        assert args[0].endswith("rsi-github-pr-reviewer-request-broker-v1")
        assert args[1:] == (
            "--protocol",
            "github-rest-reviewer-request-broker-v1",
            "--request-stdin-json",
            "--response-stdout-json",
        )
        assert timeout_seconds == 30
        assert max_output_bytes == 64 * 1024
        assert stdout_prefix_bytes == 64 * 1024
        assert stderr_prefix_bytes == 64 * 1024
        assert not any(
            marker in key.upper()
            for key in environment
            for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")
        )
        permission_url = (
            "https://api.github.com/repos/Ternedal/ModelRig/collaborators/"
            f"{cap.reviewer_login}/permission"
        )
        assert request == {
            "schema": preflight.PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_REQUEST_SCHEMA,
            "operation": "check-reviewer-requestability",
            "api_origin": "https://api.github.com",
            "permission_api_url": permission_url,
            "repository": "Ternedal/ModelRig",
            "pull_request_number": cap.pull_request_number,
            "reviewer_login": cap.reviewer_login,
            "reviewer_user_id": cap.reviewer_user_id,
            "reviewer_node_id_sha256": cap.reviewer_node_id_sha256,
            "reviewer_request_nonce_sha256": cap.reviewer_request_nonce_sha256,
        }
        response = {
            "schema": preflight.PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_BROKER_RESPONSE_SCHEMA,
            "status": "requestable" if permission in {"read", "write", "admin"} else "not-requestable",
            "operation": "check-reviewer-requestability",
            "request_sha256": request_sha256,
            "permission_api_url_sha256": hashlib.sha256(
                permission_url.encode("utf-8")
            ).hexdigest(),
            "repository": "Ternedal/ModelRig",
            "reviewer_login": cap.reviewer_login,
            "reviewer_user_id": cap.reviewer_user_id,
            "permission": permission,
            "role_name": role_name,
        }
        stdout = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return BoundedSubprocessResult(
            args=args,
            returncode=0,
            stdout=_stream(stdout),
            stderr=_stream(b""),
            total_output_bytes=len(stdout),
            output_limit_exceeded=False,
            timed_out=False,
            process_tree_terminated=False,
        )
    return run


def run_contract() -> None:
    if os.name == "nt":
        return

    cap, broker_path, cleanup = _live_capability()
    try:
        calls = []
        result = preflight._observe_verified_pilot_exact_task_pr_reviewer_requestability(
            reviewer_request_credential_capability=cap,
            subprocess_runner=_broker_runner(cap=cap, calls=calls),
            now_provider=lambda: "2026-09-15T06:25:42Z",
            broker_host_control_required=False,
        )
        assert result.preflight_authenticated is True
        assert result.reviewer_request_credential_capability_sha256 == cap.sha256
        assert result.reviewer_identity_state_observation_sha256 == cap.reviewer_identity_state_observation_sha256
        assert result.reviewer_request_reservation_sha256 == cap.reviewer_request_reservation_sha256
        assert result.reviewer_target_attestation_sha256 == cap.reviewer_target_attestation_sha256
        assert result.ready_transaction_sha256 == cap.ready_transaction_sha256
        assert result.predicted_commit_sha == cap.predicted_commit_sha
        assert result.reviewer_target_policy_sha256 == cap.reviewer_target_policy_sha256
        assert result.reviewer_request_nonce_sha256 == cap.reviewer_request_nonce_sha256
        assert result.reviewer_login == cap.reviewer_login
        assert result.reviewer_user_id == cap.reviewer_user_id
        assert result.reviewer_node_id_sha256 == cap.reviewer_node_id_sha256
        assert result.broker_policy_sha256 == cap.broker_policy_sha256
        assert result.broker_executable_path_sha256 == cap.broker_executable_path_sha256
        assert result.broker_executable_sha256 == cap.broker_executable_sha256
        assert result.repository_permission == "read"
        assert result.repository_role_name == "read"
        assert result.capability_materialized_at_utc == "2026-09-15T06:25:41Z"
        assert result.checked_at_utc == "2026-09-15T06:25:42Z"
        assert len(calls) == 1

        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_public_identity_verified",
            "reviewer_not_pr_author_verified",
            "fresh_exact_pr_state_observed",
            "no_requested_reviewers_verified",
            "credential_broker_freshly_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "credentialed_requestability_check_performed",
            "reviewer_repository_read_access_verified",
            "reviewer_requestability_verified",
            "one_shot_reviewer_request_transaction_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "post_reviewer_request_readback_required",
            "team_reviewers_forbidden",
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

        reloaded = preflight.PilotExactTaskPrReviewerRequestabilityPreflight.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.preflight_authenticated is False

        reloaded_capability = capability.PilotExactTaskPrReviewerRequestCredentialCapability.from_mapping(
            cap.to_dict()
        )
        assert reloaded_capability.capability_authenticated is False
        _reject(lambda: preflight._require_live_capability(reloaded_capability))

        _reject(lambda: preflight._observe_verified_pilot_exact_task_pr_reviewer_requestability(
            reviewer_request_credential_capability=cap,
            subprocess_runner=_broker_runner(cap=cap, calls=[]),
            now_provider=lambda: "2026-09-15T06:26:42Z",
            broker_host_control_required=False,
        ))

        _reject(lambda: preflight._observe_verified_pilot_exact_task_pr_reviewer_requestability(
            reviewer_request_credential_capability=cap,
            subprocess_runner=_broker_runner(
                cap=cap,
                calls=[],
                permission="none",
                role_name="none",
            ),
            now_provider=lambda: "2026-09-15T06:25:42Z",
            broker_host_control_required=False,
        ))

        original = broker_path.read_bytes()
        broker_path.write_bytes(original + b"tampered")
        _reject(lambda: preflight._observe_verified_pilot_exact_task_pr_reviewer_requestability(
            reviewer_request_credential_capability=cap,
            subprocess_runner=_broker_runner(cap=cap, calls=[]),
            now_provider=lambda: "2026-09-15T06:25:42Z",
            broker_host_control_required=False,
        ))
        broker_path.write_bytes(original)
        broker_path.chmod(0o700)

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(
            preflight.PilotExactTaskPrReviewerRequestabilityPreflight.__dataclass_fields__
        )
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["reviewer_requestability_verified"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(
            preflight.observe_pilot_exact_task_pr_reviewer_requestability
        ).parameters) == ("reviewer_request_credential_capability",)
        source = inspect.getsource(preflight)
        for forbidden in (
            "urllib.request",
            "request_pull_request_reviewers(",
            "add_review_to_pr(",
            "merge_pull_request(",
        ):
            assert forbidden not in source
    finally:
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
