"""Adversarial contract for ADR-DC-086 exact required-status evaluation."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_evaluation as evaluation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_policy as policy  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_applicability as applicability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_observation as ruleset_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_branch_protection_observation as branch_boundary  # noqa: E402
import rsi_pilot_exact_task_pr_required_status_policy_contract as policy_parent  # noqa: E402
import rsi_pilot_exact_task_pr_ruleset_applicability_preflight_contract as app_parent  # noqa: E402
import rsi_pilot_exact_task_pr_ruleset_observation_contract as fixtures  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-required-status-evaluation-v1.schema.json"
)


def _reject(fn):
    try:
        fn()
    except (
        evaluation.PilotExactTaskPrRequiredStatusEvaluationError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-086 accepted unsafe status evidence")


def _live(rows=None):
    source, ledger, tx, write, parent_temp, cleanup = app_parent._source(rows)
    app = applicability.classify_pilot_exact_task_pr_ruleset_applicability(source)
    required = policy.synthesize_pilot_exact_task_pr_required_status_policy(app)
    ruleset_live = ruleset_boundary._get_live_pr_ruleset_observation_inputs(source)
    assert ruleset_live is not None
    branch = ruleset_live["branch_protection_observation"]
    branch_live = branch_boundary._get_live_pr_branch_protection_observation_inputs(
        branch
    )
    assert branch_live is not None
    status = branch_live["status_check_observation"]
    assert required.policy_authenticated is True
    assert status.observation_authenticated is True
    return required, status, ledger, tx, write, parent_temp, cleanup


def _cleanup(items):
    _required, _status, ledger, tx, write, parent_temp, cleanup = items
    ledger.cleanup()
    tx.cleanup()
    write.cleanup()
    parent_temp.cleanup()
    for item in cleanup:
        item.cleanup()


def _check(
    *,
    run_id: int,
    name: str = "ci",
    app_id: int = 15368,
    status: str = "completed",
    conclusion: str | None = "success",
    started: str = "2026-09-15T06:25:40Z",
    completed: str = "2026-09-15T06:25:49Z",
):
    return {
        "id": run_id,
        "node_id_sha256": f"{run_id:064x}"[-64:],
        "name": name,
        "app_id": app_id,
        "app_slug": "github-actions",
        "status": status,
        "conclusion": "NONE" if conclusion is None else conclusion,
        "started_at_utc": started,
        "completed_at_utc": completed if status == "completed" else "",
    }


def _legacy(
    *,
    status_id: int,
    context: str,
    state: str,
    updated: str = "2026-09-15T06:25:49Z",
):
    return {
        "id": status_id,
        "node_id_sha256": f"{status_id:064x}"[-64:],
        "context": context,
        "state": state,
        "creator_id": 4242,
        "created_at_utc": "2026-09-15T06:25:40Z",
        "updated_at_utc": updated,
    }


def run_contract():
    if os.name == "nt":
        return

    policy_parent.run_contract()
    items = _live()
    required, status, *_ = items
    try:
        result = evaluation.evaluate_pilot_exact_task_pr_required_status(
            required, status
        )
        assert result.evaluation_authenticated is True
        assert result.required_status_policy_sha256 == required.sha256
        assert result.status_check_observation_sha256 == status.sha256
        assert result.status_evidence_sha256 == status.second_combined_evidence_sha256
        assert result.required_check_count == 3
        assert result.satisfied_check_count == 3
        assert result.missing_check_count == 0
        assert result.pending_check_count == 0
        assert result.failing_check_count == 0
        assert result.unsupported_check_count == 0
        assert result.evaluation_result == "PASS"
        assert result.required_status_checks_evaluated is True
        assert result.required_status_checks_passed is True
        assert result.strict_required_status_checks_policy is True
        assert result.strict_base_sync_preflight_required is True
        assert result.branch_policy_fully_evaluated is False
        assert result.review_threads_preflight_required is True
        assert result.merge_readiness_authorized is False
        assert result.merge_authorized is False
        assert result.production_activation_authorized is False

        replay = evaluation.PilotExactTaskPrRequiredStatusEvaluation.from_mapping(
            result.to_dict()
        )
        assert replay == result
        assert replay.evaluation_authenticated is False

        loose_policy = policy.PilotExactTaskPrRequiredStatusPolicy.from_mapping(
            required.to_dict()
        )
        assert loose_policy.policy_authenticated is False
        _reject(
            lambda: evaluation.evaluate_pilot_exact_task_pr_required_status(
                loose_policy, status
            )
        )
        loose_status = type(status).from_mapping(status.to_dict())
        assert loose_status.observation_authenticated is False
        _reject(
            lambda: evaluation.evaluate_pilot_exact_task_pr_required_status(
                required, loose_status
            )
        )

        # Receipt reloads must reject malformed audit identity, not merely lose
        # process-local authentication.
        for field, bad in (
            ("required_status_policy_sha256", "0" * 64),
            ("status_check_observation_sha256", "x" * 64),
            ("status_evidence_sha256", "0" * 64),
            ("predicted_commit_sha", "0" * 40),
            ("repository", "someone/else"),
            ("pull_request_number", 0),
            ("required_check_count", True),
        ):
            tampered = result.to_dict()
            tampered[field] = bad
            _reject(
                lambda tampered=tampered: evaluation.PilotExactTaskPrRequiredStatusEvaluation.from_mapping(
                    tampered
                )
            )
    finally:
        _cleanup(items)

    row = fixtures._list_row(
        8691,
        name="missing-required-check",
        source_type="Repository",
        source="Ternedal/ModelRig",
        enforcement="active",
    )
    detail = fixtures._detail(
        row,
        conditions={"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        rules=[
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": "missing-check", "integration_id": 15368}
                    ],
                },
            }
        ],
    )
    blocked_items = _live([(row, detail)])
    required, status, *_ = blocked_items
    try:
        blocked = evaluation.evaluate_pilot_exact_task_pr_required_status(
            required, status
        )
        assert blocked.evaluation_authenticated is True
        assert blocked.evaluation_result == "BLOCKED"
        assert blocked.missing_check_count == 1
        assert blocked.required_status_checks_evaluated is True
        assert blocked.required_status_checks_passed is False
        assert blocked.merge_authorized is False
    finally:
        _cleanup(blocked_items)

    row = fixtures._list_row(
        8692,
        name="unbound-app-check",
        source_type="Repository",
        source="Ternedal/ModelRig",
        enforcement="active",
    )
    detail = fixtures._detail(
        row,
        conditions={"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        rules=[
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": "ci", "integration_id": -1}
                    ],
                },
            }
        ],
    )
    unsupported_items = _live([(row, detail)])
    required, status, *_ = unsupported_items
    try:
        unsupported = evaluation.evaluate_pilot_exact_task_pr_required_status(
            required, status
        )
        assert unsupported.evaluation_authenticated is True
        assert unsupported.evaluation_result == "UNSUPPORTED"
        assert unsupported.unsupported_check_count == 1
        assert unsupported.required_status_checks_evaluated is False
        assert unsupported.required_status_checks_passed is False
        assert unsupported.merge_authorized is False
    finally:
        _cleanup(unsupported_items)

    # Selection regressions: a newer rerun must dominate an older success.
    older_success = _check(
        run_id=9001,
        completed="2026-09-15T06:25:48Z",
    )
    newer_pending = _check(
        run_id=9002,
        status="in_progress",
        conclusion=None,
        started="2026-09-15T06:25:50Z",
    )
    assert (
        evaluation._one_requirement(
            "ci", 15368, (older_success, newer_pending), ()
        )
        == "PENDING"
    )
    newer_failure = _check(
        run_id=9003,
        conclusion="failure",
        completed="2026-09-15T06:25:51Z",
    )
    assert (
        evaluation._one_requirement(
            "ci", 15368, (older_success, newer_failure), ()
        )
        == "FAILING"
    )

    # Equal latest timestamps cannot be ordered safely.
    tied_a = _check(run_id=9010, completed="2026-09-15T06:25:52Z")
    tied_b = _check(
        run_id=9011,
        conclusion="failure",
        completed="2026-09-15T06:25:52Z",
    )
    assert (
        evaluation._one_requirement("ci", 15368, (tied_a, tied_b), ())
        == "UNSUPPORTED"
    )

    # An unbound context seen in both GitHub status families is deliberately
    # unsupported; ADR-DC-086 never invents cross-family precedence.
    check_only = _check(run_id=9020, name="shared")
    legacy_same = _legacy(
        status_id=9021,
        context="shared",
        state="success",
        updated="2026-09-15T06:25:53Z",
    )
    assert (
        evaluation._one_requirement("shared", None, (check_only,), (legacy_same,))
        == "UNSUPPORTED"
    )

    # Legacy status selection follows the latest update and treats pending /
    # failure as blockers.
    legacy_old = _legacy(
        status_id=9030,
        context="legacy/security",
        state="success",
        updated="2026-09-15T06:25:48Z",
    )
    legacy_pending = _legacy(
        status_id=9031,
        context="legacy/security",
        state="pending",
        updated="2026-09-15T06:25:54Z",
    )
    assert (
        evaluation._one_requirement(
            "legacy/security", None, (), (legacy_old, legacy_pending)
        )
        == "PENDING"
    )
    legacy_failure = _legacy(
        status_id=9032,
        context="legacy/security",
        state="failure",
        updated="2026-09-15T06:25:55Z",
    )
    assert (
        evaluation._one_requirement(
            "legacy/security", None, (), (legacy_old, legacy_failure)
        )
        == "FAILING"
    )

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        evaluation.PilotExactTaskPrRequiredStatusEvaluation.__dataclass_fields__
    )
    assert len(fields) == 30
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["properties"]["branch_policy_fully_evaluated"]["const"] is False
    assert schema["properties"]["review_threads_preflight_required"]["const"] is True
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert schema["properties"]["production_activation_authorized"]["const"] is False
    assert tuple(
        inspect.signature(
            evaluation.evaluate_pilot_exact_task_pr_required_status
        ).parameters
    ) == ("policy", "status")
    module_source = inspect.getsource(evaluation)
    for forbidden in (
        "UrllibReadOnlyTransport",
        "run_bounded_subprocess",
        "merge_pull_request(",
        "enable_auto_merge",
        "resolve_review_thread",
        "label_pr(",
    ):
        assert forbidden not in module_source


if __name__ == "__main__":
    run_contract()
