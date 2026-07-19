from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_tmp = tempfile.mkdtemp(prefix="kaliv-capability-v2-")
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(_tmp, "tools.json"))
os.environ.setdefault("KALIV_JOBS_DB", os.path.join(_tmp, "jobs.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _tmp)
sys.path.insert(0, str(ROOT / "worker"))

from app import tools  # noqa: E402
from app.capability_schema import (  # noqa: E402
    SCHEMA,
    CapabilitySchemaError,
    descriptors_from_registry,
    parse_descriptor,
)

FIXTURES = json.loads(
    (ROOT / "contracts" / "kaliv-capability-v2-fixtures.json").read_text(
        encoding="utf-8"
    )
)
JSON_SCHEMA = json.loads(
    (ROOT / "contracts" / "kaliv-capability-v2.schema.json").read_text(
        encoding="utf-8"
    )
)


def test_shared_fixtures_round_trip_canonically() -> None:
    assert FIXTURES["schema"] == "kaliv-capability-fixtures/v1"
    for fixture in FIXTURES["valid"]:
        descriptor = parse_descriptor(fixture["descriptor"])
        assert descriptor.canonical_json() == fixture["canonical"]
        assert (
            parse_descriptor(json.loads(descriptor.canonical_json()))
            == descriptor
        )


def test_shared_invalid_fixtures_fail_closed() -> None:
    for fixture in FIXTURES["invalid"]:
        try:
            parse_descriptor(fixture["descriptor"])
        except CapabilitySchemaError:
            pass
        else:
            raise AssertionError(
                f"invalid fixture was accepted: {fixture['name']}"
            )


def test_registry_adapter_is_pure_and_complete() -> None:
    before = tools.GATE.list_tools()
    descriptors = descriptors_from_registry(tools.REGISTRY)
    after = tools.GATE.list_tools()

    assert before == after, "schema adaptation changed existing tool behavior"
    assert len(descriptors) == len(tools.REGISTRY)
    assert [item.capability_id for item in descriptors] == sorted(
        f"tool:{name}" for name in tools.REGISTRY
    )

    for descriptor in descriptors:
        name = descriptor.capability_id.removeprefix("tool:")
        tool = tools.REGISTRY[name]
        assert descriptor.access == tool.risk
        assert descriptor.impact == tool.impact
        assert descriptor.data_class == tool.sensitivity
        assert descriptor.termination_mode == tool.cancellation
        assert descriptor.idempotent is tool.idempotent
        assert descriptor.production_activation is False
        assert descriptor.network_mode == "undeclared"
        assert descriptor.isolation.mode == (
            "process" if tool.isolate else "in_process"
        )
        assert descriptor.scheduling.allowed is tool.schedulable
        assert descriptor.confirmation.mode == (
            "required" if tool.risk in {"write", "desktop"} else "none"
        )

        payload = descriptor.to_dict()
        assert "enabled" not in payload
        assert parse_descriptor(payload) == descriptor
        assert descriptor.canonical_json() == json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def test_schema_document_matches_runtime_contract() -> None:
    assert JSON_SCHEMA["properties"]["schema"]["const"] == SCHEMA
    assert JSON_SCHEMA["additionalProperties"] is False
    assert (
        JSON_SCHEMA["properties"]["production_activation"]["const"]
        is False
    )
    expected = {
        "schema",
        "capability_id",
        "kind",
        "description",
        "access",
        "impact",
        "data_class",
        "parameters",
        "isolation",
        "scheduling",
        "confirmation",
        "network",
        "termination",
        "replay",
        "production_activation",
    }
    assert set(JSON_SCHEMA["required"]) == expected
    for nested, required in {
        "isolation": {"mode", "env_allow"},
        "scheduling": {"allowed", "reason"},
        "confirmation": {"mode"},
        "network": {"mode", "destinations"},
        "termination": {"mode"},
        "replay": {"idempotent"},
    }.items():
        contract = JSON_SCHEMA["properties"][nested]
        assert contract["additionalProperties"] is False
        assert set(contract["required"]) == required


def test_registry_key_mismatch_is_rejected() -> None:
    one = next(iter(tools.REGISTRY.values()))
    try:
        descriptors_from_registry({"wrong-key": one})
    except CapabilitySchemaError:
        pass
    else:
        raise AssertionError("registry key/name mismatch was accepted")


TESTS = [
    value
    for name, value in sorted(globals().items())
    if name.startswith("test_")
]

if __name__ == "__main__":
    for test_case in TESTS:
        test_case()
    print(f"capability schema v2: {len(TESTS)} passed")
