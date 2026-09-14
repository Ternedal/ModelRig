from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/devcontrol/dc-l16/product-integration-inventory.json"
PROPOSAL = ROOT / "docs/devcontrol/dc-l16/product-integration-selection-proposal.json"
DESKTOP = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt"
BACKEND = ROOT / "backend/internal/httpapi/server.go"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_dc_l16_selection_proposal_is_inert_and_inventory_bound() -> None:
    inventory = load(INVENTORY)
    proposal = load(PROPOSAL)

    candidates = {entry["candidate_id"]: entry for entry in inventory["candidate_surfaces"]}
    assert set(candidates) == {
        "desktop.control-center",
        "android.control-center",
        "backend.local-api-host-pattern",
    }
    assert all(entry["selected"] is False for entry in candidates.values())

    assert proposal["source_inventory_head_sha"] == "30be16b320acd6655c07ab1476cceaead547e3e3"
    assert proposal["proposal"]["operator_surface"] == "desktop.control-center"
    assert proposal["proposal"]["route_host_pattern"] == "backend.local-api-host-pattern"
    assert proposal["proposal"]["feature_flag"] == "KALIV_DEVCONTROL_PILOT"
    assert proposal["proposal"]["route_prefix"] == "/api/v1/experimental/devcontrol-pilot"
    assert proposal["proposal"]["runtime_observer"] == "desktop-manual-refresh-only"
    assert proposal["proposal"]["automatic_polling"] is False
    assert proposal["proposal"]["unattended_cadence"] is False
    assert proposal["proposal"]["remote_transport"] is False
    assert proposal["proposal"]["local_commit_policy"] == "forbidden-until-human-go"

    decision = proposal["decision_state"]
    assert decision == {
        "human_selection_accepted": False,
        "operator_surface_selected": False,
        "feature_flag_selected": False,
        "product_route_selected": False,
        "runtime_observer_selected": False,
        "task_registry_selected": False,
        "feature_flag_implemented": False,
        "product_route_implemented": False,
        "product_ui_implemented": False,
        "runtime_observer_implemented": False,
    }

    authority = proposal["authority_state"]
    assert authority["authority"] == "dc-l16-product-integration-selection-proposal-only"
    for key, value in authority.items():
        if key != "authority":
            assert value is False, key


def test_dc_l16_proposed_names_are_not_implemented_in_product_sources() -> None:
    desktop = DESKTOP.read_text(encoding="utf-8")
    backend = BACKEND.read_text(encoding="utf-8")

    assert "Ingen automatisk polling" in desktop
    assert 'GET /api/v1/control-center/status' in backend
    assert 'os.Getenv("KALIV_AGENT3_ENABLED") == "1"' in backend

    for source in (desktop, backend):
        assert "kaliv_dev_control" not in source
        assert "KALIV_DEVCONTROL_PILOT" not in source

    assert "/api/v1/experimental/devcontrol-pilot" not in backend
