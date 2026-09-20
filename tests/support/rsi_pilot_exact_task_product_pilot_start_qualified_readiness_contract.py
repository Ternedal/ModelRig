"""Adversarial contract for ADR-DC-099 lineage-qualified product-pilot start readiness."""
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
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.asymmetric_authority import Ed25519AuthorityVerifier  # noqa: E402
from kaliv_dev_control import improvement_human_pilot_decision as human  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_post_production_activation_attestation as post  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_qualified_readiness as qualified  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_requirements as requirements  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_product_pilot_start_qualified_readiness_production_boundary as qualified_boundary  # noqa: E402
import rsi_human_pilot_decision_production_boundary as human_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-qualified-readiness-v1.schema.json"
)
IMPL = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_product_pilot_start_qualified_readiness_impl.py"
)
BOUNDARY = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_product_pilot_start_qualified_readiness_production_boundary.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-099 unexpectedly accepted unsafe readiness evidence")


def _fresh_go(lineage_receipt):
    completion = human_contract._completion_proof()
    private_key, key = human_contract._trusted_key(actor="product.pilot.owner")
    decision = human.build_human_pilot_decision(
        completion_proof=completion,
        decision_id="product-pilot-go-099",
        decision_maker_actor_id="product.pilot.owner",
        decision="go",
        operator_surface=lineage_receipt.operator_surface,
        allowed_task_ids=(lineage_receipt.selected_pilot_task_id,),
        workspace_root_path_sha256=lineage_receipt.workspace_root_path_sha256,
        local_commits_allowed=False,
        notes=(),
        decided_at_utc="2026-09-15T09:54:05Z",
    )
    signature = human_contract._sign(decision, private_key, key)
    verifier = Ed25519AuthorityVerifier(
        {key.key_id: key},
        minimum_keyring_epoch=1,
    )
    proof = human._verify_human_pilot_decision(
        completion_proof=completion,
        decision=decision,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T09:54:06Z",
    )
    assert proof.pilot_go_authorized is True
    assert proof.allowed_task_ids == (lineage_receipt.selected_pilot_task_id,)
    assert proof.local_commits_allowed is False
    return completion, proof, signature, verifier


def _evaluate(
    fresh,
    lineage_receipt,
    post_receipt,
    *,
    when="2026-09-15T09:54:20Z",
):
    return qualified._evaluate_verified_pilot_exact_task_product_pilot_start_qualified_readiness(
        fresh_human_go_proof=fresh,
        product_pilot_lineage_attestation=lineage_receipt,
        post_production_activation_attestation=post_receipt,
        now_provider=lambda: when,
    )


def _assert_inert(receipt) -> None:
    for field in (
        "production_activation",
        "production_activation_attested",
        "requirements_satisfied",
        "lineage_verified",
        "historical_human_go_lineage_verified",
        "fresh_human_product_pilot_go_verified",
        "explicit_pilot_scope_verified",
        "product_integration_selection_reverified",
        "runtime_preflight_reverified",
        "feature_flag_default_off_verified",
        "local_only_scope_verified",
        "manual_operator_invocation_required",
        "kill_switch_armed_required",
        "revoke_not_asserted_required",
        "restart_recovery_required",
        "network_writes_blocked_required",
        "credentials_absent_required",
        "unattended_cadence_forbidden",
        "general_shell_forbidden",
        "model_defined_commands_forbidden",
        "one_shot_start_authorization_required",
        "host_local_replay_guard_required",
        "start_receipt_required",
        "product_pilot_start_ready",
        "next_boundary_authorization_required",
    ):
        assert getattr(receipt, field) is True, field
    for field in (
        "product_pilot_start_authorized",
        "product_pilot_started",
        "task_execution_authorized",
        "local_commit_authorized",
        "promotion_gate_execution_authorized",
        "production_env_mutation_authorized",
        "appliance_restart_authorized",
        "production_receipt_write_authorized",
        "production_activation_authorized",
        "success_deployment_status_authorized",
        "deployment_status_mutation_authorized",
        "deployment_mutation_authorized",
        "deploy_authorized",
        "remote_write_authorized",
        "release_authorized",
        "tag_write_authorized",
        "release_mutation_authorized",
        "merge_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "review_submission_authorized",
        "review_thread_mutation_authorized",
        "nonce_reusable",
    ):
        assert getattr(receipt, field) is False, field


