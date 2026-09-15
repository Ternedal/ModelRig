"""Adversarial contract for ADR-DC-046 exact local Git write transaction."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_reservation as reservation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_transaction as transaction,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _git_sha1,
    _identity_reader,
)
from rsi_pilot_exact_task_local_commit_write_reservation_contract import (  # noqa: E402
    _authorized_material,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-write-transaction-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        transaction.PilotExactTaskLocalCommitWriteTransactionError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-046 unexpectedly accepted invalid authority")


def _live_reservation():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        identity,
        _requirements,
        task,
        fixture,
        staged,
        index_payload,
        _claim,
        _verifier,
        _signature,
        _proof,
        fresh,
    ) = _authorized_material()
    ledger_temp = TemporaryDirectory(prefix="rsi-local-write-reservation-046-source-")
    ledger = reservation._PilotExactTaskLocalCommitWriteReservationLedger(
        Path(ledger_temp.name)
    )
    _calls, reader = _identity_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    times = iter(("2026-09-15T06:13:00Z", "2026-09-15T06:14:00Z"))
    with patch.object(fixture["git_runner"], "run", side_effect=reader):
        write_reservation = reservation._reserve_verified_exact_task_local_commit_write(
            authorization_proof=fresh,
            local_commit_object_identity=identity,
            ledger=ledger,
            now_provider=lambda: next(times),
        )
    assert write_reservation.reservation_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        ledger_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        write_reservation,
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
        source_reservation_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        write_reservation,
    ) = _live_reservation()
    transaction_temp = TemporaryDirectory(prefix="rsi-local-write-transaction-046-")
    replay_temp = TemporaryDirectory(prefix="rsi-local-write-transaction-replay-046-")
    try:
        ledger = transaction._PilotExactTaskLocalCommitWriteTransactionLedger(
            Path(transaction_temp.name)
        )
        local_ref = transaction._local_ref_name(write_reservation.local_write_nonce_sha256)

        _base_calls, base_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )
        calls: list[tuple[str, ...]] = []
        objects: dict[str, tuple[str, bytes]] = {}
        refs: dict[str, str] = {}

        def writer(args, *, cwd, stdin=None, **kwargs):
            args = tuple(args)
            calls.append(args)
            assert Path(cwd) == fixture["workspace"]
            if args in {
                ("rev-parse", "--show-toplevel"),
                ("rev-parse", "HEAD"),
                (
                    "diff",
                    "--cached",
                    "--binary",
                    "--full-index",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--",
                ),
                (
                    "diff",
                    "--binary",
                    "--full-index",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--",
                ),
                ("ls-files", "--others", "--exclude-standard", "-z"),
                ("rev-parse", "--show-object-format"),
                ("ls-files", "--stage", "-z", "--"),
            }:
                return base_reader(args, cwd=cwd, stdin=stdin, **kwargs)
            if args == ("check-ref-format", local_ref):
                return b""
            if args == (
                "for-each-ref",
                "--format=%(objectname)",
                "--count=1",
                local_ref,
            ):
                target = refs.get(local_ref)
                return b"" if target is None else (target + "\n").encode("ascii")
            if args == ("hash-object", "-t", "tree", "-w", "--stdin"):
                assert isinstance(stdin, bytes)
                sha = _git_sha1("tree", stdin)
                objects[sha] = ("tree", stdin)
                return (sha + "\n").encode("ascii")
            if args == ("hash-object", "-t", "commit", "-w", "--stdin"):
                assert isinstance(stdin, bytes)
                sha = _git_sha1("commit", stdin)
                objects[sha] = ("commit", stdin)
                return (sha + "\n").encode("ascii")
            if len(args) == 3 and args[:2] == ("cat-file", "tree"):
                kind, payload = objects[args[2]]
                assert kind == "tree"
                return payload
            if len(args) == 3 and args[:2] == ("cat-file", "commit"):
                kind, payload = objects[args[2]]
                assert kind == "commit"
                return payload
            if args == (
                "update-ref",
                local_ref,
                identity.predicted_commit_sha,
                "0" * 40,
            ):
                assert local_ref not in refs
                refs[local_ref] = identity.predicted_commit_sha
                return b""
            if args == (
                "rev-parse",
                "--verify",
                f"{local_ref}^{{commit}}",
            ):
                return (refs[local_ref] + "\n").encode("ascii")
            raise AssertionError(f"ADR-DC-046 attempted unexpected Git command: {args!r}")

        times = iter(
            (
                "2026-09-15T06:14:10Z",
                "2026-09-15T06:14:20Z",
                "2026-09-15T06:14:30Z",
                "2026-09-15T06:14:40Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=writer):
            receipt = transaction._execute_verified_exact_task_local_commit_write(
                write_reservation=write_reservation,
                ledger=ledger,
                now_provider=lambda: next(times),
            )

        assert receipt.transaction_key_sha256 == write_reservation.local_write_nonce_sha256
        assert receipt.write_reservation_sha256 == write_reservation.sha256
        assert (
            receipt.authorization_proof_sha256
            == write_reservation.authorization_proof_sha256
        )
        assert (
            receipt.authorization_signature_sha256
            == write_reservation.authorization_signature_sha256
        )
        assert receipt.local_commit_object_identity_sha256 == identity.sha256
        assert receipt.execution_nonce_sha256 == identity.execution_nonce_sha256
        assert receipt.local_write_nonce_sha256 == write_reservation.local_write_nonce_sha256
        assert receipt.base_sha == identity.base_sha
        assert receipt.local_ref == local_ref
        assert receipt.expected_old_ref_sha == "0" * 40
        assert receipt.index_manifest_sha256 == identity.index_manifest_sha256
        assert receipt.root_tree_sha == identity.root_tree_sha
        assert receipt.commit_payload_sha256 == identity.commit_payload_sha256
        assert receipt.predicted_commit_sha == identity.predicted_commit_sha
        assert receipt.tree_object_count == 1
        assert refs[local_ref] == identity.predicted_commit_sha
        assert receipt.local_commit_created is True
        assert receipt.git_object_write_performed is True
        assert receipt.local_ref_update_performed is True
        assert receipt.local_commit_write_completed is True
        assert receipt.write_reservation_consumed is True
        assert receipt.git_object_write_authorized is False
        assert receipt.local_ref_update_authorized is False
        assert receipt.local_commit_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.transaction_authenticated is True
        assert (
            "update-ref",
            local_ref,
            identity.predicted_commit_sha,
            "0" * 40,
        ) in calls
        assert ("hash-object", "-t", "tree", "-w", "--stdin") in calls
        assert ("hash-object", "-t", "commit", "-w", "--stdin") in calls
        assert not any(
            call and call[0] in {"push", "checkout", "reset", "clean"}
            for call in calls
        )

        reloaded = transaction.PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.sha256 == receipt.sha256
        assert reloaded.transaction_authenticated is False

        reloaded_reservation = (
            reservation.PilotExactTaskLocalCommitWriteReservationReceipt.from_mapping(
                write_reservation.to_dict()
            )
        )
        assert reloaded_reservation.reservation_authenticated is False
        _reject(lambda: transaction._require_live_reservation(reloaded_reservation))

        replay_ledger = transaction._PilotExactTaskLocalCommitWriteTransactionLedger(
            Path(replay_temp.name)
        )
        _replay_base_calls, replay_base_reader = _identity_reader(
            workspace=fixture["workspace"],
            base_sha=task.base_sha,
            staged=staged,
            index_payload=index_payload,
        )

        def occupied_reader(args, *, cwd, stdin=None, **kwargs):
            args = tuple(args)
            if args in {
                ("rev-parse", "--show-toplevel"),
                ("rev-parse", "HEAD"),
                (
                    "diff",
                    "--cached",
                    "--binary",
                    "--full-index",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--",
                ),
                (
                    "diff",
                    "--binary",
                    "--full-index",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--",
                ),
                ("ls-files", "--others", "--exclude-standard", "-z"),
                ("rev-parse", "--show-object-format"),
                ("ls-files", "--stage", "-z", "--"),
            }:
                return replay_base_reader(args, cwd=cwd, stdin=stdin, **kwargs)
            if args == ("check-ref-format", local_ref):
                return b""
            if args == (
                "for-each-ref",
                "--format=%(objectname)",
                "--count=1",
                local_ref,
            ):
                return (identity.predicted_commit_sha + "\n").encode("ascii")
            raise AssertionError(f"unexpected replay Git command: {args!r}")

        with patch.object(fixture["git_runner"], "run", side_effect=occupied_reader):
            _reject(
                lambda: transaction._execute_verified_exact_task_local_commit_write(
                    write_reservation=write_reservation,
                    ledger=replay_ledger,
                    now_provider=lambda: "2026-09-15T06:14:50Z",
                )
            )
        replay_final, replay_pending, replay_lock = replay_ledger._paths(
            write_reservation.local_write_nonce_sha256
        )
        assert not replay_final.exists()
        assert not replay_pending.exists()
        assert not replay_lock.exists()

        _reject(
            lambda: transaction._reservation_window_allows_write(
                write_reservation,
                "2026-09-15T06:19:01Z",
            )
        )

        for field in (
            "host_transaction_guard_committed",
            "write_reservation_authenticated",
            "fresh_live_identity_revalidated",
            "exact_tree_objects_written",
            "exact_commit_object_written",
            "exact_commit_object_verified",
            "local_ref_create_only_cas_succeeded",
            "post_write_ref_verified",
            "post_write_workspace_revalidated",
            "write_reservation_consumed",
            "local_commit_write_completed",
            "git_object_write_performed",
            "local_ref_update_performed",
            "local_commit_created",
        ):
            _reject(
                lambda field=field: transaction.PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
                    {**receipt.to_dict(), field: False}
                )
            )

        for field in (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "integration_ready",
            "product_pilot_started",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: transaction.PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
                    {**receipt.to_dict(), field: True}
                )
            )

        wrong_ref = receipt.to_dict()
        wrong_ref["local_ref"] = "refs/heads/main"
        _reject(
            lambda: transaction.PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
                wrong_ref
            )
        )
        non_create_only = receipt.to_dict()
        non_create_only["expected_old_ref_sha"] = identity.base_sha
        _reject(
            lambda: transaction.PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
                non_create_only
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(receipt.to_dict())
        assert set(schema["required"]) == set(receipt.to_dict())
        assert props["local_commit_created"]["const"] is True
        assert props["git_object_write_performed"]["const"] is True
        assert props["local_ref_update_performed"]["const"] is True
        assert props["git_object_write_authorized"]["const"] is False
        assert props["local_ref_update_authorized"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            transaction.execute_pilot_exact_task_local_commit_write
        ).parameters
        assert tuple(public_parameters) == ("write_reservation",)

        source = inspect.getsource(transaction)
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '"write-tree"' not in source
        assert '"commit-tree"' not in source
        assert '("push",' not in source
        assert '("checkout",' not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
        assert '"symbolic-ref"' not in source
        assert '("update-ref",' in source
        assert '("hash-object", "-t", "tree", "-w", "--stdin")' in source
        assert '("hash-object", "-t", "commit", "-w", "--stdin")' in source
    finally:
        replay_temp.cleanup()
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
