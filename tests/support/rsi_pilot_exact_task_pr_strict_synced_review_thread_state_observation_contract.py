"""Adversarial contract for ADR-DC-090 strict-synced review-thread state observation."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEV = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEV):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as capability
import rsi_pilot_exact_task_pr_strict_synced_review_thread_read_capability_contract as parent

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-strict-synced-review-thread-state-observation-v1.schema.json"


def _reject(fn):
    try:
        fn()
    except (
        observation.PilotExactTaskPrStrictSyncedReviewThreadStateObservationError,
        capability.PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-090 accepted unsafe observation state")


def _source():
    strict, req, live, items = parent._source()
    temp = tempfile.TemporaryDirectory()
    broker = Path(temp.name) / "review-thread-read-broker"
    broker_bytes = b"modelrig-test-review-thread-broker-v1\n"
    broker.write_bytes(broker_bytes)
    broker.chmod(0o755)
    descriptor = parent._descriptor(req, strict)
    descriptor["broker_executable_path"] = os.fspath(broker)
    descriptor["broker_executable_path_sha256"] = hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(broker)))
    ).hexdigest()
    descriptor["broker_executable_sha256"] = hashlib.sha256(broker_bytes).hexdigest()
    cap = parent._materialize(
        strict, req, at="2026-09-15T19:30:18Z", descriptor=descriptor
    )
    assert cap.capability_authenticated is True
    return cap, strict, req, items, temp, broker, broker_bytes


def _stream(prefix: bytes, *, truncated=False):
    return SimpleNamespace(prefix=prefix, total_bytes=len(prefix), truncated=truncated)


class _Runner:
    def __init__(
        self,
        capability,
        *,
        drift_second_snapshot=False,
        duplicate=False,
        cursor_loop=False,
        wrong_head=False,
        wrong_number=False,
        bad_binding=False,
        stderr=False,
        malformed=False,
    ):
        self.capability = capability
        self.calls = []
        self.drift_second_snapshot = drift_second_snapshot
        self.duplicate = duplicate
        self.cursor_loop = cursor_loop
        self.wrong_head = wrong_head
        self.wrong_number = wrong_number
        self.bad_binding = bad_binding
        self.stderr = stderr
        self.malformed = malformed

    def __call__(self, command, *, cwd, env, stdin_bytes, timeout_seconds, max_output_bytes, stdout_prefix_bytes, stderr_prefix_bytes):
        request = json.loads(stdin_bytes.decode("utf-8"))
        self.calls.append(request)
        assert tuple(command[1:]) == (
            "--protocol", self.capability.credential_protocol,
            "--request-stdin-json", "--response-stdout-json",
        )
        assert all(marker not in " ".join(command).upper() for marker in ("TOKEN=", "PASSWORD=", "BEARER "))
        assert all(marker not in key.upper() for key in env for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER", "COOKIE"))
        assert request["strict_synced_review_thread_read_capability_sha256"] == self.capability.sha256
        assert request["strict_base_sync_preflight_sha256"] == self.capability.strict_base_sync_preflight_sha256
        assert request["repository"] == self.capability.repository
        assert request["pull_request_number"] == self.capability.pull_request_number
        assert request["head_sha"] == self.capability.predicted_commit_sha
        assert request["strict_base_tip_sha"] == self.capability.strict_base_tip_sha
        cursor = request["variables"]["threadsCursor"]
        page_two = cursor is not None
        snapshot_index = (len(self.calls) - 1) // 2
        decision = "CHANGES_REQUESTED" if self.drift_second_snapshot and snapshot_index >= 1 else "APPROVED"
        if not page_two:
            nodes = [{"id": "THREAD-1", "isResolved": False, "isOutdated": False, "path": "devcontrol/a.py"}]
            has_next = True
            end_cursor = "cursor-2"
        else:
            node_id = "THREAD-1" if self.duplicate else "THREAD-2"
            nodes = [{"id": node_id, "isResolved": True, "isOutdated": True, "path": "devcontrol/b.py"}]
            has_next = self.cursor_loop
            end_cursor = "cursor-2" if self.cursor_loop else None
        data = {
            "repository": {
                "pullRequest": {
                    "id": "PR_test_1519",
                    "number": self.capability.pull_request_number + (1 if self.wrong_number else 0),
                    "state": "OPEN",
                    "isDraft": False,
                    "baseRefName": "main",
                    "headRefName": "agent/rsi/remote-candidate/" + "a" * 64,
                    "headRefOid": ("f" * 40) if self.wrong_head else self.capability.predicted_commit_sha,
                    "reviewDecision": decision,
                    "reviewThreads": {
                        "nodes": nodes,
                        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                    },
                }
            }
        }
        request_sha = hashlib.sha256(
            json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        response = {
            "schema": observation.RESPONSE_SCHEMA,
            "operation": self.capability.graphql_operation,
            "request_sha256": request_sha,
            "strict_synced_review_thread_read_capability_sha256": ("f" * 64 if self.bad_binding else self.capability.sha256),
            "data": data,
        }
        stdout = b"{" if self.malformed else json.dumps(
            response, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        stderr_bytes = b"unexpected stderr" if self.stderr else b""
        return SimpleNamespace(
            returncode=0, output_limit_exceeded=False, timed_out=False,
            stdout=_stream(stdout), stderr=_stream(stderr_bytes),
        )


def _observe(cap, runner, *, times=("2026-09-15T19:30:19Z", "2026-09-15T19:30:20Z")):
    clock = iter(times)
    return observation._observe_verified_pilot_exact_task_pr_strict_synced_review_thread_state(
        review_thread_read_capability=cap,
        subprocess_runner=runner,
        now_provider=clock.__next__,
        require_host_control=False,
    )


def run_contract():
    if os.name == "nt":
        return
    parent.run_contract()
    cap, strict, req, items, temp, broker, broker_bytes = _source()
    try:
        runner = _Runner(cap)
        result = _observe(cap, runner)
        assert result.observation_authenticated is True
        assert result.review_thread_read_capability_sha256 == cap.sha256
        assert result.strict_base_sync_preflight_sha256 == strict.sha256
        assert result.review_thread_read_requirements_sha256 == req.sha256
        assert result.required_status_evaluation_sha256 == cap.required_status_evaluation_sha256
        assert result.required_status_policy_sha256 == cap.required_status_policy_sha256
        assert result.ruleset_applicability_sha256 == cap.ruleset_applicability_sha256
        assert result.ruleset_observation_sha256 == cap.ruleset_observation_sha256
        assert result.status_check_observation_sha256 == cap.status_check_observation_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == cap.pull_request_number
        assert result.predicted_commit_sha == cap.predicted_commit_sha
        assert result.strict_base_tip_sha == cap.strict_base_tip_sha
        assert result.github_review_decision == "APPROVED"
        assert result.review_thread_count == 2
        assert result.unresolved_review_thread_count == 1
        assert result.unresolved_outdated_review_thread_count == 0
        assert result.review_thread_page_count == 2
        assert len(runner.calls) == 4

        live = observation._get_live_pr_strict_synced_review_thread_state_observation_inputs(result)
        assert live is not None
        assert live["review_thread_read_capability"] is cap
        assert len(live["review_threads"]) == 2

        replay = observation.PilotExactTaskPrStrictSyncedReviewThreadStateObservation.from_mapping(result.to_dict())
        assert replay == result
        assert replay.observation_authenticated is False

        for field in (
            "source_capability_verified", "source_strict_sync_verified", "source_status_checks_passed",
            "source_strict_base_sync_passed", "fresh_capability_age_verified", "broker_binary_reverified",
            "graphql_fixed_query_verified", "exact_repository_pr_head_revalidated", "review_decision_observed",
            "review_threads_observed", "review_thread_inventory_complete", "stable_double_observation_verified",
            "credential_secret_not_loaded", "credential_broker_owns_https", "bounded_broker_process",
            "broker_stderr_empty", "pagination_bounded", "review_thread_state_observation_completed",
            "review_thread_policy_evaluation_required", "fresh_required_status_reobservation_before_merge_required",
            "fresh_review_reobservation_required", "fresh_merge_transaction_revalidation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "review_thread_mutation_authorized",
            "merge_readiness_authorized", "merge_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        loose = capability.PilotExactTaskPrStrictSyncedReviewThreadReadCapability.from_mapping(cap.to_dict())
        untouched = _Runner(cap)
        _reject(lambda: _observe(loose, untouched))
        assert untouched.calls == []

        stale = _Runner(cap)
        _reject(lambda: _observe(cap, stale, times=("2026-09-15T19:30:29Z", "2026-09-15T19:30:30Z")))
        assert stale.calls == []

        _reject(lambda: _observe(cap, _Runner(cap, duplicate=True)))
        _reject(lambda: _observe(cap, _Runner(cap, cursor_loop=True)))
        _reject(lambda: _observe(cap, _Runner(cap, wrong_head=True)))
        _reject(lambda: _observe(cap, _Runner(cap, wrong_number=True)))
        _reject(lambda: _observe(cap, _Runner(cap, bad_binding=True)))
        _reject(lambda: _observe(cap, _Runner(cap, stderr=True)))
        _reject(lambda: _observe(cap, _Runner(cap, malformed=True)))
        _reject(lambda: _observe(cap, _Runner(cap, drift_second_snapshot=True)))
        _reject(lambda: _observe(cap, _Runner(cap), times=("2026-09-15T19:30:19Z", "2026-09-15T19:30:50Z")))
        _reject(lambda: _observe(cap, _Runner(cap), times=("2026-09-15T19:30:20Z", "2026-09-15T19:30:19Z")))

        broker.write_bytes(b"tampered-broker\n")
        _reject(lambda: _observe(cap, _Runner(cap)))
        broker.write_bytes(broker_bytes)
        broker.chmod(0o755)

        tampered = result.to_dict()
        tampered["merge_authorized"] = True
        _reject(lambda: observation.PilotExactTaskPrStrictSyncedReviewThreadStateObservation.from_mapping(tampered))
        tampered = result.to_dict()
        tampered["review_threads_inventory_sha256"] = "4" * 64
        _reject(lambda: observation.PilotExactTaskPrStrictSyncedReviewThreadStateObservation.from_mapping(tampered))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(observation.PilotExactTaskPrStrictSyncedReviewThreadStateObservation.__dataclass_fields__)
        assert len(fields) == 68
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["review_thread_state_observation_completed"]["const"] is True
        assert schema["properties"]["review_thread_policy_evaluated"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(observation.observe_pilot_exact_task_pr_strict_synced_review_thread_state).parameters) == ("review_thread_read_capability",)

        source = inspect.getsource(observation)
        assert "run_bounded_subprocess" in source
        assert "Authorization" not in source
        for forbidden in (
            "resolve_review_thread(", "unresolve_review_thread(", "add_review_to_pr(",
            "dismiss_pull_request_review(", "request_pull_request_reviewers(",
            "merge_pull_request(", "enable_auto_merge(", "label_pr(",
        ):
            assert forbidden not in source
    finally:
        parent.parent._cleanup(items)
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
