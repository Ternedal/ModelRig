"""Adversarial contract for ADR-DC-043 local-commit authorization requirements."""
from __future__ import annotations

import inspect
import json
import os
import sys
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
    improvement_pilot_exact_task_local_commit_authorization_requirements as requirements,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_object_identity as object_identity,
)
from rsi_pilot_exact_task_execution_plan_contract import _git_reader  # noqa: E402
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
    _live_plan,
)
from rsi_pilot_exact_task_prelaunch_reservation_contract import (  # noqa: E402
    _drift_after_first_snapshot_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-authorization-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-043 unexpectedly accepted invalid authority")


def _live_identity():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        task,
        fixture,
        staged,
    ) = _live_plan()
    blob_sha = "1" * 40
    index_payload = f"100644 {blob_sha} 0\tVERSION\0".encode("ascii")
    _calls, reader = _identity_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        identity = (
            object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                local_commit_plan=local_plan,
                now_provider=lambda: "2026-09-15T05:31:00Z",
            )
        )
    assert identity.identity_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        local_plan,
        identity,
        task,
        fixture,
        staged,
    )


def run_contract() -> None:
    if os.name == "nt":
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
        local_plan,
        identity,
        task,
        fixture,
        staged,
    ) = _live_identity()
    try:
        calls, reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            manifest = (
                requirements._build_verified_pilot_exact_task_local_commit_authorization_requirements(
                    object_identity=identity,
                    now_provider=lambda: "2026-09-15T05:32:00Z",
                )
            )

        # Two read-only workspace snapshots bracket pure requirements construction.
        assert len(calls) == 10
        assert manifest.local_commit_object_identity_sha256 == identity.sha256
        assert manifest.local_commit_plan_sha256 == local_plan.sha256
        assert manifest.post_execution_evaluation_sha256 == evaluation.sha256
        assert manifest.execution_transaction_sha256 == execution_receipt.sha256
        assert manifest.tier_a_receipt_sha256 == execution_receipt.tier_a_receipt_sha256
        assert manifest.execution_nonce_sha256 == execution_receipt.execution_nonce_sha256
        assert manifest.development_task_sha256 == identity.development_task_sha256
        assert manifest.task_id == task.task_id
        assert manifest.repository == task.repository
        assert manifest.base_sha == task.base_sha
        assert manifest.fixed_command_plan_sha256 == execution_plan.fixed_command_plan_sha256
        assert manifest.post_execution_workspace_snapshot_sha256 == identity.post_execution_workspace_snapshot_sha256
        assert manifest.candidate_patch_sha256 == identity.candidate_patch_sha256
        assert manifest.candidate_patch_bytes == len(staged)
        assert manifest.candidate_numstat_sha256 == identity.candidate_numstat_sha256
        assert manifest.scope_policy_sha256 == identity.scope_policy_sha256
        assert manifest.changed_paths == identity.changed_paths
        assert manifest.changed_file_count == identity.changed_file_count
        assert manifest.root_tree_sha == identity.root_tree_sha
        assert manifest.predicted_commit_sha == identity.predicted_commit_sha
        assert manifest.commit_payload_sha256 == identity.commit_payload_sha256
        assert manifest.index_manifest_sha256 == identity.index_manifest_sha256
        assert manifest.index_entry_count == identity.index_entry_count
        assert manifest.commit_subject == identity.commit_subject
        assert manifest.commit_subject_sha256 == identity.commit_subject_sha256
        assert manifest.author_name == identity.author_name
        assert manifest.author_email == identity.author_email
        assert manifest.committer_name == identity.committer_name
        assert manifest.committer_email == identity.committer_email
        assert manifest.commit_epoch_seconds == identity.commit_epoch_seconds
        assert manifest.commit_timezone == identity.commit_timezone
        assert manifest.object_format == identity.object_format
        assert manifest.source_identity_materialized_at_utc == identity.materialized_at_utc
        assert manifest.requirements_materialized_at_utc == "2026-09-15T05:32:00Z"
        assert manifest.authorization_intent == requirements.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHORIZATION_INTENT
        assert manifest.authorization_max_window_seconds == 600
        assert manifest.requirements_key_sha256 == requirements._requirements_key_from_values(manifest)

        for field in (
            "source_identity_authenticated_at_materialization",
            "fresh_workspace_snapshot_matched",
            "exact_object_identity_required",
            "fresh_human_local_commit_authorization_required",
            "one_shot_local_commit_nonce_required",
            "host_local_authorization_replay_ledger_required",
            "host_local_commit_execution_ledger_required",
            "fresh_source_identity_revalidation_before_authorization_required",
            "fresh_workspace_revalidation_before_write_required",
            "exact_parent_head_revalidation_required",
            "exact_index_manifest_revalidation_required",
            "exact_root_tree_identity_required",
            "exact_predicted_commit_identity_required",
            "fixed_author_committer_identity_required",
            "fixed_commit_subject_required",
            "manual_operator_invocation_required",
            "failure_after_consumption_burns_nonce_required",
            "remote_publication_forbidden",
        ):
            assert getattr(manifest, field) is True
        for field in (
            "human_local_commit_authorization_verified",
            "local_commit_authorization_consumed",
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(manifest, field) is False

        reloaded = requirements.PilotExactTaskLocalCommitAuthorizationRequirements.from_mapping(manifest.to_dict())
        assert reloaded == manifest
        assert reloaded.sha256 == manifest.sha256

        for field, value in (
            ("requirements_key_sha256", "a" * 64),
            ("predicted_commit_sha", "b" * 40),
            ("source_identity_authenticated_at_materialization", False),
            ("fresh_human_local_commit_authorization_required", False),
            ("authorization_max_window_seconds", 601),
            ("local_commit_authorized", True),
            ("git_object_write_authorized", True),
            ("author_name", "Caller Controlled"),
            ("object_format", "sha256"),
        ):
            _reject(
                lambda field=field, value=value: requirements.PilotExactTaskLocalCommitAuthorizationRequirements.from_mapping(
                    {**manifest.to_dict(), field: value}
                )
            )

        reloaded_identity = object_identity.PilotExactTaskLocalCommitObjectIdentity.from_mapping(identity.to_dict())
        assert reloaded_identity.identity_authenticated is False
        _reject(
            lambda: requirements._build_verified_pilot_exact_task_local_commit_authorization_requirements(
                object_identity=reloaded_identity,
                now_provider=lambda: "2026-09-15T05:32:01Z",
            )
        )

        rollback_calls, rollback_reader = _git_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=rollback_reader):
            _reject(
                lambda: requirements._build_verified_pilot_exact_task_local_commit_authorization_requirements(
                    object_identity=identity,
                    now_provider=lambda: "2026-09-15T05:30:59Z",
                )
            )
        assert rollback_calls

        drift_calls, drift_reader = _drift_after_first_snapshot_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(
                lambda: requirements._build_verified_pilot_exact_task_local_commit_authorization_requirements(
                    object_identity=identity,
                    now_provider=lambda: "2026-09-15T05:32:02Z",
                )
            )
        assert drift_calls

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(manifest.to_dict())
        assert set(schema["required"]) == set(manifest.to_dict())
        assert props["fresh_human_local_commit_authorization_required"]["const"] is True
        assert props["one_shot_local_commit_nonce_required"]["const"] is True
        assert props["git_object_write_authorized"]["const"] is False
        assert props["local_ref_update_authorized"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["local_commit_created"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            requirements.build_pilot_exact_task_local_commit_authorization_requirements
        ).parameters
        assert tuple(public_parameters) == ("object_identity",)

        source = inspect.getsource(requirements)
        assert "_GitWorkspaceEvidence(" in source
        assert ".run(" not in source
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
