"""Adversarial contract for ADR-DC-048 exact local branch ref update."""
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

from kaliv_dev_control import improvement_pilot_exact_task_local_commit_object_write as object_write  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_local_commit_ref_update as ref_update  # noqa: E402
from rsi_pilot_exact_task_local_commit_object_identity_contract import _identity_reader  # noqa: E402
from rsi_pilot_exact_task_local_commit_object_write_contract import (  # noqa: E402
    _live_consumption,
    _object_writer_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-ref-update-receipt-v1.schema.json"
)
TARGET_REF = "refs/heads/rsi-pilot-local-commit"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-048 unexpectedly accepted invalid authority")


def _live_object_write():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
        consumed,
        identity,
        task,
        fixture,
        staged,
        index_payload,
    ) = _live_consumption()
    object_ledger_temp = tempfile.TemporaryDirectory(
        prefix="rsi-local-commit-object-write-for-ref-update-"
    )
    ledger = object_write._PilotExactTaskLocalCommitObjectWriteLedger(
        Path(object_ledger_temp.name).resolve()
    )
    _read_calls, _write_calls, _tree_plan, reader = _object_writer_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
        identity=identity,
    )
    times = iter(
        (
            "2026-09-15T05:34:06Z",
            "2026-09-15T05:34:07Z",
            "2026-09-15T05:34:08Z",
        )
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        receipt = object_write._materialize_verified_pilot_exact_task_local_commit_objects(
            write_consumption_receipt=consumed,
            ledger=ledger,
            now_provider=lambda: next(times),
        )
    assert receipt.object_write_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
        object_ledger_temp,
        receipt,
        identity,
        task,
        fixture,
        staged,
        index_payload,
    )


