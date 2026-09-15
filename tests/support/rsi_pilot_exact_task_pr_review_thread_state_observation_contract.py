"""Adversarial contract for ADR-DC-083 exact review-thread state observation."""
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
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_review_thread_state_observation as observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_status_review_thread_credential_capability as capability  # noqa: E402
from kaliv_dev_control.bounded_subprocess import BoundedStreamEvidence, BoundedSubprocessResult  # noqa: E402
import rsi_pilot_exact_task_pr_status_check_observation_contract as status_parent  # noqa: E402
import rsi_pilot_exact_task_pr_status_review_thread_credential_capability_contract as capability_parent  # noqa: E402
import rsi_pilot_exact_task_pr_submitted_review_observation_contract as review_parent  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-pr-review-thread-state-observation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        observation.PilotExactTaskPrReviewThreadStateObservationError,
        capability.PilotExactTaskPrStatusReviewThreadCredentialCapabilityError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-083 unexpectedly accepted unsafe review-thread state")


def _stream(payload: bytes) -> BoundedStreamEvidence:
    return BoundedStreamEvidence(
        prefix=payload,
        total_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        truncated=False,
    )


def _live_capability():
    preflight, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = (
        status_parent._live_preflight()
    )
    checks = [
        status_parent._check(preflight, run_id=9401, name="ci"),
        status_parent._check(
            preflight,
            run_id=9402,
            name="agent3-diagnostics",
            status="in_progress",
            conclusion=None,
        ),
    ]
    statuses = [
        status_parent._legacy(
            status_id=9501,
            context="legacy/security",
            state="success",
        )
    ]
    source = status_parent._observe(
        preflight,
        status_parent._stable_transport(preflight, checks, statuses),
    )
    assert source.observation_authenticated is True

    broker_temp = TemporaryDirectory(prefix="rsi-review-thread-state-broker-083-")
    broker_path = Path(broker_temp.name) / "rsi-github-review-thread-read-broker-v1"
    broker_raw = b"review-thread-read-broker-083"
    broker_path.write_bytes(broker_raw)
    broker_path.chmod(0o755)

    descriptor = capability_parent._descriptor()
    descriptor["broker_executable_path"] = os.fspath(broker_path)
    descriptor["broker_executable_path_sha256"] = hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(broker_path)))
    ).hexdigest()
    descriptor["broker_executable_sha256"] = hashlib.sha256(broker_raw).hexdigest()

    cap = capability._materialize_verified_pilot_exact_task_pr_status_review_thread_credential_capability(
        status_check_observation=source,
        broker_descriptor=descriptor,
        now_provider=lambda: "2026-09-15T06:26:00Z",
    )
    assert cap.capability_authenticated is True
    return (
        cap,
        source,
        preflight,
        broker_temp,
        broker_path,
        broker_raw,
        ledger_temp,
        tx_ledger,
        write_temp,
        parent_temp,
        cleanup,
    )


def _thread(node_id, path, *, resolved, outdated):
    return {
        "id": node_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
    }


def _data(cap, *, cursor, variant="stable"):
    if cursor is None:
        nodes = [
            _thread("PRRT_083_A", "backend/a.py", resolved=True, outdated=False),
            _thread("PRRT_083_B", "worker/b.py", resolved=False, outdated=False),
        ]
        has_next = True
        end_cursor = "CURSOR_083_1"
    elif cursor == "CURSOR_083_1":
        node = _thread(
            "PRRT_083_C",
            "desktop/c.py",
            resolved=False,
            outdated=True,
        )
        if variant == "drift":
            node["isResolved"] = True
        if variant == "duplicate":
            node["id"] = "PRRT_083_B"
        nodes = [node]
        has_next = False
        end_cursor = "CURSOR_083_2"
    else:
        raise AssertionError(f"unexpected cursor: {cursor!r}")

    if variant == "cursor-loop" and cursor is None:
        end_cursor = "CURSOR_083_1"
    elif variant == "cursor-loop" and cursor == "CURSOR_083_1":
        has_next = True
        end_cursor = "CURSOR_083_1"

    decision = "APPROVED"
    if variant == "unsupported-decision":
        decision = "SOMETHING_NEW"

    return {
        "repository": {
            "pullRequest": {
                "id": review_parent.PR_NODE_ID,
                "number": cap.pull_request_number,
                "state": "OPEN",
                "isDraft": False,
                "baseRefName": cap.base_branch,
                "headRefName": cap.head_branch,
                "headRefOid": (
                    "1" * 40 if variant == "head-drift" else cap.predicted_commit_sha
                ),
                "reviewDecision": decision,
                "reviewThreads": {
                    "nodes": nodes,
                    "pageInfo": {
                        "hasNextPage": has_next,
                        "endCursor": end_cursor,
                    },
                },
            }
        }
    }


