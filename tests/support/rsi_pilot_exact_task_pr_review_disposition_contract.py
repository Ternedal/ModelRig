"""Adversarial contract for ADR-DC-079 exact review disposition."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_review_disposition as disposition  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_submitted_review_observation as observation  # noqa: E402
import rsi_pilot_exact_task_pr_submitted_review_observation_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-review-disposition-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        disposition.PilotExactTaskPrReviewDispositionError,
        observation.PilotExactTaskPrSubmittedReviewObservationError,
        ValueError, TypeError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-079 unexpectedly accepted unsafe review disposition")


def _evaluate(value):
    return disposition._evaluate_verified_pilot_exact_task_pr_review_disposition(
        submitted_review_observation=value,
        now_provider=lambda: "2026-09-15T06:25:50Z",
    )


def _observation(checkpoint, *, state=None, stale=False, pending=False):
    rows = []
    if state is not None:
        rows.append(parent._review(
            checkpoint, review_id=9001, node_id=f"PRR_079_{state}", state=state,
            commit_id="1" * 40 if stale else checkpoint.predicted_commit_sha,
            submitted_at="2026-09-15T06:25:47Z",
        ))
    if pending:
        rows.append(parent._review(
            checkpoint, review_id=9002, node_id="PRR_079_PENDING", state="PENDING", submitted_at=None,
        ))
    return parent._observe(checkpoint, parent._stable_transport(checkpoint, rows, requested=False))


def run_contract() -> None:
    if os.name == "nt":
        return
    parent.run_contract()
    checkpoint, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = parent._live_checkpoint()
    try:
        approved_source = _observation(checkpoint, state="APPROVED")
        approved = _evaluate(approved_source)
        assert approved.disposition_authenticated is True
        assert approved.submitted_review_observation_sha256 == approved_source.sha256
        assert approved.review_disposition_policy_sha256 == disposition._policy_sha256()
        assert approved.review_disposition == "APPROVED"
        assert approved.disposition_reason == "latest-exact-head-review-approved"
        assert approved.review_policy_evaluated is True
        assert approved.review_policy_passed is True
        assert approved.exact_head_approval_verified is True
        assert approved.stale_head_reviews_ignored is True
        assert approved.pinned_reviewer_only_policy is True
        assert approved.fresh_merge_preflight_required is True
        assert approved.semantic_pr_metadata_policy_required is True
        assert approved.checkpoint_reusable is True
        for field in (
            "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized",
            "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized",
            "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized",
        ):
            assert getattr(approved, field) is False

        blocked = _evaluate(_observation(checkpoint, state="CHANGES_REQUESTED"))
        assert blocked.review_disposition == "BLOCKED"
        assert blocked.disposition_reason == "latest-exact-head-review-changes-requested"
        assert blocked.review_policy_passed is False and blocked.exact_head_approval_verified is False

        commented = _evaluate(_observation(checkpoint, state="COMMENTED"))
        assert commented.review_disposition == "PENDING"
        assert commented.disposition_reason == "latest-exact-head-review-commented"

        dismissed = _evaluate(_observation(checkpoint, state="DISMISSED"))
        assert dismissed.review_disposition == "PENDING"
        assert dismissed.disposition_reason == "latest-exact-head-review-dismissed"

        none = _evaluate(_observation(checkpoint))
        assert none.review_disposition == "PENDING"
        assert none.disposition_reason == "no-submitted-exact-head-review"

        stale = _evaluate(_observation(checkpoint, state="APPROVED", stale=True))
        assert stale.review_disposition == "PENDING"
        assert stale.disposition_reason == "no-submitted-exact-head-review"
        assert stale.pinned_stale_head_review_count == 1 and stale.pinned_exact_head_review_count == 0

        pending = _evaluate(_observation(checkpoint, state="APPROVED", pending=True))
        assert pending.review_disposition == "PENDING"
        assert pending.disposition_reason == "pending-exact-head-review-present"
        assert pending.review_policy_passed is False

        reloaded_source = observation.PilotExactTaskPrSubmittedReviewObservation.from_mapping(approved_source.to_dict())
        assert reloaded_source.observation_authenticated is False
        _reject(lambda: disposition._require_live_observation(reloaded_source))

        reloaded = disposition.PilotExactTaskPrReviewDisposition.from_mapping(approved.to_dict())
        assert reloaded == approved and reloaded.sha256 == approved.sha256
        assert reloaded.disposition_authenticated is False

        tampered = approved.to_dict(); tampered["review_disposition_policy_sha256"] = "1" * 64
        _reject(lambda: disposition.PilotExactTaskPrReviewDisposition.from_mapping(tampered))
        _reject(lambda: disposition._evaluate_verified_pilot_exact_task_pr_review_disposition(
            submitted_review_observation=approved_source,
            now_provider=lambda: "2026-09-15T06:25:48Z",
        ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(disposition.PilotExactTaskPrReviewDisposition.__dataclass_fields__)
        assert len(fields) == 54
        assert set(schema["properties"]) == fields and set(schema["required"]) == fields
        assert schema["properties"]["review_policy_evaluated"]["const"] is True
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(inspect.signature(disposition.evaluate_pilot_exact_task_pr_review_disposition).parameters) == ("submitted_review_observation",)
        source = inspect.getsource(disposition)
        for forbidden in (
            "UrllibReadOnlyTransport", "run_bounded_subprocess", "request_pull_request_reviewers",
            "add_review_to_pr", "resolve_review_thread", "merge_pull_request(", "label_pr(",
        ):
            assert forbidden not in source
    finally:
        ledger_temp.cleanup(); tx_ledger.cleanup(); write_temp.cleanup(); parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
