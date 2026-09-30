#!/usr/bin/env python3
"""Validate BodyRig's canonical final Photoreal M6 release for Kaliv.

The BodyRig artifact is production-activating inside BodyRig. This bridge only
verifies it and emits a bounded release evidence ref; it never activates Kaliv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

VERDICT_SCHEMA = "kaliv-system/bodyrig-photoreal-verdict/v1"
BODYRIG_FORMAT = "bodyrig-digital-twin-photoreal-release"
BODYRIG_POLICY = "bodyrig-digital-twin-photoreal-release-v1"
VISUAL_AUTHORITY = "photoreal-v2-p3"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^dtphotorel-[0-9a-f]{32}$")

TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "release_id",
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyrig_revision",
    "canonical_m6_release_id",
    "canonical_m6_release_file_sha256",
    "canonical_m6_release_content_sha256",
    "photoreal_m5_link_id",
    "photoreal_m5_link_file_sha256",
    "photoreal_m5_link_content_sha256",
    "m4_photoreal_link_id",
    "windows_realization_sha256",
    "quest_realization_sha256",
    "visual_authority",
    "state",
    "canonical_digital_twin_ready",
    "photoreal_digital_twin_ready",
    "finalized_utc",
    "production_activation",
}

RELEASE_ID_FIELDS = (
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyrig_revision",
    "canonical_m6_release_id",
    "canonical_m6_release_file_sha256",
    "canonical_m6_release_content_sha256",
    "photoreal_m5_link_id",
    "photoreal_m5_link_file_sha256",
    "photoreal_m5_link_content_sha256",
    "m4_photoreal_link_id",
    "windows_realization_sha256",
    "quest_realization_sha256",
    "visual_authority",
)


class BodyRigPhotorealQualificationError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BodyRigPhotorealQualificationError(f"{name} must be an object")
    return value


def _sha40(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise BodyRigPhotorealQualificationError(
            f"{name} must be a lowercase 40-hex Git SHA"
        )
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise BodyRigPhotorealQualificationError(
            f"{name} must be a lowercase SHA-256"
        )
    return value


def _v1(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1


def _release_id(authority: Mapping[str, Any]) -> str:
    evidence = {key: authority[key] for key in RELEASE_ID_FIELDS}
    return "dtphotorel-" + hashlib.sha256(_canonical(evidence)).hexdigest()[:32]


def qualify(authority: Mapping[str, Any], *, expected_bodyrig_sha: str) -> dict[str, Any]:
    expected = _sha40(expected_bodyrig_sha, "expected BodyRig SHA")
    value = _mapping(authority, "BodyRig Photoreal M6 authority")

    if set(value) != TOP_FIELDS:
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal M6 fields are not canonical"
        )
    if (
        value["format"] != BODYRIG_FORMAT
        or not _v1(value["version"])
        or value["policy_revision"] != BODYRIG_POLICY
    ):
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal M6 format/version/policy mismatch"
        )

    revision = _sha40(value["bodyrig_revision"], "BodyRig Photoreal bodyrig_revision")
    if revision != expected:
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal authority is bound to a different BodyRig Git SHA"
        )

    for field in (
        "assembly_fingerprint",
        "body_package_sha256",
        "canonical_m6_release_file_sha256",
        "canonical_m6_release_content_sha256",
        "photoreal_m5_link_file_sha256",
        "photoreal_m5_link_content_sha256",
        "windows_realization_sha256",
        "quest_realization_sha256",
    ):
        _sha256(value[field], f"BodyRig Photoreal {field}")

    if value["visual_authority"] != VISUAL_AUTHORITY:
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal visual authority is not canonical"
        )
    if value["state"] != "released":
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal state must be released"
        )
    if value["canonical_digital_twin_ready"] is not True:
        raise BodyRigPhotorealQualificationError(
            "canonical_digital_twin_ready must be true"
        )
    if value["photoreal_digital_twin_ready"] is not True:
        raise BodyRigPhotorealQualificationError(
            "photoreal_digital_twin_ready must be true"
        )
    if value["production_activation"] is not True:
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal production_activation must be true"
        )
    if (
        not isinstance(value["finalized_utc"], str)
        or not value["finalized_utc"].endswith("Z")
    ):
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal finalized_utc must be a UTC Z timestamp"
        )

    release_id = value["release_id"]
    if (
        not isinstance(release_id, str)
        or _RELEASE_ID.fullmatch(release_id) is None
        or release_id != _release_id(value)
    ):
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal release_id does not match exact evidence"
        )

    digest = hashlib.sha256(_canonical(dict(value))).hexdigest()
    return {
        "schema": VERDICT_SCHEMA,
        "state": "QUALIFIED",
        "bodyrig_photoreal_likeness_gate_satisfied": True,
        "bodyrig_revision": revision,
        "bodyrig_photoreal_release_id": release_id,
        "bodyrig_photoreal_authority_sha256": digest,
        "release_evidence_ref": f"bodyrig-photoreal-likeness:{revision}:{digest}",
        "release_gate_satisfied": False,
        "production_activation": False,
    }


def load(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal authority file cannot be read"
        ) from exc
    if len(raw) > 1024 * 1024:
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal authority file is too large"
        )
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BodyRigPhotorealQualificationError(
            "BodyRig Photoreal authority file is not valid UTF-8 JSON"
        ) from exc
    return _mapping(parsed, "BodyRig Photoreal authority")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("authority", type=Path)
    parser.add_argument("--bodyrig-sha", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        verdict = qualify(load(args.authority), expected_bodyrig_sha=args.bodyrig_sha)
        code = 0
    except BodyRigPhotorealQualificationError as exc:
        verdict = {
            "schema": VERDICT_SCHEMA,
            "state": "INVALID",
            "bodyrig_photoreal_likeness_gate_satisfied": False,
            "release_gate_satisfied": False,
            "production_activation": False,
            "error": str(exc),
        }
        code = 2

    rendered = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