def run_contract() -> None:
    if os.name == "nt":
        return

    fixture = lineage_contract._build_fixture()
    try:
        lineage_receipt = lineage_contract._attest(fixture)
        post_receipt = fixture["post_production"]
        completion, fresh, signature, verifier = _fresh_go(lineage_receipt)

        with patch.object(
            qualified_boundary,
            "_canonical_human_pilot_decision_verifier",
            return_value=verifier,
        ):
            qualified_boundary._reverify_fresh_human_go(
                completion,
                fresh,
                signature,
            )

        receipt = _evaluate(
            fresh,
            lineage_receipt,
            post_receipt,
        )
        _assert_inert(receipt)
        assert receipt.readiness_authenticated is True
        assert (
            receipt.historical_human_go_proof_sha256
            == lineage_receipt.human_decision_proof_sha256
        )
        assert receipt.fresh_human_go_proof_sha256 == fresh.sha256
        assert receipt.fresh_human_go_signature_sha256 == signature.sha256
        assert (
            receipt.product_pilot_lineage_attestation_sha256
            == lineage_receipt.sha256
        )
        assert (
            receipt.post_production_activation_attestation_sha256
            == post_receipt.sha256
        )
        exact_requirements = (
            requirements.build_pilot_exact_task_product_pilot_start_requirements(
                post_receipt
            )
        )
        assert receipt.product_pilot_start_requirements_sha256 == exact_requirements.sha256
        assert (
            receipt.production_activation_candidate_sha256
            == lineage_receipt.production_activation_candidate_sha256
            == post_receipt.production_activation_candidate_sha256
        )
        assert receipt.execution_nonce_sha256 == lineage_receipt.execution_nonce_sha256
        assert receipt.operator_surface == lineage_receipt.operator_surface
        assert receipt.selected_pilot_task_id == lineage_receipt.selected_pilot_task_id
        assert (
            receipt.workspace_root_path_sha256
            == lineage_receipt.workspace_root_path_sha256
        )
        assert receipt.human_go_age_seconds == 14

        serialized = (
            qualified.PilotExactTaskProductPilotStartQualifiedReadinessReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.sha256 == receipt.sha256
        assert serialized.readiness_authenticated is False

        stale_post = post.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
            post_receipt.to_dict()
        )
        assert stale_post.attestation_authenticated is False
        _reject(
            lambda: _evaluate(
                fresh,
                lineage_receipt,
                stale_post,
            )
        )

        wrong_lineage_raw = lineage_receipt.to_dict()
        wrong_lineage_raw["production_activation_candidate_sha256"] = (
            "f" * 64
            if lineage_receipt.production_activation_candidate_sha256 != "f" * 64
            else "e" * 64
        )
        wrong_lineage = lineage.PilotExactTaskProductPilotLineageAttestationReceipt.from_mapping(
            wrong_lineage_raw
        )
        _reject(
            lambda: _evaluate(
                fresh,
                wrong_lineage,
                post_receipt,
            )
        )

        wrong_scope_raw = fresh.to_dict()
        wrong_scope_raw["operator_surface"] = "different_control_center"
        wrong_scope = human.HumanPilotDecisionProof.from_mapping(wrong_scope_raw)
        _reject(
            lambda: _evaluate(
                wrong_scope,
                lineage_receipt,
                post_receipt,
            )
        )

        broad_scope_raw = fresh.to_dict()
        broad_scope_raw["allowed_task_ids"] = [
            lineage_receipt.selected_pilot_task_id,
            "another.pilot.task",
        ]
        broad_scope_raw["allowed_task_ids"].sort()
        broad_scope = human.HumanPilotDecisionProof.from_mapping(broad_scope_raw)
        _reject(
            lambda: _evaluate(
                broad_scope,
                lineage_receipt,
                post_receipt,
            )
        )

        local_commit_raw = fresh.to_dict()
        local_commit_raw["local_commits_allowed"] = True
        local_commit = human.HumanPilotDecisionProof.from_mapping(local_commit_raw)
        _reject(
            lambda: _evaluate(
                local_commit,
                lineage_receipt,
                post_receipt,
            )
        )

        no_go_decision = human.build_human_pilot_decision(
            completion_proof=completion,
            decision_id="product-pilot-no-go-099",
            decision_maker_actor_id="product.pilot.owner",
            decision="no_go",
            operator_surface=lineage_receipt.operator_surface,
            allowed_task_ids=(lineage_receipt.selected_pilot_task_id,),
            workspace_root_path_sha256=lineage_receipt.workspace_root_path_sha256,
            local_commits_allowed=False,
            notes=("fresh product pilot remains blocked",),
            decided_at_utc="2026-09-15T09:54:05Z",
        )
        private_key, key = human_contract._trusted_key(actor="product.pilot.owner")
        no_go_signature = human_contract._sign(no_go_decision, private_key, key)
        no_go_verifier = Ed25519AuthorityVerifier(
            {key.key_id: key},
            minimum_keyring_epoch=1,
        )
        no_go = human._verify_human_pilot_decision(
            completion_proof=completion,
            decision=no_go_decision,
            signature=no_go_signature,
            verifier=no_go_verifier,
            now_provider=lambda: "2026-09-15T09:54:06Z",
        )
        assert no_go.pilot_go_authorized is False
        _reject(
            lambda: _evaluate(
                no_go,
                lineage_receipt,
                post_receipt,
            )
        )

        _reject(
            lambda: _evaluate(
                fresh,
                lineage_receipt,
                post_receipt,
                when="2026-09-15T09:59:07Z",
            )
        )
        _reject(
            lambda: _evaluate(
                fresh,
                lineage_receipt,
                post_receipt,
                when="2026-09-15T09:54:05Z",
            )
        )

        for field, value in (
            ("requirements_satisfied", False),
            ("product_pilot_start_ready", False),
            ("product_pilot_start_authorized", True),
            ("product_pilot_started", True),
            ("remote_write_authorized", True),
            ("production_activation_authorized", True),
            ("nonce_reusable", True),
            ("next_boundary_authorization_required", False),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: (
                    qualified.PilotExactTaskProductPilotStartQualifiedReadinessReceipt.from_mapping(
                        raw
                    )
                )
            )
    finally:
        lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        qualified.PilotExactTaskProductPilotStartQualifiedReadinessReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        qualified.evaluate_pilot_exact_task_product_pilot_start_qualified_readiness
    )
    assert tuple(public.parameters) == (
        "fresh_human_go_completion_proof",
        "fresh_human_go_proof",
        "fresh_human_go_signature",
        "product_pilot_lineage_attestation",
        "post_production_activation_attestation",
    )

    impl_source = code_of(IMPL)
    boundary_source = code_of(BOUNDARY)
    for source in (impl_source, boundary_source):
        for forbidden in (
            "subprocess.",
            "urllib.",
            "requests.",
            "http.client",
            "create_once_file",
            ".write_text(",
            ".write_bytes(",
            ".unlink(",
            ".rename(",
            "Ed25519PrivateKey",
        ):
            assert forbidden not in source
    assert "_canonical_human_pilot_decision_verifier" in boundary_source
    assert "_verify_human_pilot_decision" in boundary_source
    assert "product_pilot_start_ready: bool = True" in impl_source
    assert "product_pilot_start_authorized: bool = False" in impl_source
    assert "product_pilot_started: bool = False" in impl_source


if __name__ == "__main__":
    run_contract()
