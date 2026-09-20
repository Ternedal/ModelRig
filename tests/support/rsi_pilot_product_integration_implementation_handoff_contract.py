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

HANDOFF = ROOT / "docs/devcontrol/dc-l16/product-integration-implementation-handoff.json"
SCHEMA = ROOT / "devcontrol/schemas/rsi-pilot-product-integration-implementation-handoff-v1.schema.json"
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
        "to_git_blob_sha": "3b202c783b288f77572611ee71e0d732183e5404",
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

    # Non-selected/untouched candidate surfaces remain exactly at ADR-DC-018.
    assert _git_blob_sha(DESKTOP) == "0a9498ac0fe61ea742a47c1d6be1cf7886992321"
    assert _git_blob_sha(ANDROID) == "82643d7cefe9a9c249e8e7cc8b480d9989b38606"

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
