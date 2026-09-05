#!/usr/bin/env python3
"""The `.mrbody` ModelRig writes must be the one BodyRig specified.

Two repositories write and read the same container with different code:
BodyRig produces a real body from video, ModelRig validates it, stores it
and serves it to a renderer. Nothing has been holding them together except
that both were written from the same spec -- and a spec is not a test.

Verified 5/9/2026 against BodyRig commit 4c42aa04f23a69ad962aa14414b4e162167cabc5:
required payload, optional motion paths and manifest all agreed exactly. This
gate keeps that true. If it fails, the two sides have drifted and the first
real .mrbody would be rejected on the rig -- which is the worst place to find
out, because the video, the tracking run and the fit are already spent.

The schema is vendored at contracts/mrbody-manifest-v1.schema.json. When
BodyRig changes it, copy the new one in and let this gate say whether
ModelRig still complies. Validation is dependency-free on purpose: the
gate must run wherever the tests run.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from bodyrig.identity import build_identity_bundle  # noqa: E402
from bodyrig.mrbody import OPTIONAL_MOTION_PATHS, REQUIRED_PATHS, build_mrbody  # noqa: E402
from bodyrig_fixtures import png_fixture, tracking_fixture, vrm_fixture  # noqa: E402

SCHEMA = ROOT / "contracts" / "mrbody-manifest-v1.schema.json"
# From BodyRig docs/MRBODY_SPEC.md at the verified commit.
BODYRIG_REQUIRED = {
    "manifest.json", "checksums.json", "avatar.vrm",
    "bodyprint.json", "provenance.json", "thumbnail.png",
}
BODYRIG_MOTIONS = {
    "motions/idle.vrma", "motions/walk.vrma", "motions/talk.vrma",
    "motions/gesture_01.vrma", "motions/gesture_02.vrma", "motions/gesture_03.vrma",
}

passed = failed = 0


def check(condition: object, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def type_ok(value: object, spec: object) -> bool:
    names = spec if isinstance(spec, list) else [spec]
    kinds = {"string": str, "integer": int, "number": (int, float),
             "boolean": bool, "object": dict, "array": list, "null": type(None)}
    return any(isinstance(value, kinds[n]) for n in names if n in kinds)


def validate(instance: dict, schema: dict, path: str = "manifest") -> list[str]:
    """Enough of JSON Schema for this contract, and no dependency."""
    problems: list[str] = []
    for name in schema.get("required", []):
        if name not in instance:
            problems.append(f"{path}: missing required field {name!r}")
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        for name in instance:
            if name not in props:
                problems.append(f"{path}: field {name!r} is not allowed by the schema")
    for name, sub in props.items():
        if name not in instance:
            continue
        value = instance[name]
        if "type" in sub and not type_ok(value, sub["type"]):
            problems.append(f"{path}.{name}: expected {sub['type']}, got {type(value).__name__}")
        if "const" in sub and value != sub["const"]:
            problems.append(f"{path}.{name}: expected {sub['const']!r}, got {value!r}")
        if "enum" in sub and value not in sub["enum"]:
            problems.append(f"{path}.{name}: {value!r} not in {sub['enum']}")
        if isinstance(value, dict) and sub.get("type") == "object":
            problems.extend(validate(value, sub, f"{path}.{name}"))
    return problems


check(SCHEMA.exists(), "BodyRig's manifest schema is vendored")
schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

check(set(REQUIRED_PATHS) == BODYRIG_REQUIRED,
      f"required payload matches BodyRig's spec {sorted(set(REQUIRED_PATHS) ^ BODYRIG_REQUIRED) or ''}")
check(set(OPTIONAL_MOTION_PATHS) == BODYRIG_MOTIONS,
      f"optional motion paths match BodyRig's spec {sorted(set(OPTIONAL_MOTION_PATHS) ^ BODYRIG_MOTIONS) or ''}")

package = build_mrbody(
    build_identity_bundle(tracking_fixture()), display_name="Kaliv",
    avatar_vrm=vrm_fixture("cross-repo"), thumbnail_png=png_fixture(),
)
with zipfile.ZipFile(io.BytesIO(package)) as archive:
    names = set(archive.namelist())
    manifest = json.loads(archive.read("manifest.json"))

check(BODYRIG_REQUIRED <= names, "a built package carries every file BodyRig requires")
problems = validate(manifest, schema)
check(not problems, f"the manifest ModelRig writes validates against BodyRig's schema {problems or ''}")

# The validator must be able to fail, or the two checks above prove nothing.
check(validate({k: v for k, v in manifest.items() if k != "id"}, schema),
      "the validator rejects a manifest missing a required field")
check(validate({**manifest, "unexpected": 1}, schema),
      "the validator rejects a field the schema does not allow")
check(validate({**manifest, "name": 7}, schema),
      "the validator rejects a field of the wrong type")

print(f"\n===== MRBODY CROSS-REPO CONTRACT: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
