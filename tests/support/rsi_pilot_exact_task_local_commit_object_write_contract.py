"""Adversarial contract for ADR-DC-047 exact local Git object materialization."""
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

from kaliv_dev_control import improvement_pilot_exact_task_local_commit_object_identity as identity_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_local_commit_object_write as object_write  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_local_commit_write_consumption as consumption  # noqa: E402
from rsi_pilot_exact_task_local_commit_object_identity_contract import _identity_reader  # noqa: E402
from rsi_pilot_exact_task_local_commit_write_consumption_contract import _live_admission  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-local-commit-object-write-receipt-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-047 unexpectedly accepted invalid authority")


def _live_consumption():
    source_temp, admission_ledger_temp, capability_temp, reservation_temp, execution_temp, local_admission_temp, admitted, identity, task, fixture, staged, index_payload = _live_admission()
    consume_temp = tempfile.TemporaryDirectory(prefix="rsi-local-commit-write-consumption-for-object-write-")
    ledger = consumption._PilotExactTaskLocalCommitWriteConsumptionLedger(Path(consume_temp.name).resolve())
    _calls, reader = _identity_reader(workspace=fixture["workspace"], base_sha=task.base_sha, staged=staged, index_payload=index_payload)
    times = iter(("2026-09-15T05:34:04Z", "2026-09-15T05:34:05Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        receipt = consumption._consume_verified_pilot_exact_task_local_commit_authorization(
            admission_receipt=admitted,
            ledger=ledger,
            now_provider=lambda: next(times),
        )
    assert receipt.consumption_authenticated is True
    return source_temp, admission_ledger_temp, capability_temp, reservation_temp, execution_temp, local_admission_temp, consume_temp, receipt, identity, task, fixture, staged, index_payload


def _object_writer_reader(*, workspace: Path, base_sha: str, staged: bytes, index_payload: bytes, identity):
    read_calls, read = _identity_reader(workspace=workspace, base_sha=base_sha, staged=staged, index_payload=index_payload)
    entries = identity_boundary._parse_index_manifest(index_payload)
    tree_plan = object_write._tree_object_plan(entries)
    commit_payload = identity_boundary._commit_payload(tree_sha=identity.root_tree_sha, parent_sha=identity.base_sha, subject=identity.commit_subject, epoch_seconds=identity.commit_epoch_seconds)
    expected_tree = {payload: sha for sha, payload in tree_plan}
    write_calls: list[tuple[str, ...]] = []
    def run(args, *, cwd, stdin=None, **kwargs):
        args = tuple(args)
        if args == ("hash-object", "-t", "tree", "-w", "--stdin"):
            write_calls.append(args)
            assert isinstance(stdin, bytes)
            expected = expected_tree.get(stdin)
            if expected is None:
                raise AssertionError("ADR-DC-047 attempted an unplanned tree object")
            return (expected + "\n").encode("ascii")
        if args == ("hash-object", "-t", "commit", "-w", "--stdin"):
            write_calls.append(args)
            assert stdin == commit_payload
            return (identity.predicted_commit_sha + "\n").encode("ascii")
        return read(args, cwd=cwd, stdin=stdin, **kwargs)
    return read_calls, write_calls, tree_plan, run


def run_contract() -> None:
    if os.name == "nt":
        return
    source_temp, admission_ledger_temp, capability_temp, reservation_temp, execution_temp, local_admission_temp, consume_temp, consumed, identity, task, fixture, staged, index_payload = _live_consumption()
    object_ledger_temp = tempfile.TemporaryDirectory(prefix="rsi-local-commit-object-write-")
    try:
        ledger = object_write._PilotExactTaskLocalCommitObjectWriteLedger(Path(object_ledger_temp.name).resolve())
        read_calls, write_calls, tree_plan, reader = _object_writer_reader(
            workspace=fixture["workspace"], base_sha=task.base_sha, staged=staged,
            index_payload=index_payload, identity=identity,
        )
        times = iter(("2026-09-15T05:34:06Z", "2026-09-15T05:34:07Z", "2026-09-15T05:34:08Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            receipt = object_write._materialize_verified_pilot_exact_task_local_commit_objects(
                write_consumption_receipt=consumed,
                ledger=ledger,
                now_provider=lambda: next(times),
            )
        assert len(read_calls) == 21
        assert write_calls.count(("hash-object", "-t", "tree", "-w", "--stdin")) == len(tree_plan)
        assert write_calls.count(("hash-object", "-t", "commit", "-w", "--stdin")) == 1
        assert receipt.object_write_authenticated is True
        assert receipt.write_key_sha256 == consumed.local_commit_nonce_sha256
        assert receipt.write_consumption_receipt_sha256 == consumed.sha256
        assert receipt.admission_receipt_sha256 == consumed.admission_receipt_sha256
        assert receipt.authorization_proof_sha256 == consumed.authorization_proof_sha256
        assert receipt.authorization_sha256 == consumed.authorization_sha256
        assert receipt.authorization_signature_sha256 == consumed.authorization_signature_sha256
        assert receipt.authorization_requirements_sha256 == consumed.authorization_requirements_sha256
        assert receipt.requirements_key_sha256 == consumed.requirements_key_sha256
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.local_commit_plan_sha256 == identity.local_commit_plan_sha256
        assert receipt.development_task_sha256 == identity.development_task_sha256
        assert receipt.task_id == identity.task_id
        assert receipt.repository == identity.repository
        assert receipt.base_sha == identity.base_sha
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.index_entry_count == identity.index_entry_count
        assert receipt.commit_subject_sha256 == identity.commit_subject_sha256
        assert receipt.local_commit_nonce_sha256 == consumed.local_commit_nonce_sha256
        assert receipt.consumed_at_utc == consumed.consumed_at_utc
        assert receipt.prepared_at_utc == "2026-09-15T05:34:06Z"
        assert receipt.write_started_at_utc == "2026-09-15T05:34:07Z"
        assert receipt.write_completed_at_utc == "2026-09-15T05:34:08Z"
        assert receipt.tree_object_count == len(tree_plan)
        assert receipt.tree_object_shas == tuple(sha for sha, _ in tree_plan)
        assert receipt.tree_object_shas[-1] == identity.root_tree_sha
        assert receipt.commit_object_sha == identity.predicted_commit_sha
        assert receipt.host_object_write_guard_committed is True
        assert receipt.consumption_authenticated_at_write is True
        assert receipt.local_commit_authorization_consumed is True
        assert receipt.write_boundary_ready is True
        assert receipt.exact_object_identity_revalidated is True
        assert receipt.fresh_workspace_snapshot_matched is True
        assert receipt.exact_git_object_write_transaction_executed is True
        assert receipt.tree_objects_materialized is True
        assert receipt.commit_object_materialized is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.local_commit_created is False
        assert receipt.push_authorized is False
        assert receipt.production_activation_authorized is False

        reloaded = object_write.PilotExactTaskLocalCommitObjectWriteReceipt.from_mapping(receipt.to_dict())
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.object_write_authenticated is False

        replay_reads, replay_writes, _replay_plan, replay_reader = _object_writer_reader(
            workspace=fixture["workspace"], base_sha=task.base_sha, staged=staged,
            index_payload=index_payload, identity=identity,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=replay_reader):
            _reject(lambda: object_write._materialize_verified_pilot_exact_task_local_commit_objects(
                write_consumption_receipt=consumed, ledger=ledger,
                now_provider=lambda: "2026-09-15T05:34:09Z",
            ))
        assert replay_reads
        assert replay_writes == []

        reloaded_consumption = consumption.PilotExactTaskLocalCommitWriteConsumptionReceipt.from_mapping(consumed.to_dict())
        assert reloaded_consumption.consumption_authenticated is False
        other_temp = tempfile.TemporaryDirectory(prefix="rsi-local-commit-object-write-reloaded-")
        try:
            _reject(lambda: object_write._materialize_verified_pilot_exact_task_local_commit_objects(
                write_consumption_receipt=reloaded_consumption,
                ledger=object_write._PilotExactTaskLocalCommitObjectWriteLedger(Path(other_temp.name).resolve()),
                now_provider=lambda: "2026-09-15T05:34:10Z",
            ))
        finally:
            other_temp.cleanup()

        for field, value in (
            ("host_object_write_guard_committed", False),
            ("consumption_authenticated_at_write", False),
            ("local_commit_authorization_consumed", False),
            ("exact_git_object_write_transaction_executed", False),
            ("tree_objects_materialized", False),
            ("commit_object_materialized", False),
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("local_commit_created", True),
            ("push_authorized", True),
            ("production_activation_authorized", True),
            ("predicted_commit_sha", "a" * 40),
            ("commit_object_sha", "b" * 40),
            ("write_key_sha256", "c" * 64),
        ):
            _reject(lambda field=field, value=value: object_write.PilotExactTaskLocalCommitObjectWriteReceipt.from_mapping({**receipt.to_dict(), field: value}))

        nested_entries = (("100644", "1" * 40, "a/one"), ("100644", "2" * 40, "root"))
        nested_plan = object_write._tree_object_plan(nested_entries)
        assert len(nested_plan) == 2
        assert nested_plan[-1][0] == identity_boundary._root_tree_sha(nested_entries)

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert schema["properties"]["exact_git_object_write_transaction_executed"]["const"] is True
        assert schema["properties"]["tree_objects_materialized"]["const"] is True
        assert schema["properties"]["commit_object_materialized"]["const"] is True
        assert schema["properties"]["git_object_write_authorized"]["const"] is False
        assert schema["properties"]["local_ref_update_authorized"]["const"] is False
        assert schema["properties"]["local_commit_authorized"]["const"] is False
        assert schema["properties"]["local_commit_created"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(object_write.materialize_pilot_exact_task_local_commit_objects).parameters
        assert tuple(public_parameters) == ("write_consumption_receipt",)
        impl_source = inspect.getsource(sys.modules["kaliv_dev_control._improvement_pilot_exact_task_local_commit_object_write_impl"])
        production_source = inspect.getsource(sys.modules["kaliv_dev_control._improvement_pilot_exact_task_local_commit_object_write_production_boundary"])
        assert '("hash-object", "-t", kind, "-w", "--stdin")' in impl_source
        assert '"write-tree"' not in impl_source
        assert '"commit-tree"' not in impl_source
        assert 'run(("commit",' not in impl_source
        assert '("update-ref",' not in impl_source
        assert '("push",' not in impl_source
        assert '("reset",' not in impl_source
        assert '("clean",' not in impl_source
        assert "subprocess" not in impl_source
        assert "shell=True" not in impl_source
        assert "git_runner" not in public_parameters
        assert "args" not in public_parameters
        assert "subprocess" not in production_source
    finally:
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
