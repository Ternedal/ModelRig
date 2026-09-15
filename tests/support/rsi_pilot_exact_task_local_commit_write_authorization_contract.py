"""Adversarial contract for ADR-DC-043 exact local commit write authorization."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
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
    improvement_pilot_exact_task_local_commit_write_authorization as write_auth,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
    _live_plan,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-write-authorization-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-043 unexpectedly accepted invalid write authority")


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
        identity = object_identity._materialize_verified_pilot_exact_task_local_commit_object_identity(
            local_commit_plan=local_plan,
            now_provider=lambda: "2026-09-15T06:00:00Z",
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
        index_payload,
    )


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, write_auth._PilotExactTaskLocalCommitWriteAuthorizationLedger(root)


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
        index_payload,
    ) = _live_identity()
    auth_temp, ledger = _ledger("rsi-exact-task-local-write-auth-")
    try:
        calls, reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        times = iter(("2026-09-15T06:00:10Z", "2026-09-15T06:00:11Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = write_auth._authorize_verified_pilot_exact_task_local_commit_write(
                local_commit_object_identity=identity,
                ledger=ledger,
                now_provider=lambda: next(times),
            )

        assert calls.count(("rev-parse", "--show-object-format")) == 2
        assert calls.count(("ls-files", "--stage", "-z", "--")) == 2
        assert receipt.authorization_authenticated is True
        assert receipt.authorization_key_sha256 == identity.execution_nonce_sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.local_commit_plan_sha256 == local_plan.sha256
        assert receipt.post_execution_evaluation_sha256 == evaluation.sha256
        assert receipt.execution_transaction_sha256 == execution_receipt.sha256
        assert receipt.tier_a_receipt_sha256 == execution_receipt.tier_a_receipt_sha256
        assert receipt.execution_nonce_sha256 == execution_receipt.execution_nonce_sha256
        assert receipt.development_task_sha256 == identity.development_task_sha256
        assert receipt.task_id == task.task_id
        assert receipt.repository == task.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.candidate_patch_sha256 == identity.candidate_patch_sha256
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.host_replay_guard_committed is True
        assert receipt.local_commit_object_identity_authenticated is True
        assert receipt.fresh_workspace_snapshot_matched is True
        assert receipt.fresh_index_manifest_matched is True
        assert receipt.exact_commit_identity_revalidated is True
        assert receipt.local_commit_write_authority_reserved is True
        assert receipt.one_shot_local_commit_write_required is True
        assert receipt.git_object_write_authorized is True
        assert receipt.local_ref_update_authorized is True
        assert receipt.local_commit_authorized is True
        assert receipt.local_commit_created is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = write_auth.PilotExactTaskLocalCommitWriteAuthorizationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.authorization_authenticated is False

        for field, value in (
            ("authorization_key_sha256", "a" * 64),
            ("git_object_write_authorized", False),
            ("local_ref_update_authorized", False),
            ("local_commit_authorized", False),
            ("local_commit_created", True),
            ("push_authorized", True),
            ("merge_authorized", True),
            ("production_activation_authorized", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    write_auth.PilotExactTaskLocalCommitWriteAuthorizationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        # The exact execution nonce owns one permanent local-write slot in this
        # ledger.  Even the same still-live identity cannot reserve it twice.
        replay_calls, replay_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=replay_reader):
            _reject(
                lambda: write_auth._authorize_verified_pilot_exact_task_local_commit_write(
                    local_commit_object_identity=identity,
                    ledger=ledger,
                    now_provider=lambda: "2026-09-15T06:00:12Z",
                )
            )
        assert replay_calls

        # Serialized ADR-DC-042 evidence is audit-only and must never recover
        # the live authority required to obtain a write slot.
        reloaded_identity = object_identity.PilotExactTaskLocalCommitObjectIdentity.from_mapping(
            identity.to_dict()
        )
        assert reloaded_identity.identity_authenticated is False
        _reject(
            lambda: write_auth._authorize_verified_pilot_exact_task_local_commit_write(
                local_commit_object_identity=reloaded_identity,
                ledger=ledger,
                now_provider=lambda: "2026-09-15T06:00:13Z",
            )
        )

        # Drift after the durable marker burns the slot fail-closed.  A clean
        # later retry must still collide with the marker instead of reusing it.
        drift_temp, drift_ledger = _ledger("rsi-exact-task-local-write-drift-")
        try:
            drift_calls, drift_reader = _identity_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
                drift_after_index=True,
            )
            drift_times = iter(("2026-09-15T06:00:20Z", "2026-09-15T06:00:21Z"))
            with patch.object(fixture["git_runner"], "run", side_effect=drift_reader):
                _reject(
                    lambda: write_auth._authorize_verified_pilot_exact_task_local_commit_write(
                        local_commit_object_identity=identity,
                        ledger=drift_ledger,
                        now_provider=lambda: next(drift_times),
                    )
                )
            assert drift_calls
            final, pending, lock = drift_ledger._paths(identity.execution_nonce_sha256)
            assert lock.exists()
            assert not final.exists()
            assert not pending.exists()

            stable_calls, stable_reader = _identity_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=stable_reader):
                _reject(
                    lambda: write_auth._authorize_verified_pilot_exact_task_local_commit_write(
                        local_commit_object_identity=identity,
                        ledger=drift_ledger,
                        now_provider=lambda: "2026-09-15T06:00:22Z",
                    )
                )
            assert stable_calls
        finally:
            drift_temp.cleanup()

        # Clock rollback after ADR-DC-042 fails before durable reservation.
        rollback_temp, rollback_ledger = _ledger("rsi-exact-task-local-write-clock-")
        try:
            rollback_calls, rollback_reader = _identity_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=rollback_reader):
                _reject(
                    lambda: write_auth._authorize_verified_pilot_exact_task_local_commit_write(
                        local_commit_object_identity=identity,
                        ledger=rollback_ledger,
                        now_provider=lambda: "2026-09-15T05:59:59Z",
                    )
                )
            _final, _pending, rollback_lock = rollback_ledger._paths(
                identity.execution_nonce_sha256
            )
            assert not rollback_lock.exists()
            assert rollback_calls
        finally:
            rollback_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["git_object_write_authorized"]["const"] is True
        assert props["local_ref_update_authorized"]["const"] is True
        assert props["local_commit_authorized"]["const"] is True
        assert props["local_commit_created"]["const"] is False
        assert props["remote_write_authorized"]["const"] is False
        assert props["push_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            write_auth.authorize_pilot_exact_task_local_commit_write
        ).parameters
        assert tuple(public_parameters) == ("local_commit_object_identity",)

        source = inspect.getsource(write_auth)
        assert "create_once_file" in source
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
        auth_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
