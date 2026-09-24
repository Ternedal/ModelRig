from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from rsi_pilot_product_ui_observer_handoff_contract import (  # noqa: E402
    run_contract as run_ui_handoff_contract,
)
from source_code import code_of  # noqa: E402

DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import catalog  # noqa: E402

HANDOFF = ROOT / "docs/devcontrol/dc-l16/product-integration-implementation-handoff.json"
SCHEMA = ROOT / "devcontrol/schemas/rsi-pilot-product-integration-implementation-handoff-v1.schema.json"
UI_HANDOFF = ROOT / "docs/devcontrol/dc-l16/product-ui-observer-handoff.json"
DESKTOP = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt"
ANDROID = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterScreen.kt"
SERVER = ROOT / "backend/internal/httpapi/server.go"
PILOT = ROOT / "backend/internal/httpapi/devcontrol_pilot.go"
PILOT_TEST = ROOT / "backend/internal/httpapi/devcontrol_pilot_test.go"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def run_contract() -> None:
    handoff = _load(HANDOFF)
    schema = _load(SCHEMA)
    ui_handoff = _load(UI_HANDOFF) if UI_HANDOFF.is_file() else None

    assert handoff["schema"] == "kaliv-rsi-dc-l16-product-integration-implementation-handoff/v1"
    assert handoff["repository"] == "Ternedal/ModelRig"
    assert handoff["source_inventory_head_sha"] == "30be16b320acd6655c07ab1476cceaead547e3e3"
    assert handoff["source_selection_proposal_head_sha"] == "5978052d593033cbea545a34ddca6e45cfd4e39f"

    choice = handoff["implementation_choice"]
    assert choice == {
        "implementation_direction_selected": True,
        "operator_surface": "desktop.control-center",
        "route_host_pattern": "backend.local-api-host-pattern",
        "feature_flag": "KALIV_DEVCONTROL_PILOT",
        "route": "GET /api/v1/experimental/devcontrol-pilot/status",
        "manual_refresh_only": True,
        "human_pilot_go_verified": False,
    }

    transition = handoff["tracked_source_transition"]
    assert transition == {
        "path": "backend/internal/httpapi/server.go",
        "from_git_blob_sha": "6085d525ff86a3d2b5c7cdece20bcaeace896e85",
        "to_git_blob_sha": "582b163d7a71a934b43671ddad62a5644df3087e",
    }
    assert _git_blob_sha(SERVER) == transition["to_git_blob_sha"]

    new_files = handoff["new_product_files"]
    assert new_files == [
        {
            "path": "backend/internal/httpapi/devcontrol_pilot.go",
            "git_blob_sha": "ddbdbb0aba2c95a63d42d6b89aeb5fbd85fd134d",
        },
        {
            "path": "backend/internal/httpapi/devcontrol_pilot_test.go",
            "git_blob_sha": "07b787298bfd02259f97cb7800e4b5c48d895304",
        },
    ]
    assert _git_blob_sha(PILOT) == new_files[0]["git_blob_sha"]
    assert _git_blob_sha(PILOT_TEST) == new_files[1]["git_blob_sha"]

    # Android remains untouched at ADR-DC-018. Desktop may move only through
    # the separately pinned successor observer handoff.
    assert _git_blob_sha(ANDROID) == "82643d7cefe9a9c249e8e7cc8b480d9989b38606"
    if ui_handoff is None:
        assert _git_blob_sha(DESKTOP) == "0a9498ac0fe61ea742a47c1d6be1cf7886992321"
    else:
        assert ui_handoff["source_product_status_head_sha"] == "b7acd3db6e88a4316375923d4cf1f5be2cde51a8"
        ui_transition = ui_handoff["tracked_source_transition"]
        assert ui_transition["path"] == "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt"
        assert ui_transition["from_git_blob_sha"] == "0a9498ac0fe61ea742a47c1d6be1cf7886992321"
        assert _git_blob_sha(DESKTOP) == ui_transition["to_git_blob_sha"]
        assert ui_handoff["implementation_choice"]["human_pilot_go_verified"] is False
        assert ui_handoff["implementation_choice"]["executor_wired"] is False
        assert ui_handoff["implementation_choice"]["start_control_present"] is False
        run_ui_handoff_contract()

    server = code_of(SERVER)
    pilot = code_of(PILOT)
    assert 'GET /api/v1/experimental/devcontrol-pilot/status' in server
    assert 'POST /api/v1/experimental/devcontrol-pilot' not in server
    assert 'devControlPilotEnabled()' in server
    assert 'const devControlPilotFlag = "KALIV_DEVCONTROL_PILOT"' in pilot
    assert 'os.Getenv(devControlPilotFlag) == "1"' in pilot
    assert '"authority":                        "dc-l16-product-status-observation-only"' in pilot
    assert "kaliv_dev_control" not in server
    assert "kaliv_dev_control" not in pilot

    authority = handoff["authority_state"]
    assert authority["authority"] == "dc-l16-product-implementation-handoff-only"
    for key, value in authority.items():
        if key != "authority":
            assert value is False, key

    assert catalog.modelrig_command_catalog().command_ids == ()

    assert schema["properties"]["source_inventory_head_sha"]["const"] == handoff["source_inventory_head_sha"]
    assert schema["properties"]["source_selection_proposal_head_sha"]["const"] == handoff["source_selection_proposal_head_sha"]
    assert schema["properties"]["tracked_source_transition"]["properties"]["to_git_blob_sha"]["const"] == transition["to_git_blob_sha"]
    assert schema["properties"]["implementation_choice"]["properties"]["human_pilot_go_verified"]["const"] is False
    for key, value in authority.items():
        if key == "authority":
            assert schema["properties"]["authority_state"]["properties"][key]["const"] == value
        else:
            assert schema["properties"]["authority_state"]["properties"][key]["const"] is False
