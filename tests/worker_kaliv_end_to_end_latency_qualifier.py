#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_end_to_end_latency_qualifier",
    ROOT / "scripts" / "kaliv_end_to_end_latency_qualifier.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def evidence() -> dict:
    event_id = "kaliv-event-001"
    return {
        "schema": module.SCHEMA,
        "candidate_git_sha": "a" * 40,
        "event_id": event_id,
        "real_event": True,
        "simulated": False,
        "clock": {
            "kind": "monotonic",
            "unit": "milliseconds",
            "origin": "single-observer",
        },
        "outward_kind": "voice+body",
        "phases": {
            "perception_received": {
                "correlation_id": event_id,
                "at_ms": 1000.0,
                "evidence_ref": "visionrig:world-evidence:abc",
            },
            "cognition_completed": {
                "correlation_id": event_id,
                "at_ms": 1325.5,
                "evidence_ref": "modelrig:cognition-event:def",
            },
            "outward_started": {
                "correlation_id": event_id,
                "at_ms": 1510.0,
                "evidence_ref": "kaliv:outward-event:ghi",
            },
        },
        "production_activation": False,
    }


def reject(mutator, fragment: str, message: str) -> None:
    value = evidence()
    mutator(value)
    try:
        module.qualify(value)
    except module.EndToEndLatencyQualificationError as exc:
        check(fragment in str(exc), message)
    else:
        check(False, message)


verdict = module.qualify(evidence())
check(verdict["state"] == "MEASURED", "real correlated event is measured")
check(verdict["end_to_end_ms"] == 510.0, "end-to-end latency is derived")
check(
    verdict["perception_to_cognition_ms"] == 325.5
    and verdict["cognition_to_outward_ms"] == 184.5,
    "phase latencies are derived from the same monotonic clock",
)
check(verdict["threshold_applied"] is False, "qualifier applies no invented latency SLO")
check(
    verdict["end_to_end_latency_gate_satisfied"] is True
    and verdict["release_gate_satisfied"] is False
    and verdict["production_activation"] is False,
    "measurement can satisfy its evidence gate but cannot release or activate production",
)
check(
    verdict["release_evidence_ref"].startswith(
        "kaliv-end-to-end-latency:" + "a" * 40 + ":"
    )
    and len(verdict["release_evidence_ref"].split(":")[-1]) == 64,
    "release evidence ref is content-addressed and exact-head-bound",
)

reject(
    lambda x: x.__setitem__("real_event", False),
    "real, non-simulated",
    "fixture/non-real event is rejected",
)
reject(
    lambda x: x.__setitem__("simulated", True),
    "real, non-simulated",
    "simulated event is rejected",
)
reject(
    lambda x: x["clock"].__setitem__("kind", "wall-clock"),
    "monotonic milliseconds",
    "wall-clock evidence is rejected",
)
reject(
    lambda x: x["phases"]["cognition_completed"].__setitem__(
        "correlation_id", "different-event"
    ),
    "correlation id does not match",
    "cross-event phase splice is rejected",
)
reject(
    lambda x: x["phases"]["cognition_completed"].__setitem__("at_ms", 999.0),
    "timestamps must be monotone",
    "non-monotone phase order is rejected",
)
reject(
    lambda x: x["phases"]["outward_started"].__setitem__(
        "evidence_ref", x["phases"]["cognition_completed"]["evidence_ref"]
    ),
    "evidence refs must be distinct",
    "reused evidence ref across phases is rejected",
)
reject(
    lambda x: x.__setitem__("outward_kind", "screen-only"),
    "outward_kind",
    "unsupported outward surface is rejected",
)
reject(
    lambda x: x.__setitem__("production_activation", True),
    "cannot activate production",
    "latency evidence cannot activate production",
)
reject(
    lambda x: x["phases"]["outward_started"].__setitem__(
        "at_ms", 1000.0 + module._MAX_LATENCY_MS + 1.0
    ),
    "safety cap",
    "unbounded measurement is rejected",
)

print(f"\nKaliv end-to-end latency qualifier contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
