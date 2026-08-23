#!/usr/bin/env python3
"""Adversarial integrity checks for BodyRig tracking v1."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bodyrig.tracking import (  # noqa: E402
    BackendFrame,
    Landmark,
    MediaFacts,
    TrackingContractError,
    build_tracking_timeline,
)

PASSED = FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def expect_error(fn, label: str) -> None:
    try:
        fn()
    except TrackingContractError as exc:
        check(True, f"{label} ({exc})")
    except BaseException as exc:  # noqa: BLE001
        check(False, f"{label} -- wrong exception {type(exc).__name__}: {exc}")
    else:
        check(False, f"{label} -- no exception")


class StableBackend:
    backend_id = "integrity-fixture"
    backend_version = "1"
    model_revision = "r1"

    def inspect(self, source_path) -> MediaFacts:
        return MediaFacts("h264", 1280, 720, 100_000, 30.0)

    def extract(self, source_path):
        return iter([
            BackendFrame(
                timestamp_us=0,
                body={"nose": Landmark(0.5, 0.25, 0.0, 0.9)},
            )
        ])


class MutateDuringInspect(StableBackend):
    def inspect(self, source_path) -> MediaFacts:
        facts = super().inspect(source_path)
        pathlib.Path(source_path).write_bytes(b"different-source-bytes")
        return facts


class ReplaceDuringExtract(StableBackend):
    def extract(self, source_path):
        path = pathlib.Path(source_path)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(b"replacement-source-bytes")
        replacement.replace(path)
        return super().extract(source_path)


with tempfile.TemporaryDirectory(prefix="bodyrig-track-integrity-") as td:
    root = pathlib.Path(td)
    source = root / "clip.mp4"

    source.write_bytes(b"original-source-bytes")
    expect_error(
        lambda: build_tracking_timeline(
            source, backend=MutateDuringInspect(), permission_assertion="fixture"
        ),
        "byte mutation during extraction invalidates provenance",
    )

    source.write_bytes(b"original-source-bytes")
    expect_error(
        lambda: build_tracking_timeline(
            source, backend=ReplaceDuringExtract(), permission_assertion="fixture"
        ),
        "path replacement during extraction invalidates provenance",
    )

    source.write_bytes(b"original-source-bytes")
    stable = build_tracking_timeline(
        source, backend=StableBackend(), permission_assertion="fixture"
    )
    check(stable["source"]["bytes"] == len(b"original-source-bytes"),
          "stable source retains exact byte count")

schema = json.loads((ROOT / "docs/bodyrig/schemas/tracking.schema.json").read_text("utf-8"))
defs = schema["$defs"]
body_ids = set(defs["body_landmarks"]["propertyNames"]["enum"])
hand_ids = set(defs["hand_landmarks"]["propertyNames"]["enum"])
face_ids = set(defs["face_landmarks"]["propertyNames"]["enum"])
expression_ids = set(defs["expressions"]["propertyNames"]["enum"])

check("engine_joint_42" not in body_ids | hand_ids | face_ids,
      "schema rejects extractor-native landmark ids")
check("nose" in body_ids and "index_tip" not in body_ids,
      "body schema accepts only body ids")
check("index_tip" in hand_ids and "nose_tip" not in hand_ids,
      "hand schema accepts only hand ids")
check("nose_tip" in face_ids and "jaw_open" not in face_ids,
      "face schema accepts only face landmark ids")
check("jaw_open" in expression_ids and "nose_tip" not in expression_ids,
      "expression schema accepts only canonical coefficients")
check(defs["frame"]["properties"]["body"]["$ref"] == "#/$defs/body_landmarks"
      and defs["frame"]["properties"]["left_hand"]["$ref"] == "#/$defs/hand_landmarks",
      "frame schema uses subsystem-specific maps")

print(f"\n===== BODYRIG M1.1 TRACKING INTEGRITY: {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
