"""Adversarial contract for ADR-DC-047 verified publication requirements."""
from __future__ import annotations

import hashlib
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
    improvement_pilot_exact_task_local_commit_publication_requirements as publication,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_reservation as reservation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_transaction as transaction,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_object_identity as identity_boundary,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
)
from rsi_pilot_exact_task_local_commit_write_transaction_contract import (  # noqa: E402
    _live_reservation,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-publication-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        publication.PilotExactTaskLocalCommitPublicationRequirementsError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-047 unexpectedly accepted invalid authority")


def _completed_transaction_fixture():
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
    transaction_temp = TemporaryDirectory(prefix="rsi-local-write-transaction-047-source-")
    ledger = transaction._PilotExactTaskLocalCommitWriteTransactionLedger(
        Path(transaction_temp.name)
    )
    local_ref = transaction._local_ref_name(write_reservation.local_write_nonce_sha256)
    marker = ledger.acquire(reservation=write_reservation, local_ref=local_ref)
    source_receipt = transaction.PilotExactTaskLocalCommitWriteTransactionReceipt(
        transaction_ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=write_reservation.local_write_nonce_sha256,
        write_reservation_sha256=write_reservation.sha256,
        authorization_proof_sha256=write_reservation.authorization_proof_sha256,
        authorization_signature_sha256=write_reservation.authorization_signature_sha256,
        local_commit_object_identity_sha256=identity.sha256,
        execution_nonce_sha256=write_reservation.execution_nonce_sha256,
        local_write_nonce_sha256=write_reservation.local_write_nonce_sha256,
        base_sha=identity.base_sha,
        local_ref=local_ref,
        expected_old_ref_sha="0" * 40,
        index_manifest_sha256=identity.index_manifest_sha256,
        root_tree_sha=identity.root_tree_sha,
        commit_payload_sha256=identity.commit_payload_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        tree_object_count=1,
        prepared_at_utc="2026-09-15T06:14:10Z",
        object_write_completed_at_utc="2026-09-15T06:14:20Z",
        ref_updated_at_utc="2026-09-15T06:14:30Z",
        completed_at_utc="2026-09-15T06:14:40Z",
    )
    completed = ledger.commit(
        receipt=source_receipt,
        reservation=write_reservation,
        lock_payload=marker,
    )
    assert completed.transaction_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        write_reservation,
        completed,
    )


