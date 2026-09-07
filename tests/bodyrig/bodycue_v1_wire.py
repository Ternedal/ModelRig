#!/usr/bin/env python3
"""Dependency-free #704 contract for the production BodyCue v1 boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "worker"))

from bodyrig.body_cue import (  # noqa: E402
    BodyCueError,
    build_body_cue,
    expression_plan_from_body_cue,
    validate_body_cue,
)
from app import body_cues  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_error(fn, message: str) -> None:
    try:
        fn()
    except BodyCueError:
        check(True, message)
    except Exception as exc:
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, message)
    else:
        check(False, message)


schema = json.loads((ROOT / "contracts" / "bodyrig" / "body-cue-v1.schema.json").read_text(encoding="utf-8"))
check(schema["additionalProperties"] is False, "public BodyCue schema is fail-closed on unknown fields")
check(schema["properties"]["type"]["const"] == "modelrig-body-cue"
      and schema["properties"]["version"]["const"] == 1,
      "public schema pins BodyCue type + version 1")
check(set(schema["required"]) == {"type", "version", "utterance_id"},
      "utterance_id remains mandatory public authority")

cue = build_body_cue(
    utterance_id="voice-abc-2",
    body_id="bodyid-0123456789abcdef01234567",
    emotion="neutral",
    intensity=0.6,
    energy=0.5,
    gesture="explain",
    gaze="neutral",
    duration_ms=420,
)
check(validate_body_cue(cue) == cue, "canonical emitted BodyCue round-trips executable validation")
check(set(cue).issubset(set(schema["properties"])), "runtime emitter uses only public v1 schema fields")
check(set(cue).isdisjoint({"bone", "bones", "joint", "joints", "transform", "transforms", "rotation"}),
      "BodyCue semantic wire contains no engine/bone/joint transform fields")
plan = expression_plan_from_body_cue(cue, state="speaking")
check(plan["gesture"] == {"intent": "explain", "intensity": 0.6}
      and plan["emotion"] is None and plan["gaze"] is None,
      "BodyRig adapter translates semantics only after v1 validation")

bad = dict(cue)
bad["joint_rotation"] = [0, 1, 0]
expect_error(lambda: validate_body_cue(bad), "unknown joint/engine field fails closed")
bad = dict(cue)
bad["version"] = 2
expect_error(lambda: validate_body_cue(bad), "unknown BodyCue version fails closed")
bad = dict(cue)
bad["utterance_id"] = "bad utterance with spaces"
expect_error(lambda: validate_body_cue(bad), "malformed utterance authority fails closed")
bad = dict(cue)
bad["duration_ms"] = True
expect_error(lambda: validate_body_cue(bad), "boolean cannot masquerade as duration integer")
bad = dict(cue)
bad["posture"] = "upright"
check(validate_body_cue(bad)["posture"] == "upright", "posture remains valid in the public v1 schema")
expect_error(lambda: expression_plan_from_body_cue(bad, state="speaking"),
             "schema-valid posture fails closed until runtime realization exists")

previous = os.environ.get(body_cues.CUES_ENV)
os.environ[body_cues.CUES_ENV] = "1"
try:
    check(body_cues.cue_for_state(state="thinking", utterance_id=None,
                                  body_id="bodyid-0123456789abcdef01234567") is None,
          "state policy never fabricates an utterance_id")
    spoken = body_cues.cue_for_speech(
        sentence="forklaring " * 8,
        utterance_id="voice-turn-3",
        body_id="bodyid-0123456789abcdef01234567",
        duration_ms=500,
    )
    check(spoken is not None and spoken["utterance_id"] == "voice-turn-3"
          and spoken["gesture"] == "explain",
          "speech policy emits canonical cue with exact VoiceRig utterance authority")
finally:
    if previous is None:
        os.environ.pop(body_cues.CUES_ENV, None)
    else:
        os.environ[body_cues.CUES_ENV] = previous

print(f"\nBodyCue v1 production boundary: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
