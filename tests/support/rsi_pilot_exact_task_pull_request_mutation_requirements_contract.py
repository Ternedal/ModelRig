"""Adversarial contract for ADR-DC-054 exact pull-request mutation requirements."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pull_request_mutation_requirements as pr_requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_write_transaction as transaction  # noqa: E402
from rsi_pilot_exact_task_remote_publication_credential_capability_contract import (  # noqa: E402
    _broker_descriptor,
    _reservation_material,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pull-request-mutation-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        pr_requirements.PilotExactTaskPullRequestMutationRequirementsError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-054 unexpectedly accepted unsafe PR requirements")


def _completed_transaction():
    material, ledger_temp, reservation_receipt = _reservation_material()
    broker_temp = TemporaryDirectory(prefix="rsi-pr-requirements-054-broker-")
    descriptor, _policy_path, _broker_path, _policy = _broker_descriptor(broker_temp)
    credential_capability = capability._materialize_verified_pilot_exact_task_remote_publication_credential_capability(
        remote_write_reservation=reservation_receipt,
        broker_descriptor=descriptor,
        now_provider=lambda: "2026-09-15T06:21:45Z",
    )
    push_stdout = b"exact remote publication completed\n"
    push_stderr = b""
    result = transaction.PilotExactTaskRemotePublicationWriteTransaction(
        credential_capability_sha256=credential_capability.sha256,
        remote_write_reservation_sha256=reservation_receipt.sha256,
        prewrite_state_observation_sha256=(
            credential_capability.fresh_state_observation_sha256
        ),
        target_attestation_sha256=credential_capability.target_attestation_sha256,
        authorization_proof_sha256=credential_capability.authorization_proof_sha256,
        local_commit_publication_requirements_sha256=(
            credential_capability.local_commit_publication_requirements_sha256
        ),
        local_commit_write_transaction_sha256=(
            credential_capability.local_commit_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=(
            credential_capability.remote_publication_nonce_sha256
        ),
        predicted_commit_sha=credential_capability.predicted_commit_sha,
        canonical_remote_url=credential_capability.canonical_remote_url,
        destination_ref=credential_capability.destination_ref,
        expected_old_remote_sha=credential_capability.expected_old_remote_sha,
        broker_policy_sha256=credential_capability.broker_policy_sha256,
        broker_executable_path_sha256=(
            credential_capability.broker_executable_path_sha256
        ),
        broker_executable_sha256=credential_capability.broker_executable_sha256,
        push_stdout_sha256=hashlib.sha256(push_stdout).hexdigest(),
        push_stderr_sha256=hashlib.sha256(push_stderr).hexdigest(),
        push_total_output_bytes=len(push_stdout) + len(push_stderr),
        started_at_utc="2026-09-15T06:21:46Z",
        pushed_at_utc="2026-09-15T06:21:49Z",
        verified_at_utc="2026-09-15T06:21:50Z",
    )
    transaction._mark_remote_publication_write_transaction_authenticated(
        result,
        credential_capability,
    )
    assert result.transaction_authenticated is True
    return material, ledger_temp, broker_temp, reservation_receipt, credential_capability, result


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        material,
        ledger_temp,
        broker_temp,
        reservation_receipt,
        credential_capability,
        remote_transaction,
    ) = _completed_transaction()
    (
        source_temp,
        admission_ledger_temp,
        executor_capability_temp,
        local_reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        _identity,
        _task,
        _fixture,
        _staged,
        _index_payload,
        _completed,
        _requirements,
        _attestation,
    ) = material
    try:
        result = pr_requirements._materialize_verified_pilot_exact_task_pull_request_mutation_requirements(
            remote_publication_write_transaction=remote_transaction,
            now_provider=lambda: "2026-09-15T06:22:00Z",
        )

        assert result.remote_publication_write_transaction_sha256 == remote_transaction.sha256
        assert result.credential_capability_sha256 == credential_capability.sha256
        assert result.remote_write_reservation_sha256 == reservation_receipt.sha256
        assert result.target_attestation_sha256 == remote_transaction.target_attestation_sha256
        assert (
            result.remote_publication_authorization_proof_sha256
            == remote_transaction.authorization_proof_sha256
        )
        assert (
            result.local_commit_publication_requirements_sha256
            == remote_transaction.local_commit_publication_requirements_sha256
        )
        assert (
            result.local_commit_write_transaction_sha256
            == remote_transaction.local_commit_write_transaction_sha256
        )
        assert (
            result.remote_publication_nonce_sha256
            == remote_transaction.remote_publication_nonce_sha256
        )
        assert result.repository == "Ternedal/ModelRig"
        assert result.api_host == "api.github.com"
        assert result.canonical_remote_url == "https://github.com/Ternedal/ModelRig.git"
        assert result.base_ref == "main"
        assert result.head_ref == remote_transaction.destination_ref
        assert result.head_branch == remote_transaction.destination_ref.removeprefix(
            "refs/heads/"
        )
        assert result.predicted_commit_sha == remote_transaction.predicted_commit_sha
        assert (
            result.remote_publication_verified_at_utc
            == remote_transaction.verified_at_utc
        )
        assert result.materialized_at_utc == "2026-09-15T06:22:00Z"
        assert result.requirements_authenticated is True

        for field in (
            "remote_publication_transaction_authenticated",
            "remote_publication_completed",
            "remote_ref_verified",
            "pull_request_requirements_materialized",
            "draft_pull_request_required",
            "create_only_pull_request_required",
            "existing_open_pull_request_absent_required",
            "same_repository_head_required",
            "exact_base_ref_required",
            "exact_head_ref_required",
            "exact_head_sha_required",
            "separate_human_pr_mutation_authorization_required",
            "fresh_pull_request_state_observation_before_write_required",
            "one_shot_pr_mutation_reservation_required",
            "host_pinned_pr_credential_capability_required",
            "merge_separately_authorized_required",
        ):
            assert getattr(result, field) is True

        for field in (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_update_authorized",
            "ready_for_review_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        serialized = result.to_dict()
        reloaded = pr_requirements.PilotExactTaskPullRequestMutationRequirements.from_mapping(
            serialized
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.requirements_authenticated is False

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["draft_pull_request_required"]["const"] is True
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        reloaded_transaction = (
            transaction.PilotExactTaskRemotePublicationWriteTransaction.from_mapping(
                remote_transaction.to_dict()
            )
        )
        assert reloaded_transaction.transaction_authenticated is False
        _reject(
            lambda: pr_requirements._require_live_transaction(
                reloaded_transaction
            )
        )
        _reject(
            lambda: pr_requirements._materialize_verified_pilot_exact_task_pull_request_mutation_requirements(
                remote_publication_write_transaction=remote_transaction,
                now_provider=lambda: "2026-09-15T06:21:40Z",
            )
        )

        changed = dict(serialized)
        changed["base_ref"] = "release"
        _reject(
            lambda: pr_requirements.PilotExactTaskPullRequestMutationRequirements.from_mapping(
                changed
            )
        )
        changed = dict(serialized)
        changed["head_ref"] = "refs/heads/main"
        _reject(
            lambda: pr_requirements.PilotExactTaskPullRequestMutationRequirements.from_mapping(
                changed
            )
        )
        changed = dict(serialized)
        changed["pull_request_create_authorized"] = True
        _reject(
            lambda: pr_requirements.PilotExactTaskPullRequestMutationRequirements.from_mapping(
                changed
            )
        )

        public_parameters = inspect.signature(
            pr_requirements.materialize_pilot_exact_task_pull_request_mutation_requirements
        ).parameters
        assert tuple(public_parameters) == ("remote_publication_write_transaction",)

        source = inspect.getsource(pr_requirements)
        assert "requests." not in source
        assert "urllib." not in source
        assert "create_pull_request" not in source
        assert "update_pull_request" not in source
        assert "merge_pull_request" not in source
        assert "pull_request_create_authorized: bool = False" in source
        assert "merge_authorized: bool = False" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        broker_temp.cleanup()
        ledger_temp.cleanup()
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        local_reservation_temp.cleanup()
        executor_capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
