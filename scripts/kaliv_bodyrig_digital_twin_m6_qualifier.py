#!/usr/bin/env python3
"""Validate canonical BodyRig M6 digital-twin release authority for Kaliv.

This bridge is deliberately read-only. It accepts only BodyRig's canonical M6
authority schema, binds it to an exact BodyRig Git SHA, and emits a ModelRig
release-evidence reference. It does not activate ModelRig/Kaliv production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "kaliv-system/bodyrig-digital-twin-m6-evidence/v1"
VERDICT_SCHEMA = "kaliv-system/bodyrig-digital-twin-m6-verdict/v1"
BODYRIG_FORMAT = "bodyrig-digital-twin-release"
BODYRIG_POLICY = "bodyrig-digital-twin-release-v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^dtrelease-[0-9a-f]{32}$")

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
    "bodyprint_sha256",
    "bodyrig_revision",
    "composition_authority_id",
    "composition_authority_sha256",
    "composition_authority_content_sha256",
    "gate_a_sha256",
    "body_physical_release_sha256",
    "windows_platform_input_sha256",
    "windows_realization_sha256",
    "windows_renderer_attestation_sha256",
    "quest_platform_input_sha256",
    "quest_realization_sha256",
    "quest_renderer_attestation_sha256",
    "finalized_utc",
    "state",
    "digital_twin_ready",
    "production_activation",
}

RELEASE_ID_FIELDS = (
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyprint_sha256",
    "bodyrig_revision",
    "composition_authority_id",
    "composition_authority_sha256",
    "composition_authority_content_sha256",
    "gate_a_sha256",
    "body_physical_release_sha256",
    "windows_platform_input_sha256",
    "windows_realization_sha256",
    "windows_renderer_attestation_sha256",
    "quest_platform_input_sha256",
    "quest_realization_sha256",
    "quest_renderer_attestation_sha256",
)


class BodyRigM6QualificationError(RuntimeError):
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
        raise BodyRigM6QualificationError(f"{name} must be an object")
    return value


def _sha40(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise BodyRigM6QualificationError(
            f"{name} must be a lowercase 40-hex Git SHA"
        )
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise BodyRigM6QualificationError(
            f"{name} must be a lowercase SHA-256"
        )
    return value


def _v1(value: Any) -> bool:
    return not isinstance(value, bool) and value == 1


def _release_id(authority: Mapping[str, Any]) -> str:
    evidence = {key: authority[key] for key in RELEASE_ID_FIELDS}
    return "dtrelease-" + hashlib.sha256(_canonical(evidence)).hexdigest()[:32]


def qualify(authority: Mapping[str, Any], *, expected_bodyrig_sha: str) -> dict[str, Any]:
    expected = _sha40(expected_bodyrig_sha, "expected BodyRig SHA")
    value = _mapping(authority, "BodyRig M6 authority")

    if set(value) != TOP_FIELDS:
        missing = sorted(TOP_FIELDS - set(value))
        extra = sorted(set(value) - TOP_FIELDS)
        detail: list[str] = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise BodyRigM6QualificationError(
            "BodyRig M6 authority fields are not canonical"
            + (": " + "; ".join(detail) if detail else "")
        )

    if (
        value["format"] != BODYRIG_FORMAT
        or not _v1(value["version"])
        or value["policy_revision"] != BODYRIG_POLICY
    ):
        raise BodyRigM6QualificationError(
            "BodyRig M6 format/version/policy mismatch"
        )

    revision = _sha40(value["bodyrig_revision"], "BodyRig M6 bodyrig_revision")
    if revision != expected:
        raise BodyRigM6QualificationError(
            "BodyRig M6 authority is bound to a different BodyRig Git SHA"
        )

    for field in (
        "person_id",
        "person_revision",
        "body_revision",
        "body_id",
        "composition_authority_id",
    ):
        if not isinstance(value[field], str) or not value[field].strip():
            raise BodyRigM6QualificationError(
                f"BodyRig M6 {field} is invalid"
            )

    for field in TOP_FIELDS:
        if field.endswith("_sha256"):
            _sha256(value[field], f"BodyRig M6 {field}")

    release_id = value["release_id"]
    if (
        not isinstance(release_id, str)
        or _RELEASE_ID.fullmatch(release_id) is None
        or release_id != _release_id(value)
    ):
        raise BodyRigM6QualificationError(
            "BodyRig M6 release_id does not match canonical bound evidence"
        )

    if (
        not isinstance(value["finalized_utc"], str)
        or not value["finalized_utc"].endswith("Z")
    ):
        raise BodyRigM6QualificationError(
            "BodyRig M6 finalized_utc must be a UTC Z timestamp"
        )
    if value["state"] != "released":
        raise BodyRigM6QualificationError("BodyRig M6 state must be released")
    if value["digital_twin_ready"] is not True:
        raise BodyRigM6QualificationError(
            "BodyRig M6 digital_twin_ready must be true"
        )
    # BodyRig's own canonical M6 is the activating BodyRig authority. ModelRig
    # validates that fact but never inherits the authority to activate Kaliv.
    if value["production_activation"] is not True:
        raise BodyRigM6QualificationError(
            "BodyRig M6 production_activation must be true"
        )

    authority_digest = hashlib.sha256(_canonical(dict(value))).hexdigest()
    return {
        "schema": VERDICT_SCHEMA,
        "state": "QUALIFIED",
        "bodyrig_digital_twin_m6_gate_satisfied": True,
        "bodyrig_revision": revision,
        "bodyrig_release_id": release_id,
        "bodyrig_authority_sha256": authority_digest,
        "release_evidence_ref": (
            f"bodyrig-digital-twin-m6:{revision}:{authority_digest}"
        ),
        "release_gate_satisfied": False,
        "production_activation": False,
    }


def load(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BodyRigM6QualificationError(
            "BodyRig M6 authority file cannot be read"
        ) from exc
    if len(raw) > 1024 * 1024:
        raise BodyRigM6QualificationError("BodyRig M6 authority file is too large")
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BodyRigM6QualificationError(
            "BodyRig M6 authority file is not valid UTF-8 JSON"
        ) from exc
    return _mapping(parsed, "BodyRig M6 authority")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("authority", type=Path)
    parser.add_argument("--bodyrig-sha", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        verdict = qualify(load(args.authority), expected_bodyrig_sha=args.bodyrig_sha)
        code = 0
    except BodyRigM6QualificationError as exc:
        verdict = {
            "schema": VERDICT_SCHEMA,
            "state": "INVALID",
            "bodyrig_digital_twin_m6_gate_satisfied": False,
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