def _runner(cap, *, mode="stable", calls=None):
    calls = [] if calls is None else calls

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
        request = json.loads(stdin_bytes.decode("utf-8"))
        assert args[0]
        assert args[1:] == (
            "--protocol",
            capability.PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
            "--request-stdin-json",
            "--response-stdout-json",
        )
        assert Path(cwd) == Path(args[0]).parent
        assert timeout_seconds == 60
        assert max_output_bytes == 512 * 1024
        assert stdout_prefix_bytes == 512 * 1024
        assert stderr_prefix_bytes == 512 * 1024
        assert not any(
            marker in key.upper()
            for key in env
            for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER", "COOKIE")
        )
        assert request["schema"] == observation.PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_REQUEST_SCHEMA
        assert request["operation"] == cap.graphql_operation
        assert request["graphql_endpoint"] == cap.graphql_endpoint
        assert request["graphql_query_sha256"] == cap.graphql_query_sha256
        assert request["review_thread_credential_capability_sha256"] == cap.sha256
        assert request["repository"] == cap.repository
        assert request["pull_request_number"] == cap.pull_request_number
        assert request["pull_request_node_id_sha256"] == cap.pull_request_node_id_sha256
        assert request["head_sha"] == cap.predicted_commit_sha
        variables = request["variables"]
        assert variables["owner"] == "Ternedal"
        assert variables["name"] == "ModelRig"
        assert variables["number"] == cap.pull_request_number
        cursor = variables["threadsCursor"]

        call_number = len(calls)
        variant = mode
        if mode == "second-snapshot-drift":
            variant = "drift" if call_number >= 2 else "stable"
        elif mode == "node-drift":
            variant = "node-drift"
        data = _data(cap, cursor=cursor, variant=variant)
        if mode == "node-drift":
            data["repository"]["pullRequest"]["id"] = "PR_WRONG_083"

        request_sha = hashlib.sha256(stdin_bytes).hexdigest()
        response = {
            "schema": observation.PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_RESPONSE_SCHEMA,
            "operation": cap.graphql_operation,
            "request_sha256": request_sha,
            "review_thread_credential_capability_sha256": cap.sha256,
            "data": data,
        }
        stdout = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        calls.append((request, response))
        stderr = b"broker-noise" if mode == "stderr" else b""
        return BoundedSubprocessResult(
            args=args,
            returncode=0,
            stdout=_stream(stdout),
            stderr=_stream(stderr),
            total_output_bytes=len(stdout) + len(stderr),
            output_limit_exceeded=False,
            timed_out=False,
            process_tree_terminated=False,
        )

    return run


