"""Adversarial contract for ADR-DC-041 inert exact local-commit planning."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import weakref
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_plan as commit_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_execution_evaluation as post_evaluation,
)
from rsi_pilot_exact_task_execution_plan_contract import _git_reader  # noqa: E402
from rsi_pilot_exact_task_post_execution_evaluation_contract import (  # noqa: E402
    _evaluation_reader,
    _live_execution,
)
from rsi_pilot_exact_task_prelaunch_reservation_contract import (  # noqa: E402
    _drift_after_first_snapshot_reader,
)

_LIVE_EVALUATION_KEEPALIVES = {}


def _retain_reservation(evaluation, reservation) -> None:
    key = id(evaluation)

    def cleanup(_):
        _LIVE_EVALUATION_KEEPALIVES.pop(key, None)

    _LIVE_EVALUATION_KEEPALIVES[key] = (weakref.ref(evaluation, cleanup), reservation)


SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-plan-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-041 unexpectedly accepted invalid authority")


def _live_evaluation():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        reservation,
        execution_receipt,
        plan,
        task,
        fixture,
        staged,
    ) = _live_execution()
    numstat = b"1\t0\tVERSION\0"
    _calls, reader = _evaluation_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        numstat=numstat,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        evaluation = post_evaluation._evaluate_verified_pilot_exact_task_execution(
            execution_receipt=execution_receipt,
            now_provider=lambda: "2026-09-15T05:20:00Z",
        )
    assert evaluation.evaluation_authenticated is True
    # Keep the complete live ADR-038 -> ADR-040 provenance graph alive.
    # Later helpers intentionally omit several intermediate live objects from
    # their public fixture tuples; retaining only ADR-038 leaves weakref-backed
    # authentication vulnerable to GC at those boundaries.
    _retain_reservation(
        evaluation,
        (reservation, execution_receipt, plan, task, fixture),
    )
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        evaluation,
        execution_receipt,
        plan,
        task,
        fixture,
        staged,
    )


def run_contract() -> None:
    if os.name == "nt":
        # Synthetic Trusted-Git fixture is POSIX-only. Native Windows substrate
        # remains covered by the existing Windows DevControl jobs.
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        task,
        fixture,
        staged,
    ) = _live_evaluation()
    try:
        calls, reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            plan = commit_plan._materialize_verified_pilot_exact_task_local_commit_plan(
                evaluation_receipt=evaluation,
                now_provider=lambda: "2026-09-15T05:21:00Z",
            )

        # Two fresh read-only workspace snapshots are taken around pure plan
        # construction. No Git object/ref mutation occurs.
        assert len(calls) == 10
        assert plan.plan_authenticated is True
        assert plan.post_execution_evaluation_sha256 == evaluation.sha256
        assert plan.execution_transaction_sha256 == execution_receipt.sha256
        assert plan.tier_a_receipt_sha256 == execution_receipt.tier_a_receipt_sha256
        assert plan.execution_nonce_sha256 == execution_receipt.execution_nonce_sha256
        assert plan.development_task_sha256 == evaluation.development_task_sha256
        assert plan.task_id == task.task_id
        assert plan.repository == task.repository
        assert plan.base_sha == task.base_sha
        assert plan.fixed_command_plan_sha256 == execution_plan.fixed_command_plan_sha256
        assert (
            plan.post_execution_workspace_snapshot
            == evaluation.post_execution_workspace_snapshot
        )
        assert (
            plan.post_execution_workspace_snapshot_sha256
            == evaluation.post_execution_workspace_snapshot_sha256
        )
        assert plan.candidate_patch_sha256 == evaluation.candidate_patch_sha256
        assert plan.candidate_patch_bytes == len(staged)
        assert plan.candidate_numstat_sha256 == evaluation.candidate_numstat_sha256
        assert plan.changed_paths == ("VERSION",)
        assert plan.changed_file_count == 1
        assert plan.added_lines == 1
        assert plan.deleted_lines == 0
        assert plan.scope_policy_sha256 == evaluation.scope_policy_sha256
        assert plan.executed_command_id == evaluation.executed_command_id
        assert plan.required_tests == task.required_tests
        assert (
            plan.commit_operation
            == commit_plan.PILOT_EXACT_TASK_LOCAL_COMMIT_OPERATION
        )
        assert (
            plan.commit_message_policy
            == commit_plan.PILOT_EXACT_TASK_LOCAL_COMMIT_MESSAGE_POLICY
        )
        assert plan.commit_subject == "rsi: apply dc-l16-version-check"
        assert (
            plan.commit_subject_sha256
            == hashlib.sha256(plan.commit_subject.encode("utf-8")).hexdigest()
        )
        assert plan.evaluated_at_utc == evaluation.evaluated_at_utc
        assert plan.planned_at_utc == "2026-09-15T05:21:00Z"
        assert plan.post_execution_evaluation_authenticated is True
        assert plan.mechanical_evaluation_passed is True
        assert plan.fresh_workspace_snapshot_matched is True
        assert plan.candidate_patch_bound is True
        assert plan.commit_plan_materialized is True
        assert plan.git_object_write_authorized is False
        assert plan.local_ref_update_authorized is False
        assert plan.local_commit_authorized is False
        assert plan.local_commit_created is False
        assert plan.remote_write_authorized is False
        assert plan.push_authorized is False
        assert plan.pr_mutation_authorized is False
        assert plan.merge_authorized is False
        assert plan.release_authorized is False
        assert plan.deploy_authorized is False
        assert plan.production_activation_authorized is False

        reloaded = commit_plan.PilotExactTaskLocalCommitPlan.from_mapping(
            plan.to_dict()
        )
        assert reloaded == plan
        assert reloaded.sha256 == plan.sha256
        assert reloaded.plan_authenticated is False

        for field, value in (
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("local_commit_created", True),
            ("push_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    commit_plan.PilotExactTaskLocalCommitPlan.from_mapping(
                        {**plan.to_dict(), field: value}
                    )
                )
            )

        _reject(
            lambda: commit_plan.PilotExactTaskLocalCommitPlan.from_mapping(
                {**plan.to_dict(), "candidate_patch_sha256": ("0" if plan.candidate_patch_sha256[0] != "0" else "1") + plan.candidate_patch_sha256[1:]}
            )
        )
        _reject(
            lambda: commit_plan.PilotExactTaskLocalCommitPlan.from_mapping(
                {**plan.to_dict(), "candidate_numstat_sha256": ("0" if plan.candidate_numstat_sha256[0] != "0" else "1") + plan.candidate_numstat_sha256[1:]}
            )
        )
        _reject(
            lambda: commit_plan.PilotExactTaskLocalCommitPlan.from_mapping(
                {**plan.to_dict(), "commit_subject": "user selected message"}
            )
        )
        _reject(
            lambda: commit_plan.PilotExactTaskLocalCommitPlan.from_mapping(
                {**plan.to_dict(), "required_tests": ["other.command"]}
            )
        )

        # Reloaded ADR-DC-040 audit evidence cannot recover live planning authority.
        reloaded_evaluation = (
            post_evaluation.PilotExactTaskPostExecutionEvaluationReceipt.from_mapping(
                evaluation.to_dict()
            )
        )
        assert reloaded_evaluation.evaluation_authenticated is False
        _reject(
            lambda: commit_plan._materialize_verified_pilot_exact_task_local_commit_plan(
                evaluation_receipt=reloaded_evaluation,
                now_provider=lambda: "2026-09-15T05:21:01Z",
            )
        )

        # Clock rollback after the source evaluation cannot produce a valid plan.
        rollback_calls, rollback_reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=rollback_reader
        ):
            _reject(
                lambda: commit_plan._materialize_verified_pilot_exact_task_local_commit_plan(
                    evaluation_receipt=evaluation,
                    now_provider=lambda: "2026-09-15T05:19:59Z",
                )
            )
        assert rollback_calls

        # Any drift between the two fresh snapshots fails the plan closed.
        drift_calls, drift_reader = _drift_after_first_snapshot_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=drift_reader
        ):
            _reject(
                lambda: commit_plan._materialize_verified_pilot_exact_task_local_commit_plan(
                    evaluation_receipt=evaluation,
                    now_provider=lambda: "2026-09-15T05:21:02Z",
                )
            )
        assert drift_calls

        # A changed staged candidate is equally ineligible even when HEAD is stable.
        changed_patch = staged + b"\n"
        _calls, changed_reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=changed_patch,
        )
        with patch.object(
            fixture["git_runner"], "run", side_effect=changed_reader
        ):
            _reject(
                lambda: commit_plan._materialize_verified_pilot_exact_task_local_commit_plan(
                    evaluation_receipt=evaluation,
                    now_provider=lambda: "2026-09-15T05:21:03Z",
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(plan.to_dict())
        assert set(schema["required"]) == set(plan.to_dict())
        assert props["commit_plan_materialized"]["const"] is True
        assert props["git_object_write_authorized"]["const"] is False
        assert props["local_ref_update_authorized"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["local_commit_created"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            commit_plan.materialize_pilot_exact_task_local_commit_plan
        ).parameters
        assert tuple(public_parameters) == ("evaluation_receipt",)

        source = inspect.getsource(commit_plan)
        assert "_GitWorkspaceEvidence(" in source
        assert "run_single_verified_tier_a_command_with_receipt(" not in source
        assert "run_verified_tier_a_command(" not in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '"write-tree"' not in source
        assert '"commit-tree"' not in source
        assert '("commit",' not in source
        assert '("update-ref",' not in source
        assert '("push",' not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
    finally:
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
