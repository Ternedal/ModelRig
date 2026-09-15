"""Adversarial contract for ADR-DC-072 reviewer requestability precondition."""
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
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_requestability_precondition as requestability  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_request_credential_capability_contract import (  # noqa: E402
    _descriptor,
    _live_identity,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-requestability-precondition-v1.schema.json"
)

_REVIEWER_NODE_ID = "MDQ6VXNlcjI0NjgxMzU3OQ=="


def _reject(fn) -> None:
    try:
        fn()
    except (
        requestability.PilotExactTaskPrReviewerRequestabilityPreconditionError,
        capability.PilotExactTaskPrReviewerRequestCredentialCapabilityError,
        ValueError,
        TypeError,
        OSError,
    ):
        return
    raise AssertionError("ADR-DC-072 unexpectedly accepted unsafe requestability evidence")


class _Capture:
    def __init__(self, payload: bytes) -> None:
        self.prefix = payload
        self.total_bytes = len(payload)
        self.truncated = False
        self.sha256 = hashlib.sha256(payload).hexdigest()


class _Result:
    def __init__(self, stdout: bytes, stderr: bytes = b"") -> None:
        self.returncode = 0
        self.output_limit_exceeded = False
        self.timed_out = False
        self.stdout = _Capture(stdout)
        self.stderr = _Capture(stderr)
        self.total_output_bytes = len(stdout) + len(stderr)


def _live_capability():
    identity_value, cleanup = _live_identity()
    broker_temp = TemporaryDirectory(prefix="rsi-reviewer-requestability-072-")
    broker_path = Path(broker_temp.name) / "broker"
    broker_bytes = b"reviewer-request-broker-072-fixture"
    broker_path.write_bytes(broker_bytes)
    descriptor = _descriptor(broker_path, broker_bytes=broker_bytes)
    cap = capability._materialize_verified_pilot_exact_task_pr_reviewer_request_credential_capability(
        reviewer_identity_observation=identity_value,
        broker_descriptor=descriptor,
        now_provider=lambda: "2026-09-15T06:25:34Z",
    )
    assert cap.capability_authenticated is True
    return cap, identity_value, broker_path, broker_bytes, broker_temp, cleanup


def _runner(
    *,
    cap,
    identity_value,
    permission="read",
    role_name="read",
    reviewer_login=None,
    reviewer_user_id=None,
    reviewer_node_id=_REVIEWER_NODE_ID,
    reviewer_api_url=None,
    reviewer_html_url=None,
    calls=None,
):
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
        request = json.loads(stdin_bytes.decode("utf-8"))
        if calls is not None:
            calls.append(
                {
                    "command": command,
                    "cwd": cwd,
                    "env": dict(env),
                    "request": request,
                    "timeout_seconds": timeout_seconds,
                    "max_output_bytes": max_output_bytes,
                    "stdout_prefix_bytes": stdout_prefix_bytes,
                    "stderr_prefix_bytes": stderr_prefix_bytes,
                }
            )
        assert command == (
            os.fspath(Path(cwd) / Path(command[0]).name),
            "--protocol",
            "github-rest-reviewer-request-broker-v1",
            "--request-stdin-json",
            "--response-stdout-json",
        )
        assert env == {"LANG": "C", "LC_ALL": "C"}
        assert request["operation"] == "get-collaborator-permission"
        assert request["api_origin"] == "https://api.github.com"
        assert request["api_path"] == (
            "/repos/Ternedal/ModelRig/collaborators/"
            f"{cap.reviewer_login}/permission"
        )
        assert request["repository"] == cap.repository
        assert request["pull_request_number"] == cap.pull_request_number
        assert request["reviewer_login"] == cap.reviewer_login
        assert request["reviewer_user_id"] == cap.reviewer_user_id
        assert request["reviewer_request_nonce_sha256"] == cap.reviewer_request_nonce_sha256
        response = {
            "schema": requestability.PILOT_EXACT_TASK_PR_REVIEWER_PERMISSION_BROKER_RESPONSE_SCHEMA,
            "status": "permission-observed",
            "operation": "get-collaborator-permission",
            "request_sha256": hashlib.sha256(stdin_bytes).hexdigest(),
            "repository": cap.repository,
            "pull_request_number": cap.pull_request_number,
            "reviewer_login": cap.reviewer_login if reviewer_login is None else reviewer_login,
            "reviewer_user_id": cap.reviewer_user_id if reviewer_user_id is None else reviewer_user_id,
            "reviewer_node_id": reviewer_node_id,
            "reviewer_api_url": (
                identity_value.reviewer_user_api_url
                if reviewer_api_url is None
                else reviewer_api_url
            ),
            "reviewer_html_url": (
                identity_value.reviewer_user_html_url
                if reviewer_html_url is None
                else reviewer_html_url
            ),
            "repository_permission": permission,
            "repository_role_name": role_name,
        }
        payload = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return _Result(payload)

    return run


