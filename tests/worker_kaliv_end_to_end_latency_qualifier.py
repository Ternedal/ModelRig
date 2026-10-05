#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
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


def source(phase: str) -> dict:
    base = {
        "schema": module.SOURCE_SCHEMA,
        "phase": phase,
        "candidate_git_sha": "a" * 40,
        "event_id": "kaliv-event-001",
        "runtime_epoch": "runtime-epoch-001",
        "observer_id": "observer-process-001",
        "clock": {
            "kind": "monotonic",
            "unit": "milliseconds",
            "origin": "single-observer",
        },
        "observed_at_ms": {
            "perception_received": 1000.0,
            "cognition_completed": 1325.5,
            "outward_started": 1510.0,
        }[phase],
        "real_event": True,
        "simulated": False,
        "replay": False,
        "details": {},
        "production_activation": False,
    }
    if phase == "perception_received":
        base["details"] = {"input_kind": "voice", "input_id": "input-001"}
    elif phase == "cognition_completed":
        base["details"] = {
            "cognition_event_id": "kaliv-event-001",
            "transition_receipt_ref": "consciousness-transition:abc",
            "completed_cycles": 1,
        }
    else:
        base["details"] = {
            "outward_kind": "voice+body",
            "started": True,
            "utterance_id": "utterance-001",
            "body_runtime_id": "body-action-001",
        }
    return base


def write_sources(root: Path, mutate=None) -> tuple[Path, Path, Path]:
    values = {phase: source(phase) for phase in module._PHASES}
    if mutate:
        mutate(values)
    paths = []
    for phase in module._PHASES:
        path = root / f"{phase}.json"
        path.write_text(json.dumps(values[phase], sort_keys=True), encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def qualify(root: Path, mutate=None):
    perception, cognition, outward = write_sources(root, mutate)
    return module.qualify_receipts(
        evidence_root=root,
        perception_path=perception,
        cognition_path=cognition,
        outward_path=outward,
    )


def reject(mutator, fragment: str, message: str) -> None:
    with tempfile.TemporaryDirectory(prefix="kaliv-e2e-latency-") as td:
        try:
            qualify(Path(td), mutator)
        except module.EndToEndLatencyQualificationError as exc:
            check(fragment in str(exc), message)
        else:
            check(False, message)


with tempfile.TemporaryDirectory(prefix="kaliv-e2e-latency-") as td:
    verdict = qualify(Path(td))
    check(verdict["state"] == "MEASURED", "real correlated receipts are measured")
    check(verdict["end_to_end_ms"] == 510.0, "end-to-end latency is derived")
    check(
        verdict["perception_to_cognition_ms"] == 325.5
        and verdict["cognition_to_outward_ms"] == 184.5,
        "phase latencies derive from one monotonic observer",
    )
    check(verdict["threshold_applied"] is False, "no invented latency SLO is applied")
    check(
        len(verdict["source_receipts"]) == 3
        and all(len(item["sha256"]) == 64 for item in verdict["source_receipts"]),
        "verdict binds all three source receipts by SHA-256",
    )
    check(
        verdict["release_evidence_ref"].startswith(
            "kaliv-end-to-end-latency:" + "a" * 40 + ":"
        ),
        "canonical evidence ref remains exact-head-bound",
    )
    check(
        verdict["release_gate_satisfied"] is False
        and verdict["production_activation"] is False,
        "latency evidence cannot release or activate production",
    )

reject(
    lambda x: x["perception_received"].__setitem__("simulated", True),
    "real, non-simulated",
    "simulated perception is rejected",
)
reject(
    lambda x: x["cognition_completed"].__setitem__(
        "candidate_git_sha", "b" * 40
    ),
    "candidate SHA mismatch",
    "mixed candidate SHA is rejected",
)
reject(
    lambda x: x["cognition_completed"].__setitem__("event_id", "other-event"),
    "mixed correlation/event ids",
    "cross-event phase splice is rejected",
)
reject(
    lambda x: x["outward_started"].__setitem__("runtime_epoch", "epoch-other"),
    "mixed runtime epoch",
    "mixed runtime epoch is rejected",
)
reject(
    lambda x: x["outward_started"].__setitem__("observer_id", "observer-other"),
    "mixed observer clock",
    "mixed observer process is rejected",
)
reject(
    lambda x: x["cognition_completed"]["details"].__setitem__(
        "cognition_event_id", "other-event"
    ),
    "cognition_event_id does not match",
    "cognition completion must bind canonical event id",
)
reject(
    lambda x: x["cognition_completed"]["details"].__setitem__("completed_cycles", 0),
    "at least one completed real cycle",
    "zero-cycle cognition evidence is rejected",
)
reject(
    lambda x: x["outward_started"]["details"].__setitem__("started", False),
    "actual outward start",
    "queued-but-not-started outward evidence is rejected",
)
reject(
    lambda x: x["outward_started"]["details"].__setitem__("utterance_id", None),
    "requires utterance_id",
    "voice+body evidence requires utterance identity",
)
reject(
    lambda x: x["cognition_completed"].__setitem__("observed_at_ms", 999.0),
    "timestamps must be monotone",
    "non-monotone source receipts are rejected",
)
reject(
    lambda x: x["perception_received"].__setitem__("replay", True),
    "replay evidence",
    "replayed source evidence is rejected",
)
reject(
    lambda x: x["outward_started"].__setitem__("production_activation", True),
    "cannot activate production",
    "source receipt cannot overclaim production authority",
)

with tempfile.TemporaryDirectory(prefix="kaliv-e2e-latency-path-") as td:
    root = Path(td)
    outside_dir = Path(tempfile.mkdtemp(prefix="kaliv-e2e-outside-"))
    try:
        perception, cognition, outward = write_sources(root)
        outside = outside_dir / "outward.json"
        outside.write_text(outward.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            module.qualify_receipts(
                evidence_root=root,
                perception_path=perception,
                cognition_path=cognition,
                outward_path=outside,
            )
        except module.EndToEndLatencyQualificationError as exc:
            check("must exist under evidence root" in str(exc), "path escape is rejected")
        else:
            check(False, "path escape is rejected")
    finally:
        for child in outside_dir.iterdir():
            child.unlink()
        outside_dir.rmdir()

if hasattr(os, "symlink"):
    with tempfile.TemporaryDirectory(prefix="kaliv-e2e-latency-link-") as td:
        root = Path(td)
        perception, cognition, outward = write_sources(root)
        target = root / "outward-target.json"
        outward.replace(target)
        link = root / "outward_started.json"
        try:
            link.symlink_to(target)
        except OSError:
            check(True, "symlink test skipped where symlink creation is unavailable")
        else:
            try:
                module.qualify_receipts(
                    evidence_root=root,
                    perception_path=perception,
                    cognition_path=cognition,
                    outward_path=link,
                )
            except module.EndToEndLatencyQualificationError as exc:
                check("must not traverse symlinks" in str(exc), "symlink receipt is rejected")
            else:
                check(False, "symlink receipt is rejected")

print(f"\nKaliv end-to-end latency qualifier contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