def _observe(cap, runner, times=("2026-09-15T06:26:01Z", "2026-09-15T06:26:02Z")):
    clock = iter(times)
    return observation._observe_verified_pilot_exact_task_pr_review_thread_state(
        review_thread_credential_capability=cap,
        subprocess_runner=runner,
        now_provider=clock.__next__,
        broker_host_control_required=False,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    capability_parent.run_contract()
    (
        cap,
        source,
        preflight,
        broker_temp,
        broker_path,
        broker_raw,
        ledger_temp,
        tx_ledger,
        write_temp,
        parent_temp,
        cleanup,
    ) = _live_capability()
    try:
        calls = []
        result = _observe(cap, _runner(cap, calls=calls))
        assert result.observation_authenticated is True
        assert len(calls) == 4
        assert result.review_thread_credential_capability_sha256 == cap.sha256
        assert result.status_check_observation_sha256 == source.sha256
        assert result.merge_preflight_sha256 == cap.merge_preflight_sha256
        assert result.predicted_commit_sha == cap.predicted_commit_sha
        assert result.check_runs_inventory_sha256 == source.check_runs_inventory_sha256
        assert result.legacy_statuses_inventory_sha256 == source.legacy_statuses_inventory_sha256
        assert result.github_review_decision == "APPROVED"
        assert result.review_thread_count == 3
        assert result.unresolved_review_thread_count == 2
        assert result.unresolved_outdated_review_thread_count == 1
        assert result.review_thread_page_count == 2
        assert result.first_review_threads_inventory_sha256 == result.second_review_threads_inventory_sha256
        assert result.first_broker_evidence_sha256 == result.second_broker_evidence_sha256

        for field in (
            "source_capability_verified",
            "source_status_check_observation_verified",
            "source_approved_review_preflight_verified",
            "source_status_policy_not_evaluated",
            "source_required_status_checks_not_evaluated",
            "fresh_capability_age_verified",
            "broker_binary_reverified",
            "graphql_fixed_query_verified",
            "exact_pr_identity_revalidated",
            "exact_head_revalidated",
            "review_decision_observed",
            "review_threads_observed",
            "review_thread_inventory_complete",
            "stable_double_observation_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "bounded_broker_process",
            "broker_stderr_empty",
            "pagination_bounded",
            "review_thread_state_observation_completed",
            "required_status_checks_evaluation_still_required",
            "branch_policy_still_required",
            "fresh_review_reobservation_still_required",
            "fresh_merge_transaction_revalidation_still_required",
        ):
            assert getattr(result, field) is True

        for field in (
            "review_thread_policy_evaluated",
            "required_status_checks_evaluated",
            "status_policy_evaluated",
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "label_mutation_authorized",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = observation.PilotExactTaskPrReviewThreadStateObservation.from_mapping(
            result.to_dict()
        )
        assert reloaded == result and reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        loose = capability.PilotExactTaskPrStatusReviewThreadCredentialCapability.from_mapping(
            cap.to_dict()
        )
        assert loose.capability_authenticated is False
        _reject(lambda: observation._require_live_capability(loose))
        _reject(lambda: _observe(loose, _runner(cap)))

        # Exactly 10 seconds from capability materialization is accepted; 11 is stale.
        _observe(
            cap,
            _runner(cap),
            times=("2026-09-15T06:26:10Z", "2026-09-15T06:26:10Z"),
        )
        _reject(
            lambda: _observe(
                cap,
                _runner(cap),
                times=("2026-09-15T06:26:11Z", "2026-09-15T06:26:11Z"),
            )
        )
        _reject(
            lambda: _observe(
                cap,
                _runner(cap),
                times=("2026-09-15T06:25:59Z", "2026-09-15T06:26:00Z"),
            )
        )

        _reject(lambda: _observe(cap, _runner(cap, mode="second-snapshot-drift")))
        _reject(lambda: _observe(cap, _runner(cap, mode="head-drift")))
        _reject(lambda: _observe(cap, _runner(cap, mode="node-drift")))
        _reject(lambda: _observe(cap, _runner(cap, mode="unsupported-decision")))
        _reject(lambda: _observe(cap, _runner(cap, mode="duplicate")))
        _reject(lambda: _observe(cap, _runner(cap, mode="cursor-loop")))
        _reject(lambda: _observe(cap, _runner(cap, mode="stderr")))

        # Broker binary drift is caught before any subprocess invocation.
        broker_path.write_bytes(b"tampered-review-thread-broker")
        drift_calls = []
        _reject(lambda: _observe(cap, _runner(cap, calls=drift_calls)))
        assert drift_calls == []
        broker_path.write_bytes(broker_raw)

        tampered = result.to_dict()
        tampered["merge_authorized"] = True
        _reject(
            lambda: observation.PilotExactTaskPrReviewThreadStateObservation.from_mapping(
                tampered
            )
        )
        tampered = result.to_dict()
        tampered["second_review_threads_inventory_sha256"] = "1" * 64
        _reject(
            lambda: observation.PilotExactTaskPrReviewThreadStateObservation.from_mapping(
                tampered
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            observation.PilotExactTaskPrReviewThreadStateObservation.__dataclass_fields__
        )
        assert len(fields) == 74
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["review_thread_policy_evaluated"]["const"] is False
        assert schema["properties"]["required_status_checks_evaluated"]["const"] is False
        assert schema["properties"]["branch_policy_still_required"]["const"] is True
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                observation.observe_pilot_exact_task_pr_review_thread_state
            ).parameters
        ) == ("review_thread_credential_capability",)
        source_text = inspect.getsource(observation)
        assert "run_bounded_subprocess" in source_text
        assert "PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_QUERY" in source_text
        assert '"Authorization"' not in source_text
        assert "Bearer " not in source_text
        for forbidden in (
            "urllib.request",
            "requests.",
            "httpx",
            "resolve_review_thread",
            "add_review_to_pr",
            "dismiss_review",
            "request_pull_request_reviewers",
            "merge_pull_request(",
            "label_pr(",
            "enable_auto_merge",
        ):
            assert forbidden not in source_text
    finally:
        broker_temp.cleanup()
        ledger_temp.cleanup()
        tx_ledger.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
