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

HANDOFF = ROOT / "docs/devcontrol/dc-l16/visionrig-sensor-control-handoff.json"
SCHEMA = ROOT / "devcontrol/schemas/rsi-pilot-visionrig-sensor-control-handoff-v1.schema.json"
SERVER = ROOT / "backend/internal/httpapi/server.go"
CONTROL_CENTER = ROOT / "backend/internal/httpapi/control_center.go"

PREDECESSOR_SHA = "582b163d7a71a934b43671ddad62a5644df3087e"
SUCCESSOR_SHA = "f9b646350c70900ec256387b7a7e544d2de3eb0b"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def run_contract() -> None:
    handoff = _load(HANDOFF)
    schema = _load(SCHEMA)

    assert handoff["schema"] == "kaliv-rsi-dc-l16-visionrig-sensor-control-handoff/v1"
    assert handoff["repository"] == "Ternedal/ModelRig"
    assert handoff["predecessor_server_blob_sha"] == PREDECESSOR_SHA

    choice = handoff["implementation_choice"]
    assert choice == {
        "capability": "visionrig.sensor-enabled",
        "feature_flag": "KALIV_VISIONRIG_SENSOR_CONTROL",
        "route": "PATCH /api/v1/control-center/vision/sensors/{sourceID}/enabled",
        "default_off": True,
        "bearer_authenticated": True,
        "loopback_upstream_required": True,
        "boolean_only_request": True,
        "receipt_verified": True,
        "raw_perception_access": False,
        "production_activation": False,
    }

    transition = handoff["tracked_source_transition"]
    assert transition == {
        "path": "backend/internal/httpapi/server.go",
        "from_git_blob_sha": PREDECESSOR_SHA,
        "to_git_blob_sha": SUCCESSOR_SHA,
    }
    assert _git_blob_sha(SERVER) == SUCCESSOR_SHA

    server = code_of(SERVER)
    control = code_of(CONTROL_CENTER)
    assert 'os.Getenv("KALIV_VISIONRIG_SENSOR_CONTROL") == "1"' in server
    assert 'PATCH /api/v1/control-center/vision/sensors/{sourceID}/enabled' in server
    assert "s.authMW(http.HandlerFunc(s.handleControlCenterVisionSensorEnabled))" in server

    assert "decoder.DisallowUnknownFields()" in control
    assert 'map[string]bool{"enabled": *input.Enabled}' in control
    assert "ip.IsLoopback()" in control
    assert 'result["schema"] != visionRigSensorMetadataSchema' in control
    assert 'metadata["source_id"] != sourceID' in control
    assert 'metadata["enabled"] != *input.Enabled' in control

    authority = handoff["authority_state"]
    assert authority == {
        "sensor_enabled_mutation_when_flagged": True,
        "other_sensor_metadata_mutation_authority": False,
        "raw_perception_read_authority": False,
        "scheduler_authority": False,
        "tool_execution_authority": False,
        "production_activation_authority": False,
        "authority": "visionrig-sensor-enabled-only",
    }

    assert schema["properties"]["predecessor_server_blob_sha"]["const"] == PREDECESSOR_SHA
    assert (
        schema["properties"]["tracked_source_transition"]["properties"]["to_git_blob_sha"]["const"]
        == SUCCESSOR_SHA
    )