def _observe(cap, identity_value, runner, *, times=None):
    values = iter(times or ("2026-09-15T06:25:35Z", "2026-09-15T06:25:36Z"))
    return requestability._observe_verified_pilot_exact_task_pr_reviewer_requestability_precondition(
        reviewer_request_credential_capability=cap,
        subprocess_runner=runner,
        now_provider=lambda: next(values),
        broker_host_control_required=False,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    cap, identity_value, broker_path, broker_bytes, broker_temp, cleanup = _live_capability()
    try:
        calls = []
        result = _observe(
            cap,
            identity_value,
            _runner(cap=cap, identity_value=identity_value, calls=calls),
        )
        assert result.observation_authenticated is True
        assert result.reviewer_request_credential_capability_sha256 == cap.sha256
        assert result.reviewer_identity_observation_sha256 == identity_value.sha256
        assert result.reviewer_request_reservation_sha256 == cap.reviewer_request_reservation_sha256
        assert result.reviewer_target_attestation_sha256 == cap.reviewer_target_attestation_sha256
        assert result.reviewer_request_nonce_sha256 == cap.reviewer_request_nonce_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == cap.pull_request_number
        assert result.predicted_commit_sha == cap.predicted_commit_sha
        assert result.reviewer_login == cap.reviewer_login
        assert result.reviewer_user_id == cap.reviewer_user_id
        assert result.reviewer_user_node_id_sha256 == identity_value.reviewer_user_node_id_sha256
        assert result.credential_protocol == "github-rest-reviewer-request-broker-v1"
        assert result.permission_read_operation == "get-collaborator-permission"
        assert result.capability_materialized_at_utc == "2026-09-15T06:25:34Z"
        assert result.broker_policy_sha256 == cap.broker_policy_sha256
        assert result.broker_executable_path_sha256 == cap.broker_executable_path_sha256
        assert result.broker_executable_sha256 == cap.broker_executable_sha256
        assert result.repository_permission == "read"
        assert result.repository_role_name_sha256 == hashlib.sha256(b"read").hexdigest()
        assert result.permission_read_started_at_utc == "2026-09-15T06:25:35Z"
        assert result.observed_at_utc == "2026-09-15T06:25:36Z"
        assert len(calls) == 1
        assert calls[0]["request"]["operation"] == "get-collaborator-permission"

        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "exact_pr_state_reverified",
            "credential_broker_freshly_verified",
            "credential_broker_invoked_without_secret_exposure",
            "permission_read_performed",
            "minimum_read_repository_permission_verified",
            "reviewer_requestability_precondition_verified",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "post_request_readback_verification_required",
            "one_shot_reviewer_request_transaction_required",
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

        reloaded = requestability.PilotExactTaskPrReviewerRequestabilityPrecondition.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        replayed_cap = capability.PilotExactTaskPrReviewerRequestCredentialCapability.from_mapping(
            cap.to_dict()
        )
        assert replayed_cap.capability_authenticated is False
        _reject(
            lambda: requestability._require_live_capability(replayed_cap)
        )

        for permission, role in (
            ("read", "triage"),
            ("write", "maintain"),
            ("admin", "admin"),
        ):
            accepted = _observe(
                cap,
                identity_value,
                _runner(
                    cap=cap,
                    identity_value=identity_value,
                    permission=permission,
                    role_name=role,
                ),
            )
            assert accepted.repository_permission == permission
            assert accepted.repository_role_name_sha256 == hashlib.sha256(
                role.encode("utf-8")
            ).hexdigest()

        for permission in ("none", "triage", "maintain", "pull", "push", ""):
            _reject(
                lambda permission=permission: _observe(
                    cap,
                    identity_value,
                    _runner(
                        cap=cap,
                        identity_value=identity_value,
                        permission=permission,
                    ),
                )
            )

        _reject(
            lambda: _observe(
                cap,
                identity_value,
                _runner(
                    cap=cap,
                    identity_value=identity_value,
                    reviewer_user_id=cap.reviewer_user_id + 1,
                ),
            )
        )
        _reject(
            lambda: _observe(
                cap,
                identity_value,
                _runner(
                    cap=cap,
                    identity_value=identity_value,
                    reviewer_login="different-reviewer",
                ),
            )
        )
        _reject(
            lambda: _observe(
                cap,
                identity_value,
                _runner(
                    cap=cap,
                    identity_value=identity_value,
                    reviewer_node_id="MDQ6VXNlcjEyMzQ1Njc4OQ==",
                ),
            )
        )
        _reject(
            lambda: _observe(
                cap,
                identity_value,
                _runner(
                    cap=cap,
                    identity_value=identity_value,
                    reviewer_api_url="https://api.github.com/users/different-reviewer",
                ),
            )
        )

        stale_calls = []
        _reject(
            lambda: _observe(
                cap,
                identity_value,
                _runner(
                    cap=cap,
                    identity_value=identity_value,
                    calls=stale_calls,
                ),
                times=("2026-09-15T06:26:35Z", "2026-09-15T06:26:36Z"),
            )
        )
        assert stale_calls == []

        _reject(
            lambda: _observe(
                cap,
                identity_value,
                _runner(cap=cap, identity_value=identity_value),
                times=("2026-09-15T06:25:35Z", "2026-09-15T06:25:34Z"),
            )
        )

        broker_path.write_bytes(broker_bytes + b"tampered")
        tamper_calls = []
        _reject(
            lambda: _observe(
                cap,
                identity_value,
                _runner(
                    cap=cap,
                    identity_value=identity_value,
                    calls=tamper_calls,
                ),
            )
        )
        assert tamper_calls == []
        broker_path.write_bytes(broker_bytes)

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            requestability.PilotExactTaskPrReviewerRequestabilityPrecondition.__dataclass_fields__
        )
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["repository_permission"]["enum"] == [
            "read",
            "write",
            "admin",
        ]
        assert schema["properties"]["reviewer_requestability_precondition_verified"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert list(
            inspect.signature(
                requestability.observe_pilot_exact_task_pr_reviewer_requestability_precondition
            ).parameters
        ) == ["reviewer_request_credential_capability"]

        source = inspect.getsource(requestability)
        assert "get-collaborator-permission" in source
        assert '"--request-stdin-json"' in source
        assert '"--response-stdout-json"' in source
        for forbidden in (
            "/requested_reviewers",
            "request_pull_request_reviewers(",
            "remove_pull_request_reviewers(",
            "method=\"POST\"",
            "urllib.request",
            "EnvironmentFileGitHubCredentialProvider",
            "KALIV_GITHUB_TOKEN_FILE",
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "merge_pull_request(",
            "mark_pull_request_ready_for_review(",
        ):
            assert forbidden not in source
    finally:
        broker_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
