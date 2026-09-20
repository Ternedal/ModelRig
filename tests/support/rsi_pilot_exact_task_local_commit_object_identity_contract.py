"""Adversarial contract for ADR-DC-042 exact local commit object identity."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from datetime import datetime, timezone
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
    improvement_pilot_exact_task_local_commit_object_identity as object_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_plan as commit_plan,
)
from rsi_pilot_exact_task_execution_plan_contract import _git_reader  # noqa: E402
from rsi_pilot_exact_task_local_commit_plan_contract import _live_evaluation  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-object-identity-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-042 unexpectedly accepted invalid authority")


def _live_plan():
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
    _calls, reader = _git_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        plan = commit_plan._materialize_verified_pilot_exact_task_local_commit_plan(
            evaluation_receipt=evaluation,
            now_provider=lambda: "2026-09-15T05:30:00Z",
        )
    assert plan.plan_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        evaluation,
        execution_receipt,
        execution_plan,
        plan,
        task,
        fixture,
        staged,
    )


def _identity_reader(
    *,
    workspace: Path,
    base_sha: str,
    staged: bytes,
    index_payload: bytes,
    object_format: bytes = b"sha1\n",
    drift_after_index: bool = False,
):
    snapshot_number = 0
    calls: list[tuple[str, ...]] = []

    def run(args, *, cwd, **_kwargs):
        nonlocal snapshot_number
        args = tuple(args)
        calls.append(args)
        assert Path(cwd) == workspace
        if args == ("rev-parse", "--show-toplevel"):
            snapshot_number += 1
            return (os.fspath(workspace) + "\n").encode("utf-8")
        if args == ("rev-parse", "HEAD"):
            head = base_sha
            if drift_after_index and snapshot_number >= 2:
                head = "f" * 40
            return (head + "\n").encode("ascii")
        if args == (
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        ):
            return staged
        if args == (
            "diff",
            "--binary",
            "--full-index",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        ):
            return b""
        if args == ("ls-files", "--others", "--exclude-standard", "-z"):
            return b""
        if args == ("rev-parse", "--show-object-format"):
            return object_format
        if args == ("ls-files", "--stage", "-z", "--"):
            return index_payload
        raise AssertionError(f"ADR-DC-042 attempted unexpected Git command: {args!r}")

    return calls, run


def _git_sha1(kind: str, payload: bytes) -> str:
    return hashlib.sha1(
        f"{kind} {len(payload)}\0".encode("ascii") + payload
    ).hexdigest()


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
        task,
        fixture,
        staged,
    ) = _live_plan()
    try:
        blob_sha = "1" * 40
        index_payload = f"100644 {blob_sha} 0\tVERSION\0".encode("ascii")
        calls, reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        materialized_at = "2026-09-15T05:31:00Z"
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            identity = (
                object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                    local_commit_plan=local_plan,
                    now_provider=lambda: materialized_at,
                )
            )

        assert len(calls) == 12
        assert calls[5] == ("rev-parse", "--show-object-format")
        assert calls[6] == ("ls-files", "--stage", "-z", "--")
        assert identity.identity_authenticated is True
        assert identity.local_commit_plan_sha256 == local_plan.sha256
        assert identity.post_execution_evaluation_sha256 == evaluation.sha256
        assert identity.execution_transaction_sha256 == execution_receipt.sha256
        assert identity.tier_a_receipt_sha256 == execution_receipt.tier_a_receipt_sha256
        assert identity.execution_nonce_sha256 == execution_receipt.execution_nonce_sha256
        assert identity.development_task_sha256 == local_plan.development_task_sha256
        assert identity.task_id == task.task_id
        assert identity.repository == task.repository
        assert identity.base_sha == task.base_sha
        assert identity.fixed_command_plan_sha256 == execution_plan.fixed_command_plan_sha256
        assert identity.candidate_patch_sha256 == local_plan.candidate_patch_sha256
        assert identity.candidate_patch_bytes == len(staged)
        assert identity.candidate_numstat_sha256 == local_plan.candidate_numstat_sha256
        assert identity.scope_policy_sha256 == local_plan.scope_policy_sha256
        assert identity.changed_paths == local_plan.changed_paths
        assert identity.changed_file_count == local_plan.changed_file_count
        assert identity.commit_subject == local_plan.commit_subject
        assert identity.planned_at_utc == local_plan.planned_at_utc
        assert identity.materialized_at_utc == materialized_at
        assert identity.object_format == "sha1"
        assert identity.index_manifest_sha256 == hashlib.sha256(index_payload).hexdigest()
        assert identity.index_entry_count == 1

        expected_tree_payload = b"100644 VERSION\0" + bytes.fromhex(blob_sha)
        expected_tree_sha = _git_sha1("tree", expected_tree_payload)
        assert identity.root_tree_sha == expected_tree_sha

        epoch = int(
            datetime.strptime(materialized_at, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        expected_actor = (
            f"{object_identity.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME} "
            f"<{object_identity.PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL}> "
            f"{epoch} +0000"
        )
        expected_payload = (
            f"tree {expected_tree_sha}\n"
            f"parent {task.base_sha}\n"
            f"author {expected_actor}\n"
            f"committer {expected_actor}\n"
            "\n"
            f"{local_plan.commit_subject}\n"
        ).encode("utf-8")
        assert identity.commit_epoch_seconds == epoch
        assert identity.commit_payload_sha256 == hashlib.sha256(expected_payload).hexdigest()
        assert identity.predicted_commit_sha == _git_sha1("commit", expected_payload)
        assert identity.local_commit_plan_authenticated is True
        assert identity.fresh_workspace_snapshot_matched is True
        assert identity.index_manifest_bound is True
        assert identity.root_tree_identity_materialized is True
        assert identity.commit_object_identity_materialized is True
        assert identity.git_object_write_authorized is False
        assert identity.local_ref_update_authorized is False
        assert identity.local_commit_authorized is False
        assert identity.local_commit_created is False
        assert identity.push_authorized is False
        assert identity.production_activation_authorized is False

        reloaded = object_identity.PilotExactTaskLocalCommitObjectIdentity.from_mapping(
            identity.to_dict()
        )
        assert reloaded == identity
        assert reloaded.sha256 == identity.sha256
        assert reloaded.identity_authenticated is False

        for field, value in (
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("local_commit_created", True),
            ("push_authorized", True),
            ("production_activation_authorized", True),
            ("predicted_commit_sha", "a" * 40),
            ("root_tree_sha", "b" * 40),
            ("author_name", "Caller Controlled"),
        ):
            _reject(
                lambda field=field, value=value: (
                    object_identity.PilotExactTaskLocalCommitObjectIdentity.from_mapping(
                        {**identity.to_dict(), field: value}
                    )
                )
            )

        reloaded_plan = commit_plan.PilotExactTaskLocalCommitPlan.from_mapping(
            local_plan.to_dict()
        )
        assert reloaded_plan.plan_authenticated is False
        _reject(
            lambda: object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                local_commit_plan=reloaded_plan,
                now_provider=lambda: "2026-09-15T05:31:01Z",
            )
        )

        conflict_payload = f"100644 {blob_sha} 1\tVERSION\0".encode("ascii")
        _calls, conflict_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=conflict_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=conflict_reader):
            _reject(
                lambda: object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                    local_commit_plan=local_plan,
                    now_provider=lambda: "2026-09-15T05:31:02Z",
                )
            )

        _calls, sha256_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
            object_format=b"sha256\n",
        )
        with patch.object(fixture["git_runner"], "run", side_effect=sha256_reader):
            _reject(
                lambda: object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                    local_commit_plan=local_plan,
                    now_provider=lambda: "2026-09-15T05:31:03Z",
                )
            )

        drift_calls, drift_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
            drift_after_index=True,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
            _reject(
                lambda: object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                    local_commit_plan=local_plan,
                    now_provider=lambda: "2026-09-15T05:31:04Z",
                )
            )
        assert drift_calls

        rollback_calls, rollback_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=rollback_reader):
            _reject(
                lambda: object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
                    local_commit_plan=local_plan,
                    now_provider=lambda: "2026-09-15T05:29:59Z",
                )
            )
        assert rollback_calls

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(identity.to_dict())
        assert set(schema["required"]) == set(identity.to_dict())
        assert props["commit_object_identity_materialized"]["const"] is True
        assert props["git_object_write_authorized"]["const"] is False
        assert props["local_ref_update_authorized"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["local_commit_created"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            object_identity.materialize_pilot_exact_task_local_commit_object_identity
        ).parameters
        assert tuple(public_parameters) == ("local_commit_plan",)

        source = inspect.getsource(object_identity)
        assert '("ls-files", "--stage", "-z", "--")' in source
        assert '("rev-parse", "--show-object-format")' in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '"write-tree"' not in source
        assert '"commit-tree"' not in source
        # Read-only commit identity hashing is allowed; Git commit execution is not.
        assert '.run(("commit",' not in source
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
