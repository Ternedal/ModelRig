"""Adversarial contracts for ADR-DC-018 inventory and ADR-DC-019 selection requirements."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from source_code import code_of  # noqa: E402

DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import catalog  # noqa: E402

INVENTORY_PATH = ROOT / "docs" / "devcontrol" / "dc-l16" / "product-integration-inventory.json"
SCHEMA_PATH = ROOT / "devcontrol" / "schemas" / "rsi-pilot-product-integration-inventory-v1.schema.json"
SELECTION_REQUIREMENTS_PATH = (
    ROOT / "docs" / "devcontrol" / "dc-l16" / "product-integration-selection-requirements.json"
)
SELECTION_REQUIREMENTS_SCHEMA_PATH = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-product-integration-selection-requirements-v1.schema.json"
)

EXPECTED = (
    (
        "desktop.control-center",
        "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt",
        "0a9498ac0fe61ea742a47c1d6be1cf7886992321",
    ),
    (
        "android.control-center",
        "android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterScreen.kt",
        "82643d7cefe9a9c249e8e7cc8b480d9989b38606",
    ),
    (
        "backend.local-api-host-pattern",
        "backend/internal/httpapi/server.go",
        "6085d525ff86a3d2b5c7cdece20bcaeace896e85",
    ),
)


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _assert_selection_requirements() -> None:
    requirements = _load(SELECTION_REQUIREMENTS_PATH)
    schema = _load(SELECTION_REQUIREMENTS_SCHEMA_PATH)

    assert requirements["schema"] == "kaliv-rsi-dc-l16-product-integration-selection-requirements/v1"
    assert requirements["repository"] == "Ternedal/ModelRig"
    assert schema["properties"]["schema"]["const"] == requirements["schema"]
    assert schema["properties"]["repository"]["const"] == requirements["repository"]

    source = requirements["source_inventory"]
    assert source == {
        "source_head_sha": "30be16b320acd6655c07ab1476cceaead547e3e3",
        "inventory_path": "docs/devcontrol/dc-l16/product-integration-inventory.json",
        "inventory_git_blob_sha": "babad0dfc82ad359ee053817bae2674a8f8b38a0",
        "candidate_ids": [candidate_id for candidate_id, _, _ in EXPECTED],
    }
    assert _git_blob_sha(INVENTORY_PATH) == source["inventory_git_blob_sha"]

    source_schema = schema["properties"]["source_inventory"]["properties"]
    assert source_schema["source_head_sha"]["const"] == source["source_head_sha"]
    assert source_schema["inventory_path"]["const"] == source["inventory_path"]
    assert source_schema["inventory_git_blob_sha"]["const"] == source["inventory_git_blob_sha"]
    schema_candidate_ids = [item["const"] for item in source_schema["candidate_ids"]["prefixItems"]]
    assert schema_candidate_ids == source["candidate_ids"]

    binding = requirements["binding_requirements"]
    assert binding == {
        "verified_human_pilot_decision_required": True,
        "positive_human_pilot_decision_required": True,
        "exact_single_trial_scope_required": True,
        "operator_surface_must_equal_signed_scope": True,
        "known_surface_must_bind_inventory_candidate": True,
        "unknown_surface_requires_fresh_exact_source_inventory": True,
        "selected_task_must_equal_single_trial_task": True,
        "workspace_digest_must_equal_single_trial_scope": True,
        "local_commit_policy_must_not_broaden_signed_scope": True,
    }
    for key, value in binding.items():
        assert value is True, key
        assert schema["properties"]["binding_requirements"]["properties"][key]["const"] is True

    decisions = requirements["product_design_decisions_required"]
    assert set(decisions) == {
        "operator_surface",
        "feature_flag_name",
        "product_route",
        "runtime_observer",
        "task_registry",
        "workspace_policy",
        "review_authorization_roles",
        "kill_revoke_cleanup",
        "local_commit_policy",
    }
    for key, value in decisions.items():
        assert value is True, key
        assert schema["properties"]["product_design_decisions_required"]["properties"][key]["const"] is True

    selection = requirements["selection_state"]
    assert set(selection) == {
        "human_selection_recorded",
        "operator_surface_selected",
        "feature_flag_selected",
        "product_route_selected",
        "runtime_observer_selected",
        "task_registry_selected",
        "workspace_policy_selected",
        "review_authorization_roles_selected",
        "kill_revoke_cleanup_selected",
        "local_commit_policy_selected",
    }
    for key, value in selection.items():
        assert value is False, key
        assert schema["properties"]["selection_state"]["properties"][key]["const"] is False

    authority = requirements["authority_state"]
    assert authority["normal_command_catalog_empty"] is True
    assert authority["authority"] == "dc-l16-product-integration-selection-requirements-only"
    for key in (
        "integration_ready",
        "preflight_observed",
        "preflight_satisfied",
        "pilot_start_authorized",
        "product_pilot_started",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    ):
        assert authority[key] is False, key

    authority_schema = schema["properties"]["authority_state"]["properties"]
    assert authority_schema["normal_command_catalog_empty"]["const"] is True
    assert authority_schema["authority"]["const"] == authority["authority"]
    for key in authority:
        if key not in {"normal_command_catalog_empty", "authority"}:
            assert authority_schema[key]["const"] is False


def run_contract() -> None:
    inventory = _load(INVENTORY_PATH)
    schema = _load(SCHEMA_PATH)

    assert inventory["schema"] == "kaliv-rsi-dc-l16-product-integration-inventory/v1"
    assert inventory["repository"] == "Ternedal/ModelRig"
    assert inventory["source_parent_sha"] == "7cc350fc50baad9f48fae88f76b6ad17b3a3817f"
    assert schema["properties"]["source_parent_sha"]["const"] == inventory["source_parent_sha"]

    candidates = inventory["candidate_surfaces"]
    assert len(candidates) == len(EXPECTED) == 3
    for item, (candidate_id, relative_path, expected_sha) in zip(candidates, EXPECTED, strict=True):
        assert item["candidate_id"] == candidate_id
        assert item["path"] == relative_path
        assert item["git_blob_sha"] == expected_sha
        assert item["selected"] is False
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        assert _git_blob_sha(path) == expected_sha, f"source drift: {relative_path}"

    desktop = code_of(ROOT / EXPECTED[0][1])
    android = code_of(ROOT / EXPECTED[1][1])
    backend = code_of(ROOT / EXPECTED[2][1])

    assert "fun DesktopControlCenterDialog(" in desktop
    assert "Ingen automatisk polling" in desktop
    assert "fun ControlCenterScreen(" in android
    assert "Ingen automatisk polling" in android

    for marker in (
        '/api/v1/control-center/status',
        'KALIV_AGENT3_ENABLED',
        'KALIV_AGENT4_OPERATOR_API',
        'githubConnectorPilotEnabled()',
    ):
        assert marker in backend, marker

    for source in (desktop, android, backend):
        assert "kaliv_dev_control" not in source

    backend_lower = backend.lower()
    assert "kaliv_devcontrol" not in backend_lower
    assert "kalivdev" not in backend_lower
    assert "/devcontrol" not in backend_lower

    patterns = inventory["verified_existing_patterns"]
    assert all(value is True for value in patterns.values())

    absence = inventory["verified_absence"]
    assert all(value is False for value in absence.values())

    selection = inventory["selection_state"]
    assert selection == {
        "operator_surface_selected": False,
        "feature_flag_selected": False,
        "product_route_selected": False,
        "runtime_observer_selected": False,
        "task_registry_selected": False,
    }

    authority = inventory["authority_state"]
    assert authority["normal_command_catalog_empty"] is True
    for key in (
        "integration_ready",
        "preflight_observed",
        "preflight_satisfied",
        "pilot_start_authorized",
        "product_pilot_started",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    ):
        assert authority[key] is False, key
    assert authority["authority"] == "dc-l16-product-integration-inventory-only"

    assert catalog.modelrig_command_catalog().command_ids == ()

    # Schema must encode the same non-selection/non-authority constants, so a
    # reconstructed inventory cannot silently broaden the evidence claim.
    schema_candidates = schema["properties"]["candidate_surfaces"]["prefixItems"]
    for item_schema, item in zip(schema_candidates, candidates, strict=True):
        assert item_schema["properties"]["selected"]["const"] is False
        assert item_schema["properties"]["git_blob_sha"]["const"] == item["git_blob_sha"]
    for key in selection:
        assert schema["properties"]["selection_state"]["properties"][key]["const"] is False
    for key, value in authority.items():
        if key == "normal_command_catalog_empty":
            assert schema["properties"]["authority_state"]["properties"][key]["const"] is True
        elif key == "authority":
            assert schema["properties"]["authority_state"]["properties"][key]["const"] == value
        else:
            assert schema["properties"]["authority_state"]["properties"][key]["const"] is False

    _assert_selection_requirements()


if __name__ == "__main__":
    run_contract()
