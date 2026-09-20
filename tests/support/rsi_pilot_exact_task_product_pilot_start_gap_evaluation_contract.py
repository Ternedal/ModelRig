"""Adversarial contract for ADR-DC-099 product-pilot start gap evaluation."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from source_code import code_of  # noqa: E402

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_product_pilot_start_gap_evaluation as gap,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_product_pilot_start_requirements as requirements_boundary,
)
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-gap-evaluation-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_start_gap_evaluation.py"
)

IMPLEMENTATION_HANDOFF = (
    ROOT / "docs/devcontrol/dc-l16/product-integration-implementation-handoff.json"
)
UI_OBSERVER_HANDOFF = ROOT / "docs/devcontrol/dc-l16/product-ui-observer-handoff.json"
BACKEND_STATUS_SOURCE = ROOT / "backend/internal/httpapi/devcontrol_pilot.go"
DESKTOP_OBSERVER_SOURCE = (
    ROOT
    / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/DevControlPilotStatusSection.kt"
)

EXPECTED_BLOCKERS = (
    "feature-flag-scope-drift",
    "product-route-scope-drift",
    "fresh-human-product-pilot-go-missing",
    "task-registry-not-ready",
    "runtime-preflight-not-satisfied",
    "product-executor-not-wired",
    "product-start-control-absent",
    "kill-switch-runtime-not-wired",
    "revoke-runtime-not-wired",
    "restart-recovery-runtime-not-wired",
    "canonical-workspace-product-binding-not-verified",
    "native-windows-isolation-not-product-reverified",
    "trusted-git-closure-not-product-reverified",
    "local-only-product-execution-not-exercised",
    "product-start-network-write-block-not-verified",
    "product-start-credentials-absence-not-verified",
    "cancel-timeout-crash-recovery-not-verified",
    "workspace-reset-artifact-verification-not-verified",
    "physical-product-entrypoint-not-exercised",
    "requirements-not-satisfied",
)


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-099 unexpectedly accepted unsafe gap evidence")


def _inputs():
    fixture = lineage_contract._build_fixture()
    requirements = (
        requirements_boundary.build_pilot_exact_task_product_pilot_start_requirements(
            fixture["post_production"]
        )
    )
    lineage = lineage_contract._attest(fixture)
    return fixture, requirements, lineage


def run_contract() -> None:
    if os.name == "nt":
        return

    assert _git_blob_sha(IMPLEMENTATION_HANDOFF) == gap.IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA
    assert _git_blob_sha(UI_OBSERVER_HANDOFF) == gap.UI_OBSERVER_HANDOFF_GIT_BLOB_SHA
    assert _git_blob_sha(BACKEND_STATUS_SOURCE) == gap.BACKEND_STATUS_SOURCE_GIT_BLOB_SHA
    assert _git_blob_sha(DESKTOP_OBSERVER_SOURCE) == gap.DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA

    fixture, requirements, lineage = _inputs()
    try:
        receipt = gap.evaluate_pilot_exact_task_product_pilot_start_gaps(
            requirements=requirements,
            lineage_attestation=lineage,
        )
        assert (
            receipt.schema
            == gap.PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCHEMA
        )
        assert (
            receipt.authority
            == gap.PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_AUTHORITY
        )
        assert (
            receipt.evaluation_scope
            == gap.PILOT_EXACT_TASK_PRODUCT_PILOT_START_GAP_EVALUATION_SCOPE
        )
        assert receipt.requirements_sha256 == requirements.sha256
        assert receipt.lineage_attestation_sha256 == lineage.sha256
        assert (
            receipt.post_production_activation_attestation_sha256
            == requirements.post_production_activation_attestation_sha256
            == lineage.post_production_activation_attestation_sha256
        )
        assert (
            receipt.production_activation_candidate_sha256
            == requirements.production_activation_candidate_sha256
            == lineage.production_activation_candidate_sha256
        )
        assert receipt.repository == requirements.repository == lineage.repository
        assert receipt.merge_commit_sha == requirements.merge_commit_sha == lineage.merge_commit_sha
        assert receipt.signed_operator_surface == "desktop.control-center"
        assert receipt.implemented_operator_surface == "desktop.control-center"
        assert receipt.operator_surface_matches is True
        assert receipt.signed_feature_flag_name == "KALIV_DEVCONTROL_PILOT_ENABLED"
        assert receipt.implemented_feature_flag_name == "KALIV_DEVCONTROL_PILOT"
        assert receipt.feature_flag_scope_matches is False
        assert receipt.signed_product_route == "/api/v1/devcontrol/pilot"
        assert (
            receipt.implemented_product_route
            == "/api/v1/experimental/devcontrol-pilot/status"
        )
        assert receipt.product_route_scope_matches is False
        assert (
            receipt.implementation_handoff_git_blob_sha
            == gap.IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA
        )
        assert (
            receipt.ui_observer_handoff_git_blob_sha
            == gap.UI_OBSERVER_HANDOFF_GIT_BLOB_SHA
        )
        assert (
            receipt.backend_status_source_git_blob_sha
            == gap.BACKEND_STATUS_SOURCE_GIT_BLOB_SHA
        )
        assert (
            receipt.desktop_observer_source_git_blob_sha
            == gap.DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA
        )
        assert receipt.implementation_profile_sha256 == gap.IMPLEMENTATION_PROFILE_SHA256
        assert receipt.blocker_codes == EXPECTED_BLOCKERS
        assert set(receipt.blocker_codes).issubset(set(gap.KNOWN_BLOCKER_CODES))

        for field in (
            "requirements_lineage_bound",
            "implementation_profile_pinned",
            "feature_flag_default_off",
            "status_observer_implemented",
            "manual_refresh_only",
        ):
            assert getattr(receipt, field) is True
            raw = receipt.to_dict()
            raw[field] = False
            _reject(
                lambda raw=raw: (
                    gap.PilotExactTaskProductPilotStartGapEvaluationReceipt.from_mapping(
                        raw
                    )
                )
            )

        forced_false = (
            "fresh_human_product_pilot_go_verified",
            "task_registry_ready",
            "runtime_preflight_satisfied",
            "executor_wired",
            "start_control_present",
            "kill_switch_runtime_wired",
            "revoke_runtime_wired",
            "restart_recovery_runtime_wired",
            "canonical_workspace_product_binding_verified",
            "native_windows_isolation_product_reverified",
            "trusted_git_closure_product_reverified",
            "local_only_product_execution_exercised",
            "network_write_block_product_verified",
            "credentials_absent_product_verified",
            "cancel_timeout_crash_recovery_verified",
            "workspace_reset_artifact_verification_verified",
            "physical_product_entrypoint_exercised",
            "remote_transport_available",
            "status_surface_credentials_present",
            "requirements_satisfied",
            "product_capabilities_satisfied",
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        )
        for field in forced_false:
            assert getattr(receipt, field) is False
            raw = receipt.to_dict()
            raw[field] = True
            _reject(
                lambda raw=raw: (
                    gap.PilotExactTaskProductPilotStartGapEvaluationReceipt.from_mapping(
                        raw
                    )
                )
            )

        replayed = gap.PilotExactTaskProductPilotStartGapEvaluationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert replayed == receipt
        assert replayed.sha256 == receipt.sha256

        bad_match = receipt.to_dict()
        bad_match["feature_flag_scope_matches"] = True
        _reject(
            lambda: gap.PilotExactTaskProductPilotStartGapEvaluationReceipt.from_mapping(
                bad_match
            )
        )

        missing_blocker = receipt.to_dict()
        missing_blocker["blocker_codes"] = list(receipt.blocker_codes[1:])
        _reject(
            lambda: gap.PilotExactTaskProductPilotStartGapEvaluationReceipt.from_mapping(
                missing_blocker
            )
        )

        wrong_candidate = "f" * 64
        if wrong_candidate == requirements.production_activation_candidate_sha256:
            wrong_candidate = "e" * 64
        foreign_requirements = (
            requirements_boundary.PilotExactTaskProductPilotStartRequirements.from_mapping(
                {
                    **requirements.to_dict(),
                    "production_activation_candidate_sha256": wrong_candidate,
                }
            )
        )
        _reject(
            lambda: gap.evaluate_pilot_exact_task_product_pilot_start_gaps(
                requirements=foreign_requirements,
                lineage_attestation=lineage,
            )
        )

        wrong_post = "f" * 64
        if wrong_post == requirements.post_production_activation_attestation_sha256:
            wrong_post = "e" * 64
        foreign_post_requirements = (
            requirements_boundary.PilotExactTaskProductPilotStartRequirements.from_mapping(
                {
                    **requirements.to_dict(),
                    "post_production_activation_attestation_sha256": wrong_post,
                }
            )
        )
        _reject(
            lambda: gap.evaluate_pilot_exact_task_product_pilot_start_gaps(
                requirements=foreign_post_requirements,
                lineage_attestation=lineage,
            )
        )
    finally:
        lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        gap.PilotExactTaskProductPilotStartGapEvaluationReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False
    assert (
        schema["properties"]["implemented_operator_surface"]["const"]
        == gap.IMPLEMENTED_OPERATOR_SURFACE
    )
    assert (
        schema["properties"]["implemented_feature_flag_name"]["const"]
        == gap.IMPLEMENTED_FEATURE_FLAG_NAME
    )
    assert (
        schema["properties"]["implemented_product_route"]["const"]
        == gap.IMPLEMENTED_PRODUCT_ROUTE
    )
    assert (
        schema["properties"]["implementation_handoff_git_blob_sha"]["const"]
        == gap.IMPLEMENTATION_HANDOFF_GIT_BLOB_SHA
    )
    assert (
        schema["properties"]["ui_observer_handoff_git_blob_sha"]["const"]
        == gap.UI_OBSERVER_HANDOFF_GIT_BLOB_SHA
    )
    assert (
        schema["properties"]["backend_status_source_git_blob_sha"]["const"]
        == gap.BACKEND_STATUS_SOURCE_GIT_BLOB_SHA
    )
    assert (
        schema["properties"]["desktop_observer_source_git_blob_sha"]["const"]
        == gap.DESKTOP_OBSERVER_SOURCE_GIT_BLOB_SHA
    )
    assert schema["properties"]["product_pilot_start_ready"]["const"] is False
    assert schema["properties"]["product_pilot_start_authorized"]["const"] is False
    assert schema["properties"]["product_pilot_started"]["const"] is False

    signature = inspect.signature(
        gap.evaluate_pilot_exact_task_product_pilot_start_gaps
    )
    assert tuple(signature.parameters) == ("requirements", "lineage_attestation")

    source = code_of(SOURCE)
    for forbidden in (
        "subprocess.",
        "urllib.",
        "requests.",
        "http.client",
        "socket.",
        "create_once_file",
        ".write_text(",
        ".write_bytes(",
        ".unlink(",
        ".rename(",
        "authorize_pilot_exact_task_product_pilot_start",
        "execute_pilot_exact_task_product_pilot_start",
    ):
        assert forbidden not in source
    assert "product_pilot_start_ready: bool = False" in source
    assert "product_pilot_start_authorized: bool = False" in source
    assert "product_pilot_started: bool = False" in source
    assert "KALIV_DEVCONTROL_PILOT_ENABLED" not in source
    assert 'IMPLEMENTED_FEATURE_FLAG_NAME = "KALIV_DEVCONTROL_PILOT"' in source
    assert (
        'IMPLEMENTED_PRODUCT_ROUTE = "/api/v1/experimental/devcontrol-pilot/status"'
        in source
    )


if __name__ == "__main__":
    run_contract()
