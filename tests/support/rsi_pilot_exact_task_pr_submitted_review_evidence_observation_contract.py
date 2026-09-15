"""Adversarial contract for ADR-DC-093 granular submitted-review evidence."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEV = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEV):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import github_read  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_evidence_requirements as requirements_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_submitted_review_evidence_observation as observation  # noqa: E402
import rsi_pilot_exact_task_pr_review_evidence_requirements_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-submitted-review-evidence-observation-v1.schema.json"
PR_NODE_ID = "PR_test_1519"
USER_A_NODE = "U_review_a"
USER_B_NODE = "U_review_b"


def _reject(fn):
    try:
        fn()
    except (
        observation.PilotExactTaskPrSubmittedReviewEvidenceObservationError,
        requirements_boundary.PilotExactTaskPrReviewEvidenceRequirementsError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-093 accepted unsafe granular review evidence")


def _source():
    review_policy, observed, cap, strict, req, upstream_live, items, temp = parent._source()
    requirements = requirements_boundary.plan_pilot_exact_task_pr_review_evidence_requirements(review_policy)
    assert requirements.requirements_authenticated is True
    return requirements, review_policy, observed, cap, strict, req, upstream_live, items, temp


def _pr(requirements, observed, *, node_id=PR_NODE_ID, head_sha=None, head_ref=None):
    return {
        "number": requirements.pull_request_number,
        "node_id": node_id,
        "state": "open",
        "draft": False,
        "closed_at": None,
        "merged_at": None,
        "head": {
            "ref": observed.head_ref_name if head_ref is None else head_ref,
            "sha": requirements.predicted_commit_sha if head_sha is None else head_sha,
            "repo": {"full_name": "Ternedal/ModelRig"},
        },
        "base": {"ref": "main", "repo": {"full_name": "Ternedal/ModelRig"}},
    }


def _review(requirements, *, review_id, node_id, login, user_id, user_node_id, state, commit_id=None, submitted_at="2026-09-15T19:30:20Z"):
    return {
        "id": review_id,
        "node_id": node_id,
        "user": {"login": login, "id": user_id, "node_id": user_node_id},
        "state": state,
        "commit_id": requirements.predicted_commit_sha if commit_id is None else commit_id,
        "submitted_at": submitted_at,
    }


def _response(value, *, etag):
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return github_read.HttpResponse(status=200, headers={"ETag": etag}, body=body)


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        assert url.startswith("https://api.github.com/repos/Ternedal/ModelRig/")
        assert "Authorization" not in headers and "Cookie" not in headers
        assert timeout_seconds == 20
        assert 1 <= max_bytes <= 512 * 1024
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected extra GitHub read")
        return self.responses.pop(0)


def _stable_transport(requirements, observed, reviews):
    pr = _pr(requirements, observed)
    return _Transport([
        _response(pr, etag='W/"pr-093"'), _response(reviews, etag='W/"reviews-093"'),
        _response(pr, etag='W/"pr-093"'), _response(reviews, etag='W/"reviews-093"'),
    ])


def _observe(requirements, observed, transport, *, times=("2026-09-15T19:30:21Z", "2026-09-15T19:30:22Z")):
    clock = iter(times)
    return observation._observe_verified_pilot_exact_task_pr_submitted_review_evidence(
        review_evidence_requirements=requirements,
        transport=transport,
        now_provider=clock.__next__,
    )


def run_contract():
    if os.name == "nt":
        return
    parent.run_contract()
    requirements, review_policy, observed, cap, strict, req, upstream_live, items, temp = _source()
    try:
        reviews = [
            _review(requirements, review_id=9301, node_id="PRR_9301", login="reviewer-a", user_id=1001, user_node_id=USER_A_NODE, state="APPROVED"),
            _review(requirements, review_id=9302, node_id="PRR_9302", login="reviewer-a", user_id=1001, user_node_id=USER_A_NODE, state="CHANGES_REQUESTED", commit_id="1" * 40, submitted_at="2026-09-15T19:29:00Z"),
            _review(requirements, review_id=9303, node_id="PRR_9303", login="reviewer-b", user_id=1002, user_node_id=USER_B_NODE, state="COMMENTED"),
        ]
        transport = _stable_transport(requirements, observed, reviews)
        result = _observe(requirements, observed, transport)
        assert result.observation_authenticated is True
        assert result.review_evidence_requirements_sha256 == requirements.sha256
        assert result.review_policy_sha256 == review_policy.sha256
        assert result.review_thread_state_observation_sha256 == observed.sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == requirements.pull_request_number
        assert result.predicted_commit_sha == requirements.predicted_commit_sha
        assert result.pull_request_node_id_sha256 == observed.pull_request_node_id_sha256
        assert result.head_ref_name == observed.head_ref_name
        assert result.total_review_count == 3
        assert result.exact_head_review_row_count == 2
        assert result.stale_head_review_row_count == 1
        assert result.distinct_reviewer_count == 2
        assert result.exact_head_distinct_reviewer_count == 2
        assert result.review_page_count == 1
        assert result.last_push_actor_evidence_still_required is True
        assert result.code_owner_evidence_still_required is False
        assert result.last_push_actor_inferred_from_commit_metadata is False
        assert len(transport.calls) == 4

        live = observation._get_live_pr_submitted_review_evidence_observation_inputs(result)
        assert live is not None and live["review_evidence_requirements"] is requirements
        rows = live["reviews"]
        assert len(rows) == 3
        assert [row["review_id"] for row in rows] == [9301, 9302, 9303]
        assert sum(1 for row in rows if row["is_exact_head"]) == 2
        assert rows[1]["state"] == "CHANGES_REQUESTED" and rows[1]["is_exact_head"] is False

        for field in (
            "source_requirements_verified", "source_review_policy_verified", "source_review_thread_observation_verified",
            "fresh_source_age_verified", "credential_free_reads", "fixed_github_api_origin", "redirects_forbidden",
            "response_bounded", "pagination_bounded", "exact_pr_identity_revalidated", "exact_head_revalidated",
            "all_reviewer_identities_bound", "review_inventory_complete", "stable_double_observation_verified",
            "exact_head_review_rows_preserved", "stale_head_review_rows_preserved", "granular_review_evidence_observed",
            "conversation_resolution_evidence_already_bound", "review_evidence_evaluation_required",
            "merge_method_policy_still_required", "fresh_required_status_reobservation_before_merge_required",
            "fresh_review_reobservation_required", "fresh_merge_transaction_revalidation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "approval_policy_evaluated", "stale_review_policy_evaluated", "code_owner_policy_evaluated",
            "last_push_actor_inferred_from_commit_metadata", "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "review_submission_authorized", "review_thread_mutation_authorized", "merge_readiness_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        replay = observation.PilotExactTaskPrSubmittedReviewEvidenceObservation.from_mapping(result.to_dict())
        assert replay == result and replay.observation_authenticated is False
        loose = requirements_boundary.PilotExactTaskPrReviewEvidenceRequirements.from_mapping(requirements.to_dict())
        untouched = _stable_transport(requirements, observed, reviews)
        _reject(lambda: _observe(loose, observed, untouched))
        assert untouched.calls == []

        bad_pr = _pr(requirements, observed, node_id="PR_wrong")
        _reject(lambda: _observe(requirements, observed, _Transport([_response(bad_pr, etag='W/"bad"')])))
        wrong_head = _pr(requirements, observed, head_sha="f" * 40)
        _reject(lambda: _observe(requirements, observed, _Transport([_response(wrong_head, etag='W/"wrong-head"')])))

        duplicate = [reviews[0], dict(reviews[0])]
        _reject(lambda: _observe(requirements, observed, _stable_transport(requirements, observed, duplicate)))

        split = [
            _review(requirements, review_id=9401, node_id="PRR_9401", login="reviewer-a", user_id=1001, user_node_id=USER_A_NODE, state="APPROVED"),
            _review(requirements, review_id=9402, node_id="PRR_9402", login="reviewer-a", user_id=9999, user_node_id="U_conflict", state="COMMENTED"),
        ]
        _reject(lambda: _observe(requirements, observed, _stable_transport(requirements, observed, split)))

        pr = _pr(requirements, observed)
        drift = _Transport([
            _response(pr, etag='W/"pr-drift"'), _response(reviews, etag='W/"r-first"'),
            _response(pr, etag='W/"pr-drift"'), _response(reviews[:-1], etag='W/"r-second"'),
        ])
        _reject(lambda: _observe(requirements, observed, drift))

        _reject(lambda: _observe(requirements, observed, _stable_transport(requirements, observed, reviews), times=("2026-09-15T19:31:21Z", "2026-09-15T19:31:22Z")))
        _reject(lambda: _observe(requirements, observed, _stable_transport(requirements, observed, reviews), times=("2026-09-15T19:30:22Z", "2026-09-15T19:30:21Z")))

        with patch.object(observation, "_PAGE_SIZE", 1), patch.object(observation, "_MAX_PAGES", 2):
            row1 = _review(requirements, review_id=9501, node_id="PRR_9501", login="one", user_id=2001, user_node_id="U_one", state="COMMENTED")
            row2 = _review(requirements, review_id=9502, node_id="PRR_9502", login="two", user_id=2002, user_node_id="U_two", state="COMMENTED")
            _reject(lambda: observation._read_reviews(requirements, transport=_Transport([
                _response([row1], etag='W/"p1"'), _response([row2], etag='W/"p2"')
            ])))

        pending_without_time = _review(requirements, review_id=9601, node_id="PRR_9601", login="pending", user_id=3001, user_node_id="U_pending", state="PENDING", submitted_at=None)
        normalized_pending = observation._review_row(pending_without_time, requirements=requirements)
        assert normalized_pending["state"] == "PENDING" and normalized_pending["submitted_at_utc"] is None
        submitted_without_time = _review(requirements, review_id=9602, node_id="PRR_9602", login="bad-time", user_id=3002, user_node_id="U_bad", state="APPROVED", submitted_at=None)
        _reject(lambda: observation._review_row(submitted_without_time, requirements=requirements))

        tampered = result.to_dict(); tampered["merge_authorized"] = True
        _reject(lambda: observation.PilotExactTaskPrSubmittedReviewEvidenceObservation.from_mapping(tampered))
        tampered = result.to_dict(); tampered["review_inventory_sha256"] = "4" * 64
        _reject(lambda: observation.PilotExactTaskPrSubmittedReviewEvidenceObservation.from_mapping(tampered))
        tampered = result.to_dict(); tampered["last_push_actor_inferred_from_commit_metadata"] = True
        _reject(lambda: observation.PilotExactTaskPrSubmittedReviewEvidenceObservation.from_mapping(tampered))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(observation.PilotExactTaskPrSubmittedReviewEvidenceObservation.__dataclass_fields__)
        assert len(fields) == 62
        assert set(schema["properties"]) == fields and set(schema["required"]) == fields
        assert schema["properties"]["last_push_actor_inferred_from_commit_metadata"]["const"] is False
        assert schema["properties"]["approval_policy_evaluated"]["const"] is False
        assert schema["properties"]["review_evidence_evaluation_required"]["const"] is True
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(observation.observe_pilot_exact_task_pr_submitted_review_evidence).parameters) == ("review_evidence_requirements",)

        source = inspect.getsource(observation)
        assert "UrllibReadOnlyTransport" in source and "/reviews?per_page=" in source
        assert "Authorization" not in source
        for forbidden in (
            'method="POST"', 'method="PATCH"', 'method="PUT"', 'method="DELETE"',
            "run_bounded_subprocess", "request_pull_request_reviewers(", "add_review_to_pr(",
            "resolve_review_thread(", "merge_pull_request(", "enable_auto_merge(", "label_pr(",
        ):
            assert forbidden not in source
    finally:
        parent.parent.parent.parent.parent._cleanup(items)
        temp.cleanup()


if __name__ == "__main__":
    run_contract()
