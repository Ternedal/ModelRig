from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from source_code import code_of  # noqa: E402

INVENTORY = ROOT / "docs/devcontrol/dc-l16/product-integration-inventory.json"
PROPOSAL = ROOT / "docs/devcontrol/dc-l16/product-integration-selection-proposal.json"
HANDOFF = ROOT / "docs/devcontrol/dc-l16/product-integration-implementation-handoff.json"
DESKTOP = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt"
BACKEND = ROOT / "backend/internal/httpapi/server.go"
PILOT = ROOT / "backend/internal/httpapi/devcontrol_pilot.go"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_contract() -> None:
    inventory = load(INVENTORY)
    proposal = load(PROPOSAL)
    handoff = load(HANDOFF) if HANDOFF.is_file() else None

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

    # The proposal remains immutable historical evidence even when a later
    # implementation handoff exists; it never retroactively becomes a GO.
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

    desktop = code_of(DESKTOP)
    backend = code_of(BACKEND)

    assert "Ingen automatisk polling" in desktop
    assert 'GET /api/v1/control-center/status' in backend
    assert 'os.Getenv("KALIV_AGENT3_ENABLED") == "1"' in backend
    assert "kaliv_dev_control" not in desktop
    assert "kaliv_dev_control" not in backend

    if handoff is None:
        assert "KALIV_DEVCONTROL_PILOT" not in backend
        assert "/api/v1/experimental/devcontrol-pilot" not in backend
    else:
        assert handoff["source_selection_proposal_head_sha"] == "5978052d593033cbea545a34ddca6e45cfd4e39f"
        assert handoff["implementation_choice"]["implementation_direction_selected"] is True
        assert handoff["implementation_choice"]["human_pilot_go_verified"] is False
        assert handoff["implementation_choice"]["operator_surface"] == proposal["proposal"]["operator_surface"]
        assert handoff["implementation_choice"]["route_host_pattern"] == proposal["proposal"]["route_host_pattern"]
        assert handoff["implementation_choice"]["feature_flag"] == proposal["proposal"]["feature_flag"]
        assert 'GET /api/v1/experimental/devcontrol-pilot/status' in backend
        pilot = code_of(PILOT)
        assert 'const devControlPilotFlag = "KALIV_DEVCONTROL_PILOT"' in pilot
        assert 'os.Getenv(devControlPilotFlag) == "1"' in pilot
        assert "kaliv_dev_control" not in pilot
