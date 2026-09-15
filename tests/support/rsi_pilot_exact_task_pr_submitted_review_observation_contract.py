"""Adversarial contract for ADR-DC-078 exact submitted-review observation."""
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

from kaliv_dev_control import github_read  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_observation_checkpoint as checkpoint_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_submitted_review_observation as observation  # noqa: E402
import rsi_pilot_exact_task_pr_review_observation_checkpoint_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-submitted-review-observation-v1.schema.json"
PR_NODE_ID = "PR_kwDOTMQCit4A064"
REVIEWER_NODE_ID = "MDQ6VXNlcjI0NjgxMzU3OQ=="
SUBMITTED_AT = "2026-09-15T06:25:47Z"


def _reject(fn) -> None:
    try:
        fn()
    except (
        observation.PilotExactTaskPrSubmittedReviewObservationError,
        checkpoint_boundary.PilotExactTaskPrReviewObservationCheckpointError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-078 unexpectedly accepted unsafe review state")


def _live_checkpoint():
    source, tx_ledger, write_temp, parent_temp, cleanup = parent._live_attestation()
    ledger_temp = TemporaryDirectory(prefix="rsi-submitted-review-078-checkpoint-")
    ledger = checkpoint_boundary._ReviewObservationCheckpointLedger(Path(ledger_temp.name), require_host_control=False)
    value = checkpoint_boundary._checkpoint_verified_pilot_exact_task_pr_review_observation(
        reviewer_request_attestation=source,
        ledger=ledger,
        now_provider=lambda: "2026-09-15T06:25:46Z",
    )
    assert value.checkpoint_authenticated is True
    checkpoint_boundary._live_records.clear()
    parent.attestation._implementation._live_records.clear()
    loaded = ledger.load(value.checkpoint_key_sha256)
    assert loaded.checkpoint_authenticated is True
    return loaded, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup


def _pr_document(checkpoint, *, requested=True, node_id=PR_NODE_ID, reviewers=None):
    if reviewers is None:
        reviewers = ([{"login": checkpoint.reviewer_login, "id": checkpoint.reviewer_user_id, "node_id": REVIEWER_NODE_ID}] if requested else [])
    return {
        "number": checkpoint.pull_request_number,
        "node_id": node_id,
        "url": checkpoint.pull_request_api_url,
        "html_url": checkpoint.pull_request_html_url,
        "state": "open", "closed_at": None, "merged_at": None, "draft": False,
        "user": {"login": checkpoint.pull_request_author_login, "id": checkpoint.pull_request_author_user_id},
        "requested_reviewers": reviewers, "requested_teams": [],
        "head": {"ref": checkpoint.head_branch, "sha": checkpoint.predicted_commit_sha, "repo": {"full_name": checkpoint.repository}},
        "base": {"ref": checkpoint.base_branch, "repo": {"full_name": checkpoint.repository}},
    }


def _review(checkpoint, *, review_id, node_id, state, commit_id=None, login=None, user_id=None, submitted_at=SUBMITTED_AT):
    return {
        "id": review_id, "node_id": node_id,
        "user": {"login": checkpoint.reviewer_login if login is None else login, "id": checkpoint.reviewer_user_id if user_id is None else user_id},
        "state": state,
        "commit_id": checkpoint.predicted_commit_sha if commit_id is None else commit_id,
        "submitted_at": submitted_at,
    }


def _response(value, *, etag):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return github_read.HttpResponse(status=200, headers={"ETag": etag}, body=payload)


class _Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        assert url.startswith("https://api.github.com/")
        assert timeout_seconds == 20
        assert 1 <= max_bytes <= 512 * 1024
        assert "Authorization" not in headers and "Cookie" not in headers
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected extra GitHub read")
        return self.responses.pop(0)


def _stable_transport(checkpoint, reviews, *, requested=False):
    pr = _pr_document(checkpoint, requested=requested)
    return _Transport([
        _response(pr, etag='W/"pr-078"'), _response(reviews, etag='W/"reviews-078"'),
        _response(pr, etag='W/"pr-078"'), _response(reviews, etag='W/"reviews-078"'),
    ])


def _observe(checkpoint, transport):
    times = iter(("2026-09-15T06:25:48Z", "2026-09-15T06:25:49Z"))
    return observation._observe_verified_pilot_exact_task_pr_submitted_reviews(
        review_observation_checkpoint=checkpoint,
        transport=transport,
        now_provider=times.__next__,
    )


def run_contract() -> None:
    if os.name == "nt":
        return
    parent.run_contract()
    checkpoint, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = _live_checkpoint()
    try:
        assert checkpoint.pull_request_node_id_sha256 == hashlib.sha256(PR_NODE_ID.encode("utf-8")).hexdigest()
        assert checkpoint.reviewer_user_node_id_sha256 == hashlib.sha256(REVIEWER_NODE_ID.encode("utf-8")).hexdigest()

        reviews = [
            _review(checkpoint, review_id=7001, node_id="PRR_kwDOstale078", state="CHANGES_REQUESTED", commit_id="1" * 40, submitted_at="2026-09-15T06:25:40Z"),
            _review(checkpoint, review_id=7002, node_id="PRR_kwDOexact078", state="APPROVED"),
            _review(checkpoint, review_id=7003, node_id="PRR_kwDOother078", state="COMMENTED", login="other-reviewer", user_id=999999),
        ]
        transport = _stable_transport(checkpoint, reviews, requested=False)
        result = _observe(checkpoint, transport)
        assert result.observation_authenticated is True
        assert result.review_observation_checkpoint_sha256 == checkpoint.sha256
        assert result.checkpoint_key_sha256 == checkpoint.checkpoint_key_sha256
        assert result.reviewer_request_nonce_sha256 == checkpoint.reviewer_request_nonce_sha256
        assert result.pull_request_number == checkpoint.pull_request_number
        assert result.predicted_commit_sha == checkpoint.predicted_commit_sha
        assert result.reviewer_login == checkpoint.reviewer_login
        assert result.requested_reviewer_count == 0 and result.pinned_reviewer_request_present is False
        assert result.requested_team_count == 0 and result.review_page_count == 1
        assert result.total_review_count == 3 and result.pinned_reviewer_review_count == 2
        assert result.pinned_exact_head_review_count == 1 and result.pinned_stale_head_review_count == 1
        assert result.exact_head_approved_review_count == 1
        assert result.exact_head_changes_requested_review_count == 0
        assert result.exact_head_commented_review_count == 0
        assert result.exact_head_dismissed_review_count == 0
        assert result.exact_head_pending_review_count == 0
        assert result.latest_exact_head_review_present is True
        assert result.latest_exact_head_review_id == 7002
        assert result.latest_exact_head_review_state == "APPROVED"
        assert result.latest_exact_head_review_submitted_at_utc == SUBMITTED_AT
        assert len(transport.calls) == 4

        for field in (
            "stable_double_observation_verified", "credential_free_reads", "fixed_origin_reads", "redirects_forbidden",
            "response_bounded", "pagination_bounded", "exact_pr_identity_revalidated", "exact_head_revalidated",
            "exact_reviewer_identity_bound", "other_requested_reviewers_absent_verified", "team_reviewers_absent_verified",
            "submitted_reviews_observed", "checkpoint_reusable",
        ):
            assert getattr(result, field) is True
        for field in (
            "review_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized",
            "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized",
            "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = observation.PilotExactTaskPrSubmittedReviewObservation.from_mapping(result.to_dict())
        assert reloaded == result and reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        retained = _stable_transport(checkpoint, reviews, requested=True)
        retained_result = _observe(checkpoint, retained)
        assert retained_result.requested_reviewer_count == 1 and retained_result.pinned_reviewer_request_present is True

        none_result = _observe(checkpoint, _stable_transport(checkpoint, [], requested=True))
        assert none_result.latest_exact_head_review_present is False
        assert none_result.latest_exact_head_review_id == 0
        assert none_result.latest_exact_head_review_state == "NONE"
        assert none_result.pinned_exact_head_review_count == 0

        bad_pr = _pr_document(checkpoint, requested=False, node_id="PR_wrong")
        _reject(lambda: _observe(checkpoint, _Transport([_response(bad_pr, etag='W/"bad-pr"')])))

        other_requested = _pr_document(checkpoint, reviewers=[{"login": "someone-else", "id": 1234, "node_id": "U_other"}])
        _reject(lambda: _observe(checkpoint, _Transport([_response(other_requested, etag='W/"other"')])))

        split_reviews = [_review(checkpoint, review_id=7100, node_id="PRR_split", state="APPROVED", user_id=checkpoint.reviewer_user_id + 1)]
        _reject(lambda: _observe(checkpoint, _stable_transport(checkpoint, split_reviews, requested=False)))

        pr = _pr_document(checkpoint, requested=False)
        drift_transport = _Transport([
            _response(pr, etag='W/"pr-drift"'), _response(reviews, etag='W/"reviews-first"'),
            _response(pr, etag='W/"pr-drift"'),
            _response([_review(checkpoint, review_id=7002, node_id="PRR_kwDOexact078", state="COMMENTED")], etag='W/"reviews-second"'),
        ])
        _reject(lambda: _observe(checkpoint, drift_transport))

        full_pages = []
        next_id = 8000
        for page in range(10):
            rows = []
            for offset in range(100):
                rows.append(_review(
                    checkpoint, review_id=next_id, node_id=f"PRR_bound_{next_id}", state="COMMENTED",
                    login=f"other-{page}-{offset}", user_id=1000000 + next_id,
                ))
                next_id += 1
            full_pages.append(_response(rows, etag=f'W/"full-{page}"'))
        _reject(lambda: observation._read_reviews(checkpoint, transport=_Transport(full_pages)))

        checkpoint_copy = checkpoint_boundary.PilotExactTaskPrReviewObservationCheckpoint.from_mapping(checkpoint.to_dict())
        assert checkpoint_copy.checkpoint_authenticated is False
        _reject(lambda: observation._require_authenticated_checkpoint(checkpoint_copy))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(observation.PilotExactTaskPrSubmittedReviewObservation.__dataclass_fields__)
        assert len(fields) == 68
        assert set(schema["properties"]) == fields and set(schema["required"]) == fields
        assert schema["properties"]["review_policy_evaluated"]["const"] is False
        assert schema["properties"]["review_submission_authorized"]["const"] is False
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(observation.observe_pilot_exact_task_pr_submitted_reviews).parameters) == ("checkpoint_key_sha256",)
        source = inspect.getsource(observation)
        assert "UrllibReadOnlyTransport" in source and "/reviews" in source and "per_page=" in source
        for forbidden in ('method="POST"', "run_bounded_subprocess", "request_pull_request_reviewers", "add_review_to_pr", "resolve_review_thread", "merge_pull_request(", "label_pr("):
            assert forbidden not in source
    finally:
        ledger_temp.cleanup(); tx_ledger.cleanup(); write_temp.cleanup(); parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
