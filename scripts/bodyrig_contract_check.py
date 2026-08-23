#!/usr/bin/env python3
"""Self-contained contract checks for the ModelRig <-> BodyRig V1 boundary.

The repository intentionally does not depend on a JSON Schema runtime package for
these documentation/contract checks.  This file implements only the Draft 2020-12
keywords used by the BodyRig schemas and exercises representative positive and
negative fixtures.  A real BodyRig importer must use a full schema validator in
addition to ZIP/path/checksum safety checks.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "bodyrig"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load_schema(name: str) -> dict[str, Any]:
    path = CONTRACTS / name
    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda token: (_ for _ in ()).throw(
            ContractError(f"non-finite JSON constant in {name}: {token}")
        ),
    )
    require(isinstance(value, dict), f"{name} is not a JSON object")
    require(
        value.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
        f"{name} does not declare Draft 2020-12",
    )
    require(isinstance(value.get("$id"), str), f"{name} lacks $id")
    return value


def resolve_ref(root: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    require(reference.startswith("#/$defs/"), f"unsupported local ref: {reference}")
    name = reference.removeprefix("#/$defs/")
    defs = root.get("$defs")
    require(isinstance(defs, Mapping) and name in defs, f"missing $defs ref: {name}")
    target = defs[name]
    require(isinstance(target, Mapping), f"invalid $defs target: {name}")
    return target


def validate(schema: Mapping[str, Any], value: Any, *, root: Mapping[str, Any], path: str = "$") -> None:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        validate(resolve_ref(root, reference), value, root=root, path=path)
        return

    if "const" in schema:
        require(value == schema["const"], f"{path}: const mismatch")
    if "enum" in schema:
        enum = schema["enum"]
        require(isinstance(enum, list) and value in enum, f"{path}: enum mismatch")

    schema_type = schema.get("type")
    if schema_type == "object":
        require(isinstance(value, dict), f"{path}: expected object")
    elif schema_type == "array":
        require(isinstance(value, list), f"{path}: expected array")
    elif schema_type == "string":
        require(isinstance(value, str), f"{path}: expected string")
    elif schema_type == "integer":
        require(type(value) is int, f"{path}: expected integer")
    elif schema_type == "number":
        require(type(value) in {int, float} and math.isfinite(float(value)), f"{path}: expected finite number")

    if isinstance(value, dict):
        required = schema.get("required", [])
        require(isinstance(required, list), f"{path}: malformed required")
        for name in required:
            require(name in value, f"{path}: missing required property {name}")

        minimum = schema.get("minProperties")
        maximum = schema.get("maxProperties")
        if isinstance(minimum, int):
            require(len(value) >= minimum, f"{path}: too few properties")
        if isinstance(maximum, int):
            require(len(value) <= maximum, f"{path}: too many properties")

        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        require(isinstance(properties, Mapping), f"{path}: malformed properties")
        require(isinstance(patterns, Mapping), f"{path}: malformed patternProperties")
        for name, child in value.items():
            matched = False
            if name in properties:
                child_schema = properties[name]
                require(isinstance(child_schema, Mapping), f"{path}.{name}: malformed schema")
                validate(child_schema, child, root=root, path=f"{path}.{name}")
                matched = True
            for expression, child_schema in patterns.items():
                if re.search(str(expression), name):
                    require(isinstance(child_schema, Mapping), f"{path}.{name}: malformed pattern schema")
                    validate(child_schema, child, root=root, path=f"{path}.{name}")
                    matched = True
            if schema.get("additionalProperties") is False:
                require(matched, f"{path}: unexpected property {name}")

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int):
            require(len(value) >= minimum, f"{path}: too few items")
        if isinstance(maximum, int):
            require(len(value) <= maximum, f"{path}: too many items")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, child in enumerate(value):
                validate(item_schema, child, root=root, path=f"{path}[{index}]")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int):
            require(len(value) >= minimum, f"{path}: string too short")
        if isinstance(maximum, int):
            require(len(value) <= maximum, f"{path}: string too long")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            require(re.search(pattern, value) is not None, f"{path}: pattern mismatch")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ContractError(f"{path}: invalid date-time") from exc
            require(parsed.tzinfo is not None, f"{path}: date-time needs timezone")

    if type(value) in {int, float}:
        numeric = float(value)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        if type(minimum) in {int, float}:
            require(numeric >= float(minimum), f"{path}: below minimum")
        if type(maximum) in {int, float}:
            require(numeric <= float(maximum), f"{path}: above maximum")
        if type(exclusive_minimum) in {int, float}:
            require(numeric > float(exclusive_minimum), f"{path}: below exclusiveMinimum")

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        matches = 0
        for candidate in any_of:
            try:
                validate(candidate, value, root=root, path=path)
            except ContractError:
                continue
            matches += 1
        require(matches >= 1, f"{path}: anyOf did not match")

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        matches = 0
        for candidate in one_of:
            try:
                validate(candidate, value, root=root, path=path)
            except ContractError:
                continue
            matches += 1
        require(matches == 1, f"{path}: oneOf matched {matches} branches")


def passes(schema: Mapping[str, Any], value: Any) -> bool:
    try:
        validate(schema, value, root=schema)
    except ContractError:
        return False
    return True


def main() -> int:
    cue = load_schema("body-cue-v1.schema.json")
    bodyprint = load_schema("bodyprint-v1.schema.json")
    manifest = load_schema("mrbody-manifest-v1.schema.json")
    checksums = load_schema("checksums-v1.schema.json")
    provenance = load_schema("provenance-v1.schema.json")

    require(
        passes(
            cue,
            {
                "type": "modelrig-body-cue",
                "version": 1,
                "utterance_id": "u-01JABC",
                "emotion": "thoughtful",
                "intensity": 0.35,
                "gesture": "small_shrug",
                "gaze": "user",
            },
        ),
        "valid semantic BodyCue was rejected",
    )
    require(
        not passes(cue, {"type": "modelrig-body-cue", "version": 1, "utterance_id": "u-01"}),
        "empty BodyCue unexpectedly passed",
    )

    require(
        passes(bodyprint, {"format": "modelrig-bodyprint", "version": 1, "shape": {"shoulder_to_height": 0.24}}),
        "valid partial observed bodyprint was rejected",
    )
    require(
        not passes(bodyprint, {"format": "modelrig-bodyprint", "version": 1}),
        "empty bodyprint unexpectedly passed",
    )
    require(
        not passes(bodyprint, {"format": "modelrig-bodyprint", "version": 1, "shape": {}}),
        "empty bodyprint section unexpectedly passed",
    )

    valid_manifest = {
        "format": "modelrig-body",
        "format_version": 1,
        "id": "anders-body-12345678",
        "name": "Anders",
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": "0.1.0"},
    }
    require(passes(manifest, valid_manifest), "valid mrbody manifest was rejected")
    forged_manifest = dict(valid_manifest)
    forged_manifest["plugin"] = "run-me.dll"
    require(not passes(manifest, forged_manifest), "manifest accepted executable extension field")

    digest = "1" * 64
    valid_checksums = {
        "avatar.vrm": digest,
        "bodyprint.json": digest,
        "provenance.json": digest,
        "thumbnail.png": digest,
        "motions/talk.vrma": digest,
    }
    require(passes(checksums, valid_checksums), "valid checksum map was rejected")
    forged_checksums = dict(valid_checksums)
    forged_checksums["scripts/start.ps1"] = digest
    require(not passes(checksums, forged_checksums), "checksum map accepted unknown payload path")
    uppercase = dict(valid_checksums)
    uppercase["avatar.vrm"] = "A" * 64
    require(not passes(checksums, uppercase), "checksum map accepted non-canonical SHA-256")

    valid_provenance = {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": "2026-08-23T12:00:00Z",
        "source": {"kind": "user-supplied-local-media", "count": 3},
        "synthetic_avatar": True,
        "pipeline": [{"stage": "body-recovery", "adapter": "hmr2", "revision": "abc123"}],
    }
    require(passes(provenance, valid_provenance), "valid provenance was rejected")
    private_source = json.loads(json.dumps(valid_provenance))
    private_source["source"]["filename"] = "private-video.mp4"
    require(not passes(provenance, private_source), "provenance accepted private source filename")
    zero_source = json.loads(json.dumps(valid_provenance))
    zero_source["source"]["count"] = 0
    require(not passes(provenance, zero_source), "provenance accepted zero source media")

    spec = (ROOT / "docs" / "MRBODY_SPEC.md").read_text(encoding="utf-8")
    for required_path in (
        "manifest.json",
        "checksums.json",
        "avatar.vrm",
        "bodyprint.json",
        "provenance.json",
        "thumbnail.png",
    ):
        require(required_path in spec, f"MRBODY spec lost required path {required_path}")
    require("duplicate entries" in spec, "MRBODY spec lost duplicate-entry rejection")
    require("path traversal" in spec, "MRBODY spec lost traversal rejection")
    require("Atomic replacement" in spec, "MRBODY spec lost atomic replacement rule")

    print("BodyRig V1 contract checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
