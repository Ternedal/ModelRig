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

HANDOFF = ROOT / "docs/devcontrol/dc-l16/product-ui-observer-handoff.json"
SCHEMA = ROOT / "devcontrol/schemas/rsi-pilot-product-ui-observer-handoff-v1.schema.json"
DESKTOP = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt"
CLIENT = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/DevControlPilotStatusClient.kt"
SECTION = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/DevControlPilotStatusSection.kt"
CLIENT_TEST = ROOT / "desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/net/DevControlPilotStatusClientTest.kt"
SECTION_TEST = ROOT / "desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/DevControlPilotStatusSectionTest.kt"
SERVER = ROOT / "backend/internal/httpapi/server.go"
PILOT = ROOT / "backend/internal/httpapi/devcontrol_pilot.go"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def run_contract() -> None:
    handoff = _load(HANDOFF)
    schema = _load(SCHEMA)

    assert handoff["schema"] == "kaliv-rsi-dc-l16-product-ui-observer-handoff/v1"
    assert handoff["repository"] == "Ternedal/ModelRig"
    assert handoff["source_product_status_head_sha"] == "b7acd3db6e88a4316375923d4cf1f5be2cde51a8"

    choice = handoff["implementation_choice"]
    assert choice == {
        "operator_surface": "desktop.control-center",
        "route": "GET /api/v1/experimental/devcontrol-pilot/status",
        "ui_observer_implemented": True,
        "default_off_hidden_on_404": True,
        "manual_refresh_only": True,
        "executor_wired": False,
        "start_control_present": False,
        "human_pilot_go_verified": False,
    }

    transition = handoff["tracked_source_transition"]
    assert transition == {
        "path": "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt",
        "from_git_blob_sha": "0a9498ac0fe61ea742a47c1d6be1cf7886992321",
        "to_git_blob_sha": "ccf605762dfcdf95c9f2f1a60de0986a3c84564c",
    }
    assert _git_blob_sha(DESKTOP) == transition["to_git_blob_sha"]

    expected_files = [
        (CLIENT, "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/DevControlPilotStatusClient.kt", "0e9b16b565cad721de7532d681abd89e7850a4f1"),
        (SECTION, "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/DevControlPilotStatusSection.kt", "a3389801f3c7217b3d72bf85e2e87996d6f0a0b5"),
        (CLIENT_TEST, "desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/net/DevControlPilotStatusClientTest.kt", "343eec567da69e4deaa09826c4e97aa795dbfcba"),
        (SECTION_TEST, "desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/DevControlPilotStatusSectionTest.kt", "cf6389262d25fcfd89ac15df2ce3f2169b8e28f0"),
    ]
    new_files = handoff["new_product_files"]
    assert len(new_files) == len(expected_files)
    for item, (path, relative, sha) in zip(new_files, expected_files, strict=True):
        assert item == {"path": relative, "git_blob_sha": sha}
        assert _git_blob_sha(path) == sha

    # Backend seam remains bound to the currently qualified tracked-source transition.
    assert _git_blob_sha(SERVER) == "582b163d7a71a934b43671ddad62a5644df3087e"
    assert _git_blob_sha(PILOT) == "ddbdbb0aba2c95a63d42d6b89aeb5fbd85fd134d"

    desktop = code_of(DESKTOP)
    client = code_of(CLIENT)
    section = code_of(SECTION)

    assert "DevControlPilotStatusSection(" in desktop
    assert "Ingen automatisk polling" in desktop
    assert 'const val ROUTE = "/api/v1/experimental/devcontrol-pilot/status"' in client
    assert "if (response.statusCode() == 404) return null" in client
    assert "ignoreUnknownKeys = false" in client
    assert "must remain false" in client
    assert "LaunchedEffect(baseUrl, token, refreshGeneration)" in section
    assert "DevControlPilotStatusClient(baseUrl, token).status()" in section
    assert "Ingen Start-knap" in section

    for forbidden in ("delay(", "while (", "Button(", "OutlinedButton("):
        assert forbidden not in section, forbidden
    for source in (desktop, client, section):
        assert "kaliv_dev_control" not in source

    authority = handoff["authority_state"]
    assert authority["authority"] == "dc-l16-product-ui-observer-handoff-only"
    for key, value in authority.items():
        if key != "authority":
            assert value is False, key

    assert catalog.modelrig_command_catalog().command_ids == ()

    assert schema["properties"]["source_product_status_head_sha"]["const"] == handoff["source_product_status_head_sha"]
    assert schema["properties"]["tracked_source_transition"]["properties"]["to_git_blob_sha"]["const"] == transition["to_git_blob_sha"]
    assert schema["properties"]["implementation_choice"]["properties"]["executor_wired"]["const"] is False
    assert schema["properties"]["implementation_choice"]["properties"]["start_control_present"]["const"] is False
    assert schema["properties"]["implementation_choice"]["properties"]["human_pilot_go_verified"]["const"] is False
    for key, value in authority.items():
        expected = schema["properties"]["authority_state"]["properties"][key]["const"]
        assert expected == value