def _verification_reader(
    *,
    fixture,
    task,
    identity,
    staged: bytes,
    index_payload: bytes,
    transaction_receipt,
    missing_blob: bool = False,
):
    _base_calls, base_reader = _identity_reader(
        workspace=fixture["workspace"],
        base_sha=task.base_sha,
        staged=staged,
        index_payload=index_payload,
    )
    calls: list[tuple[str, ...]] = []
    entries = identity_boundary._parse_index_manifest(index_payload)
    tree_objects = transaction._tree_object_payloads(entries)
    tree_payloads = {sha: payload for sha, payload in tree_objects}
    expected_commit_payload = identity_boundary._commit_payload(
        tree_sha=identity.root_tree_sha,
        parent_sha=identity.base_sha,
        subject=identity.commit_subject,
        epoch_seconds=identity.commit_epoch_seconds,
    )
    object_types: dict[str, str] = {identity.base_sha: "commit"}
    for mode, object_sha, _path in entries:
        if mode != "160000":
            object_types[object_sha] = "blob"
    for sha, _payload in tree_objects:
        object_types[sha] = "tree"

    def run(args, *, cwd, stdin=None, **kwargs):
        args = tuple(args)
        calls.append(args)
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
        if args == (
            "rev-parse",
            "--verify",
            f"{transaction_receipt.local_ref}^{{commit}}",
        ):
            return (identity.predicted_commit_sha + "\n").encode("ascii")
        if args == ("cat-file", "commit", identity.predicted_commit_sha):
            return expected_commit_payload
        if len(args) == 3 and args[:2] == ("cat-file", "tree"):
            return tree_payloads[args[2]]
        if args == ("cat-file", "--batch-check=%(objectname) %(objecttype)"):
            assert isinstance(stdin, bytes)
            requested = stdin.decode("ascii").splitlines()
            output: list[str] = []
            for sha in requested:
                kind = object_types[sha]
                if missing_blob and kind == "blob":
                    kind = "missing"
                output.append(f"{sha} {kind}")
            return ("\n".join(output) + "\n").encode("ascii")
        raise AssertionError(f"ADR-DC-047 attempted unexpected Git command: {args!r}")

    return calls, run


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
        transaction_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        write_reservation,
        completed,
    ) = _completed_transaction_fixture()
    try:
        calls, reader = _verification_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            transaction_receipt=completed,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=reader), patch.object(
            publication,
            "_now_utc_seconds",
            return_value="2026-09-15T06:15:00Z",
        ):
            requirements = publication.materialize_pilot_exact_task_local_commit_publication_requirements(
                completed
            )

        assert requirements.local_commit_write_transaction_sha256 == completed.sha256
        assert requirements.write_reservation_sha256 == write_reservation.sha256
        assert requirements.authorization_proof_sha256 == completed.authorization_proof_sha256
        assert (
            requirements.authorization_signature_sha256
            == completed.authorization_signature_sha256
        )
        assert requirements.local_commit_object_identity_sha256 == identity.sha256
        assert requirements.execution_nonce_sha256 == identity.execution_nonce_sha256
        assert requirements.local_write_nonce_sha256 == completed.local_write_nonce_sha256
        assert requirements.repository == "Ternedal/ModelRig"
        assert requirements.base_sha == identity.base_sha
        assert requirements.local_ref == completed.local_ref
        assert requirements.index_manifest_sha256 == identity.index_manifest_sha256
        assert requirements.root_tree_sha == identity.root_tree_sha
        assert requirements.commit_payload_sha256 == identity.commit_payload_sha256
        assert requirements.predicted_commit_sha == identity.predicted_commit_sha
        assert requirements.verified_tree_object_count == 1
        assert requirements.verified_required_object_count == 3
        assert requirements.gitlink_entry_count == 0
        assert requirements.verified_at_utc == "2026-09-15T06:15:00Z"
        assert requirements.verification_authenticated is True

        for name in (
            "local_commit_mechanically_verified",
            "local_ref_verified",
            "commit_object_bytes_verified",
            "tree_object_bytes_verified",
            "required_superproject_objects_verified",
            "workspace_and_index_revalidated",
            "head_remains_frozen_base",
            "publication_requirements_materialized",
            "separate_human_remote_publication_authorization_required",
            "remote_target_host_pinned_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
            "superproject_gitlink_target_presence_not_required",
        ):
            assert getattr(requirements, name) is True

        for name in (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(requirements, name) is False

        assert (
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
        ) in calls
        assert not any(
            call and call[0] in {"push", "update-ref", "checkout", "reset", "clean"}
            for call in calls
        )

        reloaded = publication.PilotExactTaskLocalCommitPublicationRequirements.from_mapping(
            requirements.to_dict()
        )
        assert reloaded == requirements
        assert reloaded.sha256 == requirements.sha256
        assert reloaded.verification_authenticated is False

        reloaded_transaction = transaction.PilotExactTaskLocalCommitWriteTransactionReceipt.from_mapping(
            completed.to_dict()
        )
        assert reloaded_transaction.transaction_authenticated is False
        _reject(lambda: publication._require_live_transaction(reloaded_transaction))

        # A missing required superproject blob must block publication planning.
        _missing_calls, missing_reader = _verification_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            transaction_receipt=completed,
            missing_blob=True,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=missing_reader):
            _reject(
                lambda: publication.materialize_pilot_exact_task_local_commit_publication_requirements(
                    completed
                )
            )

        for field in (
            "local_commit_mechanically_verified",
            "local_ref_verified",
            "commit_object_bytes_verified",
            "tree_object_bytes_verified",
            "required_superproject_objects_verified",
            "workspace_and_index_revalidated",
            "head_remains_frozen_base",
            "publication_requirements_materialized",
            "separate_human_remote_publication_authorization_required",
            "remote_target_host_pinned_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
            "superproject_gitlink_target_presence_not_required",
        ):
            _reject(
                lambda field=field: publication.PilotExactTaskLocalCommitPublicationRequirements.from_mapping(
                    {**requirements.to_dict(), field: False}
                )
            )
        for field in (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: publication.PilotExactTaskLocalCommitPublicationRequirements.from_mapping(
                    {**requirements.to_dict(), field: True}
                )
            )
        _reject(
            lambda: publication.PilotExactTaskLocalCommitPublicationRequirements.from_mapping(
                {**requirements.to_dict(), "local_ref": "refs/heads/main"}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(requirements.to_dict())
        assert set(schema["required"]) == set(requirements.to_dict())
        assert props["publication_requirements_materialized"]["const"] is True
        assert props["separate_human_remote_publication_authorization_required"]["const"] is True
        assert props["no_force_push_required"]["const"] is True
        assert props["remote_write_authorized"]["const"] is False
        assert props["push_authorized"]["const"] is False
        assert props["pr_mutation_authorized"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            publication.materialize_pilot_exact_task_local_commit_publication_requirements
        ).parameters
        assert tuple(public_parameters) == ("local_commit_write_transaction",)

        source = inspect.getsource(publication)
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert '("push",' not in source
        assert '("update-ref",' not in source
        assert '("checkout",' not in source
        assert '("reset",' not in source
        assert '("clean",' not in source
        assert "create_pull_request" not in source
        assert "merge_pull_request" not in source
    finally:
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