def _ref_update_reader(
    *,
    workspace: Path,
    base_sha: str,
    staged: bytes,
    index_payload: bytes,
    predicted_commit_sha: str,
    root_tree_sha: str,
    detached: bool = False,
):
    _read_calls, pre_reader = _identity_reader(
        workspace=workspace,
        base_sha=base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    updated = False
    calls: list[tuple[str, ...]] = []
    update_calls: list[tuple[str, ...]] = []

    def run(args, *, cwd, stdin=None, **kwargs):
        nonlocal updated
        args = tuple(args)
        calls.append(args)
        assert Path(cwd) == workspace

        if args == ("symbolic-ref", "-q", "HEAD"):
            if detached:
                raise ValueError("detached HEAD")
            return (TARGET_REF + "\n").encode("utf-8")
        if args == ("check-ref-format", TARGET_REF):
            return b""
        if args == ("rev-parse", "--verify", TARGET_REF):
            value = predicted_commit_sha if updated else base_sha
            return (value + "\n").encode("ascii")
        if args == ("cat-file", "-t", predicted_commit_sha):
            return b"commit\n"
        if args == ("cat-file", "-t", root_tree_sha):
            return b"tree\n"
        if args == (
            "update-ref",
            TARGET_REF,
            predicted_commit_sha,
            base_sha,
        ):
            if updated:
                raise AssertionError("ADR-DC-048 attempted a second ref update")
            update_calls.append(args)
            updated = True
            return b""

        if updated:
            if args == ("rev-parse", "--show-toplevel"):
                return (os.fspath(workspace) + "\n").encode("utf-8")
            if args == ("rev-parse", "HEAD"):
                return (predicted_commit_sha + "\n").encode("ascii")
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
                return b""
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

        return pre_reader(args, cwd=cwd, stdin=stdin, **kwargs)

    return calls, update_calls, run


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        local_admission_temp,
        consume_temp,
        object_ledger_temp,
        object_receipt,
        identity,
        task,
        fixture,
        staged,
        index_payload,
    ) = _live_object_write()
    ref_ledger_temp = tempfile.TemporaryDirectory(
        prefix="rsi-local-commit-ref-update-"
    )
    try:
        ledger = ref_update._PilotExactTaskLocalCommitRefUpdateLedger(
            Path(ref_ledger_temp.name).resolve()
        )
        calls, update_calls, reader = _ref_update_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
            predicted_commit_sha=identity.predicted_commit_sha,
            root_tree_sha=identity.root_tree_sha,
        )
        times = iter(
            (
                "2026-09-15T05:34:09Z",
                "2026-09-15T05:34:10Z",
                "2026-09-15T05:34:11Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = ref_update._attach_verified_pilot_exact_task_local_commit(
                object_write_receipt=object_receipt,
                ledger=ledger,
                now_provider=lambda: next(times),
            )

        assert update_calls == [
            (
                "update-ref",
                TARGET_REF,
                identity.predicted_commit_sha,
                task.base_sha,
            )
        ]
        assert receipt.ref_update_authenticated is True
        assert receipt.ref_update_key_sha256 == object_receipt.local_commit_nonce_sha256
        assert receipt.object_write_receipt_sha256 == object_receipt.sha256
        assert (
            receipt.write_consumption_receipt_sha256
            == object_receipt.write_consumption_receipt_sha256
        )
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.task_id == identity.task_id
        assert receipt.repository == identity.repository
        assert receipt.base_sha == task.base_sha
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.target_ref == TARGET_REF
        assert receipt.expected_old_sha == task.base_sha
        assert receipt.new_commit_sha == identity.predicted_commit_sha
        assert receipt.pre_ref_update_workspace_snapshot_sha256 == (
            object_receipt.pre_write_workspace_snapshot_sha256
        )
        assert (
            receipt.post_ref_update_workspace_snapshot_sha256
            != receipt.pre_ref_update_workspace_snapshot_sha256
        )
        assert receipt.host_ref_update_guard_committed is True
        assert receipt.object_write_authenticated_at_ref_update is True
        assert receipt.exact_commit_object_verified is True
        assert receipt.current_local_branch_ref_verified is True
        assert receipt.compare_and_swap_ref_update_executed is True
        assert receipt.local_ref_updated is True
        assert receipt.local_commit_created is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = (
            ref_update.PilotExactTaskLocalCommitRefUpdateReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.ref_update_authenticated is False

        replay_temp = tempfile.TemporaryDirectory(
            prefix="rsi-local-commit-ref-update-replay-"
        )
        try:
            replay_calls, replay_updates, replay_reader = _ref_update_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
                predicted_commit_sha=identity.predicted_commit_sha,
                root_tree_sha=identity.root_tree_sha,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=replay_reader):
                _reject(
                    lambda: ref_update._attach_verified_pilot_exact_task_local_commit(
                        object_write_receipt=object_receipt,
                        ledger=ref_update._PilotExactTaskLocalCommitRefUpdateLedger(
                            Path(replay_temp.name).resolve()
                        ),
                        now_provider=lambda: "2026-09-15T05:34:12Z",
                    )
                )
            assert replay_calls
            assert replay_updates == []
        finally:
            replay_temp.cleanup()

        detached_temp = tempfile.TemporaryDirectory(
            prefix="rsi-local-commit-ref-update-detached-"
        )
        try:
            _detached_calls, detached_updates, detached_reader = _ref_update_reader(
                workspace=fixture["workspace"],
                base_sha=task.base_sha,
                staged=staged,
                index_payload=index_payload,
                predicted_commit_sha=identity.predicted_commit_sha,
                root_tree_sha=identity.root_tree_sha,
                detached=True,
            )
            with patch.object(fixture["git_runner"], "run", side_effect=detached_reader):
                _reject(
                    lambda: ref_update._attach_verified_pilot_exact_task_local_commit(
                        object_write_receipt=object_receipt,
                        ledger=ref_update._PilotExactTaskLocalCommitRefUpdateLedger(
                            Path(detached_temp.name).resolve()
                        ),
                        now_provider=lambda: "2026-09-15T05:34:12Z",
                    )
                )
            assert detached_updates == []
        finally:
            detached_temp.cleanup()

        for field, value in (
            ("host_ref_update_guard_committed", False),
            ("object_write_authenticated_at_ref_update", False),
            ("exact_commit_object_verified", False),
            ("current_local_branch_ref_verified", False),
            ("compare_and_swap_ref_update_executed", False),
            ("local_ref_updated", False),
            ("local_commit_created", False),
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("push_authorized", True),
            ("production_activation_authorized", True),
            ("target_ref", "refs/tags/not-a-local-branch"),
            ("expected_old_sha", "a" * 40),
            ("new_commit_sha", "b" * 40),
            ("pre_ref_update_workspace_snapshot_sha256", "d" * 64),
            ("post_ref_update_workspace_snapshot_sha256", receipt.pre_ref_update_workspace_snapshot_sha256),
            ("ref_update_key_sha256", "c" * 64),
        ):
            _reject(
                lambda field=field, value=value: (
                    ref_update.PilotExactTaskLocalCommitRefUpdateReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["compare_and_swap_ref_update_executed"]["const"] is True
        assert schema["properties"]["local_ref_updated"]["const"] is True
        assert schema["properties"]["local_commit_created"]["const"] is True
        assert schema["properties"]["git_object_write_authorized"]["const"] is False
        assert schema["properties"]["local_ref_update_authorized"]["const"] is False
        assert schema["properties"]["local_commit_authorized"]["const"] is False
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            ref_update.attach_pilot_exact_task_local_commit
        ).parameters
        assert tuple(public_parameters) == ("object_write_receipt",)

        impl_source = inspect.getsource(
            sys.modules[
                "kaliv_dev_control._improvement_pilot_exact_task_local_commit_ref_update_impl"
            ]
        )
        production_source = inspect.getsource(
            sys.modules[
                "kaliv_dev_control._improvement_pilot_exact_task_local_commit_ref_update_production_boundary"
            ]
        )
        assert '"update-ref",' in impl_source
        assert '("symbolic-ref", "-q", "HEAD")' in impl_source
        assert '("check-ref-format", target_ref)' in impl_source
        assert '("push",' not in impl_source
        assert '("reset",' not in impl_source
        assert '("clean",' not in impl_source
        assert "subprocess" not in impl_source
        assert "shell=True" not in impl_source
        assert "git_runner" not in public_parameters
        assert "target_ref" not in public_parameters
        assert "args" not in public_parameters
        assert "subprocess" not in production_source
    finally:
        ref_ledger_temp.cleanup()
        object_ledger_temp.cleanup()
        consume_temp.cleanup()
        local_admission_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
