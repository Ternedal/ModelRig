"""Contract for ADR-DC-074 post-reviewer-request handoff requirements."""
from __future__ import annotations

import inspect

from kaliv_dev_control import improvement_pilot_exact_task_pr_post_reviewer_request_handoff_requirements as handoff


def run_contract() -> None:
    assert handoff.SCHEMA == "kaliv-rsi-dc-l16-exact-task-pr-post-reviewer-request-handoff-requirements/v1"
    assert tuple(inspect.signature(handoff.build_pilot_exact_task_pr_post_reviewer_request_handoff_requirements).parameters) == ("reviewer_request_transaction",)
    source = inspect.getsource(handoff)
    for forbidden in ("merge_pull_request(", "label_pr(", "request_reviewers(", "requests.post(", "production_activation_authorized\": True"):
        assert forbidden not in source
    assert '"review_observation_required": True' in source
    assert '"review_approval_not_verified": True' in source
    assert '"merge_authorized": False' in source


if __name__ == "__main__":
    run_contract()
