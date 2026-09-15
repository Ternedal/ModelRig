"""Adversarial contract for ADR-DC-093 fresh post-policy review reobservation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEV = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEV):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_post_policy_review_state_observation as observation
from kaliv_dev_control import improvement_pilot_exact_task_pr_post_policy_review_read_capability as capability
import rsi_pilot_exact_task_pr_post_policy_review_read_capability_contract as parent
import rsi_pilot_exact_task_pr_strict_synced_review_thread_state_observation_contract as observation_parent

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-post-policy-review-state-observation-v1.schema.json"


def _reject(fn):
    try:
        fn()
    except (
        observation.PilotExactTaskPrPostPolicyReviewStateObservationError,
        capability.PilotExactTaskPrPostPolicyReviewReadCapabilityError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-093 accepted unsafe post-policy review observation")


def _source():
    review_policy, prior_observation, prior_capability, strict, descriptor, items, temp = parent._source()
    cap = parent._materialize(review_policy, descriptor, at="2026-09-15T19:30:21Z")
    assert cap.capability_authenticated is True
    return cap, review_policy, prior_observation, prior_capability, strict, descriptor, items, temp


def _observe(cap, runner, *, times=("2026-09-15T19:30:22Z", "2026-09-15T19:30:23Z")):
    clock = iter(times)
    return observation._observe_verified_pilot_exact_task_pr_post_policy_review_state(
        post_policy_review_read_capability=cap,
        subprocess_runner=runner,
        now_provider=clock.__next__,
        require_host_control=False,
    )


def run_contract():
    if os.name == "nt":
        return
    parent.run_contract()
    cap, review_policy, prior_observation, prior_capability, strict, descriptor, items, temp = _source()
    broker = Path(descriptor["broker_executable_path"])
    broker_bytes = broker.read_bytes()
    try:
        runner = observation_parent._Runner(cap)
        result = _observe(cap, runner)
        assert result.observation_authenticated is True
        assert result.post_policy_review_read_capability_sha256 == cap.sha256
        assert result.review_policy_sha256 == review_policy.sha256
        assert result.prior_review_thread_state_observation_sha256 == prior_observation.sha256
        assert result.prior_review_read_capability_sha256 == prior_capability.sha256
        assert result.strict_base_sync_preflight_sha256 == strict.sha256
        assert result.ruleset_applicability_sha256 == review_policy.ruleset_applicability_sha256
        assert result.ruleset_observation_sha256 == review_policy.ruleset_observation_sha256
        assert result.branch_protection_observation_sha256 == review_policy.branch_protection_observation_sha256
        assert result.effective_review_policy_sha256 == review_policy.effective_review_policy_sha256
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

        live = observation._get_live_pr_post_policy_review_state_observation_inputs(result)
        assert live is not None
        assert live["post_policy_review_read_capability"] is cap
        assert len(live["review_threads"]) == 2

        replay = observation.PilotExactTaskPrPostPolicyReviewStateObservation.from_mapping(result.to_dict())
        assert replay == result and replay.observation_authenticated is False

        loose = capability.PilotExactTaskPrPostPolicyReviewReadCapability.from_mapping(cap.to_dict())
        untouched = observation_parent._Runner(cap)
        _reject(lambda: _observe(loose, untouched))
        assert untouched.calls == []

        stale = observation_parent._Runner(cap)
        _reject(lambda: _observe(cap, stale, times=("2026-09-15T19:30:32Z", "2026-09-15T19:30:33Z")))
        assert stale.calls == []

        _reject(lambda: _observe(cap, observation_parent._Runner(cap, duplicate=True)))
        _reject(lambda: _observe(cap, observation_parent._Runner(cap, cursor_loop=True)))
        _reject(lambda: _observe(cap, observation_parent._Runner(cap, wrong_head=True)))
        _reject(lambda: _observe(cap, observation_parent._Runner(cap, wrong_number=True)))
        _reject(lambda: _observe(cap, observation_parent._Runner(cap, bad_binding=True)))
        _reject(lambda: _observe(cap, observation_parent._Runner(cap, stderr=True)))
        _reject(lambda: _observe(cap, observation_parent._Runner(cap, malformed=True)))
        _reject(lambda: _observe(cap, observation_parent._Runner(cap, drift_second_snapshot=True)))
        _reject(lambda: _observe(
            cap, observation_parent._Runner(cap),
            times=("2026-09-15T19:30:22Z", "2026-09-15T19:30:53Z"),
        ))
        _reject(lambda: _observe(
            cap, observation_parent._Runner(cap),
            times=("2026-09-15T19:30:23Z", "2026-09-15T19:30:22Z"),
        ))

        broker.write_bytes(b"tampered-post-policy-broker\n")
        _reject(lambda: _observe(cap, observation_parent._Runner(cap)))
        broker.write_bytes(broker_bytes)
        broker.chmod(0o755)

        tampered = result.to_dict()
        tampered["merge_authorized"] = True
        _reject(lambda: observation.PilotExactTaskPrPostPolicyReviewStateObservation.from_mapping(tampered))
        tampered = result.to_dict()
        tampered["review_threads_inventory_sha256"] = "4" * 64
        _reject(lambda: observation.PilotExactTaskPrPostPolicyReviewStateObservation.from_mapping(tampered))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(observation.PilotExactTaskPrPostPolicyReviewStateObservation.__dataclass_fields__)
        assert len(fields) == 69
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["fresh_review_reobservation_completed"]["const"] is True
        assert schema["properties"]["review_policy_evaluation_required"]["const"] is True
        assert schema["properties"]["review_thread_policy_evaluated"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(
            inspect.signature(observation.observe_pilot_exact_task_pr_post_policy_review_state).parameters
        ) == ("post_policy_review_read_capability",)

        source = inspect.getsource(observation)
        assert "_snapshot" in source
        for forbidden in (
            "resolve_review_thread(", "unresolve_review_thread(", "add_review_to_pr(",
            "dismiss_pull_request_review(", "request_pull_request_reviewers(",
            "merge_pull_request(", "enable_auto_merge(", "label_pr(",
        ):
            assert forbidden not in source
    finally:
        parent.parent.parent.parent._cleanup(items)
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
