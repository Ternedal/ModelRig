#!/usr/bin/env python3
"""Validate VoiceRig's final physical release acceptance for Kaliv.

VoiceRig owns the physical voice acceptance process. This bridge validates the
content-bound PASS report against the exact pinned VoiceRig revision and emits a
canonical cross-repository release evidence ref. It never activates production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

VERDICT_SCHEMA = "kaliv-system/voicerig-physical-verdict/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class VoiceRigPhysicalQualificationError(RuntimeError):
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
        raise VoiceRigPhysicalQualificationError(f"{name} must be an object")
    return value


def _sha40(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise VoiceRigPhysicalQualificationError(
            f"{name} must be a lowercase 40-hex Git SHA"
        )
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VoiceRigPhysicalQualificationError(
            f"{name} must be a lowercase SHA-256"
        )
    return value


def _artifact(value: Any, name: str, *, validated: bool) -> None:
    item = _mapping(value, name)
    if item.get("exists") is not True:
        raise VoiceRigPhysicalQualificationError(f"{name} must exist")
    _sha256(item.get("sha256"), f"{name}.sha256")
    if validated and item.get("validated") is not True:
        raise VoiceRigPhysicalQualificationError(f"{name} must be revalidated")


def qualify(acceptance: Mapping[str, Any], *, expected_voicerig_sha: str) -> dict[str, Any]:
    expected = _sha40(expected_voicerig_sha, "expected VoiceRig SHA")
    value = _mapping(acceptance, "VoiceRig release acceptance")

    if value.get("ok") is not True or value.get("stage") != "release-ready":
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig release acceptance is not a release-ready PASS"
        )
    blockers = value.get("blockers")
    if not isinstance(blockers, list) or blockers:
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig release acceptance contains blockers"
        )

    source = _mapping(value.get("source"), "VoiceRig source")
    if source.get("available") is not True or source.get("dirty") is not False:
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig acceptance source must be available and clean"
        )
    revision = _sha40(source.get("revision"), "VoiceRig source revision")
    if revision != expected:
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig release acceptance is bound to a different VoiceRig Git SHA"
        )
    if not isinstance(source.get("root"), str) or not source["root"].strip():
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig acceptance source root must be nonblank"
        )

    quality = _mapping(value.get("quality"), "VoiceRig quality")
    if quality.get("pass") is not True:
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig manual listening quality did not PASS"
        )
    if not isinstance(quality.get("note"), str) or not quality["note"].strip():
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig manual listening quality note is missing"
        )

    fallback = _mapping(value.get("fallback"), "VoiceRig fallback")
    if (
        fallback.get("before_provider") != "voicerig"
        or fallback.get("provider") != "piper"
        or fallback.get("restored_provider") != "voicerig"
    ):
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig/Piper fallback and restore evidence is incomplete"
        )
    if (
        not isinstance(fallback.get("before_package"), str)
        or not fallback["before_package"].strip()
        or fallback.get("restored_package") != fallback.get("before_package")
    ):
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig fallback did not restore the exact accepted package"
        )

    artifacts = _mapping(value.get("artifacts"), "VoiceRig artifacts")
    for name in ("package", "reference_wav", "validation_wav", "piper_fallback_wav"):
        _artifact(artifacts.get(name), f"VoiceRig {name}", validated=True)
    for name in ("validation_report", "fallback_report"):
        item = _mapping(artifacts.get(name), f"VoiceRig {name}")
        _sha256(item.get("sha256"), f"VoiceRig {name}.sha256")
        if not isinstance(item.get("bytes"), int) or isinstance(item.get("bytes"), bool) or item["bytes"] <= 0:
            raise VoiceRigPhysicalQualificationError(
                f"VoiceRig {name}.bytes must be a positive integer"
            )

    digest = hashlib.sha256(_canonical(dict(value))).hexdigest()
    return {
        "schema": VERDICT_SCHEMA,
        "state": "QUALIFIED",
        "voicerig_physical_acceptance_gate_satisfied": True,
        "voicerig_revision": revision,
        "voicerig_acceptance_sha256": digest,
        "release_evidence_ref": f"voicerig-physical-acceptance:{revision}:{digest}",
        "release_gate_satisfied": False,
        "production_activation": False,
    }


def load(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig release acceptance file cannot be read"
        ) from exc
    if len(raw) > 1024 * 1024:
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig release acceptance file is too large"
        )
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VoiceRigPhysicalQualificationError(
            "VoiceRig release acceptance file is not valid UTF-8 JSON"
        ) from exc
    return _mapping(parsed, "VoiceRig release acceptance")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("acceptance", type=Path)
    parser.add_argument("--voicerig-sha", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        verdict = qualify(load(args.acceptance), expected_voicerig_sha=args.voicerig_sha)
        code = 0
    except VoiceRigPhysicalQualificationError as exc:
        verdict = {
            "schema": VERDICT_SCHEMA,
            "state": "INVALID",
            "voicerig_physical_acceptance_gate_satisfied": False,
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
