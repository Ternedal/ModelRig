"""Adversarial contract for ADR-DC-043 exact local commit write requirements."""
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
    improvement_pilot_exact_task_local_commit_object_identity as object_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_write_requirements as write_requirements,
)
from rsi_pilot_exact_task_local_commit_object_identity_contract import (  # noqa: E402
    _identity_reader,
    _live_plan,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-local-commit-write-requirements-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-043 unexpectedly accepted invalid authority")


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
                    now_provider=lambda: "2026-09-15T06:10:00Z",
                )
            )
        assert identity.identity_authenticated is True
        live_inputs = object_identity._get_live_local_commit_object_identity_inputs(identity)
        assert live_inputs is not None
        admission_receipt = live_inputs["admission_receipt"]
        expected_actor_id = (
            admission_receipt.revalidation_attestation_proof.attestation.packet
            .execution_authorization_proof.authorization.execution_authorizer_actor_id
        )

        with patch.object(
            fixture["git_runner"],
            "run",
            side_effect=AssertionError("ADR-DC-043 must not invoke Git"),
        ):
            requirements = (
                write_requirements.materialize_pilot_exact_task_local_commit_write_requirements(
                    identity
                )
            )

        assert requirements.local_commit_object_identity_sha256 == identity.sha256
        assert requirements.local_commit_plan_sha256 == identity.local_commit_plan_sha256
        assert (
            requirements.post_execution_evaluation_sha256
            == identity.post_execution_evaluation_sha256
        )
        assert requirements.execution_transaction_sha256 == identity.execution_transaction_sha256
        assert requirements.tier_a_receipt_sha256 == identity.tier_a_receipt_sha256
        assert requirements.execution_nonce_sha256 == identity.execution_nonce_sha256
        assert requirements.execution_authorizer_actor_id == expected_actor_id
        assert requirements.development_task_sha256 == identity.development_task_sha256
        assert requirements.task_id == identity.task_id
        assert requirements.repository == identity.repository
        assert requirements.base_sha == identity.base_sha
        assert requirements.candidate_patch_sha256 == identity.candidate_patch_sha256
        assert requirements.candidate_numstat_sha256 == identity.candidate_numstat_sha256
        assert requirements.scope_policy_sha256 == identity.scope_policy_sha256
        assert requirements.index_manifest_sha256 == identity.index_manifest_sha256
        assert requirements.root_tree_sha == identity.root_tree_sha
        assert requirements.commit_payload_sha256 == identity.commit_payload_sha256
        assert requirements.predicted_commit_sha == identity.predicted_commit_sha
        assert requirements.commit_subject_sha256 == identity.commit_subject_sha256
        assert requirements.commit_message_policy == identity.commit_message_policy
        assert requirements.materialized_at_utc == identity.materialized_at_utc

        for name in (
            "local_commit_write_requirements_materialized",
            "exact_live_identity_required",
            "fresh_identity_revalidation_required",
            "fresh_workspace_snapshot_required",
            "exact_index_manifest_revalidation_required",
            "exact_root_tree_revalidation_required",
            "exact_commit_payload_revalidation_required",
            "separate_human_local_commit_authorization_required",
            "human_local_commit_authorizer_continuity_required",
            "one_shot_local_write_nonce_required",
            "local_write_nonce_distinct_from_execution_nonce_required",
            "canonical_local_write_ledger_required",
            "durable_prewrite_reservation_required",
            "reservation_before_git_object_write_required",
            "uncertain_write_reservation_fails_closed",
            "git_object_write_via_trusted_git_only_required",
            "exact_predicted_commit_sha_required",
            "local_ref_target_host_pinned_required",
            "atomic_compare_and_swap_ref_update_required",
            "ref_update_after_commit_object_verification_required",
            "post_write_commit_object_verification_required",
            "post_write_ref_verification_required",
            "remote_write_forbidden",
        ):
            assert getattr(requirements, name) is True

        for name in (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
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
            assert getattr(requirements, name) is False

        reloaded = (
            write_requirements.PilotExactTaskLocalCommitWriteRequirements.from_mapping(
                requirements.to_dict()
            )
        )
        assert reloaded == requirements
        assert reloaded.sha256 == requirements.sha256

        reloaded_identity = (
            object_identity.PilotExactTaskLocalCommitObjectIdentity.from_mapping(
                identity.to_dict()
            )
        )
        assert reloaded_identity.identity_authenticated is False
        _reject(
            lambda: write_requirements.materialize_pilot_exact_task_local_commit_write_requirements(
                reloaded_identity
            )
        )

        for field, value in (
            ("execution_authorizer_actor_id", "other.operator"),
            ("exact_live_identity_required", False),
            ("separate_human_local_commit_authorization_required", False),
            ("human_local_commit_authorizer_continuity_required", False),
            ("reservation_before_git_object_write_required", False),
            ("remote_write_forbidden", False),
            ("git_object_write_authorized", True),
            ("local_ref_update_authorized", True),
            ("local_commit_authorized", True),
            ("local_commit_created", True),
            ("push_authorized", True),
            ("production_activation_authorized", True),
            ("authority", "caller-selected-authority"),
        ):
            _reject(
                lambda field=field, value=value: (
                    write_requirements.PilotExactTaskLocalCommitWriteRequirements.from_mapping(
                        {**requirements.to_dict(), field: value}
                    )
                )
            ) if field != "execution_authorizer_actor_id" else None

        tampered_actor = write_requirements.PilotExactTaskLocalCommitWriteRequirements.from_mapping(
            {**requirements.to_dict(), "execution_authorizer_actor_id": "other.operator"}
        )
        assert tampered_actor.execution_authorizer_actor_id != requirements.execution_authorizer_actor_id
        assert tampered_actor.sha256 != requirements.sha256

        _reject(
            lambda: write_requirements.PilotExactTaskLocalCommitWriteRequirements.from_mapping(
                {**requirements.to_dict(), "execution_authorizer_actor_id": " invalid "}
            )
        )
        _reject(
            lambda: write_requirements.PilotExactTaskLocalCommitWriteRequirements.from_mapping(
                {**requirements.to_dict(), "unexpected": True}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(requirements.to_dict())
        assert set(schema["required"]) == set(requirements.to_dict())
        assert "execution_authorizer_actor_id" in props
        assert props["local_commit_write_requirements_materialized"]["const"] is True
        assert props["separate_human_local_commit_authorization_required"]["const"] is True
        assert props["human_local_commit_authorizer_continuity_required"]["const"] is True
        assert props["reservation_before_git_object_write_required"]["const"] is True
        assert props["git_object_write_authorized"]["const"] is False
        assert props["local_ref_update_authorized"]["const"] is False
        assert props["local_commit_authorized"]["const"] is False
        assert props["local_commit_created"]["const"] is False
        assert props["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            write_requirements.materialize_pilot_exact_task_local_commit_write_requirements
        ).parameters
        assert tuple(public_parameters) == ("local_commit_object_identity",)

        source = inspect.getsource(write_requirements)
        assert "execution_authorizer_actor_id" in source
        assert "subprocess" not in source
        assert "shell=True" not in source
        assert ".run(" not in source
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
