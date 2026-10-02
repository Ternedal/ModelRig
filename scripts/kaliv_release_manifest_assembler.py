#!/usr/bin/env python3
"""Assemble a fully-qualified Kaliv release manifest from canonical evidence refs.

This is an operator convenience layer only. It creates no evidence, grants no
authority and cannot activate production. The assembled manifest is accepted
only if the existing kaliv_system_release_gate evaluates it as release-ready.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import kaliv_system_release_gate as release_gate

_SHA40 = re.compile(r"^[0-9a-f]{40}$")

GATE_ARGUMENTS = (
    ("software_exact_green", "software-exact-green-ref"),
    ("consciousness_live_lifecycle", "consciousness-live-lifecycle-ref"),
    ("visionrig_physical_perception", "visionrig-physical-perception-ref"),
    ("voicerig_physical_acceptance", "voicerig-physical-acceptance-ref"),
    ("bodyrig_photoreal_likeness", "bodyrig-photoreal-likeness-ref"),
    ("bodyrig_digital_twin_m6", "bodyrig-digital-twin-m6-ref"),
    ("bodyrig_android_live_body", "bodyrig-android-live-body-ref"),
    ("end_to_end_latency", "end-to-end-latency-ref"),
    ("recovery_soak", "recovery-soak-ref"),
    ("repository_authority", "repository-authority-ref"),
)


class ReleaseManifestAssemblyError(RuntimeError):
    pass


def _sha(value: str, name: str) -> str:
    if _SHA40.fullmatch(value) is None:
        raise ReleaseManifestAssemblyError(
            f"{name} must be a lowercase 40-hex Git SHA"
        )
    return value


def _ref(value: str, name: str) -> str:
    ref = value.strip()
    if not ref or len(ref) > 512:
        raise ReleaseManifestAssemblyError(
            f"{name} must be a bounded nonblank canonical evidence ref"
        )
    return ref


def assemble(
    *,
    release_id: str,
    modelrig_sha: str,
    bodyrig_sha: str,
    visionrig_sha: str,
    voicerig_sha: str,
    evidence_refs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_gates = set(release_gate.REQUIRED_GATES)
    if set(evidence_refs) != expected_gates:
        missing = sorted(expected_gates - set(evidence_refs))
        extra = sorted(set(evidence_refs) - expected_gates)
        parts: list[str] = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if extra:
            parts.append("unknown " + ", ".join(extra))
        raise ReleaseManifestAssemblyError(
            "evidence refs do not match required gates: " + "; ".join(parts)
        )

    repositories = [
        {"repository": "Ternedal/ModelRig", "git_sha": _sha(modelrig_sha, "ModelRig SHA")},
        {"repository": "Ternedal/BodyRig", "git_sha": _sha(bodyrig_sha, "BodyRig SHA")},
        {"repository": "Ternedal/VisionRig", "git_sha": _sha(visionrig_sha, "VisionRig SHA")},
        {"repository": "Ternedal/VoiceRig", "git_sha": _sha(voicerig_sha, "VoiceRig SHA")},
    ]
    gates = {
        gate: {
            "status": "PASS",
            "evidence_refs": [_ref(evidence_refs[gate], f"{gate} evidence ref")],
        }
        for gate in release_gate.REQUIRED_GATES
    }
    manifest: dict[str, Any] = {
        "schema": release_gate.SCHEMA,
        "release_id": release_id,
        "repositories": repositories,
        "gates": gates,
        "production_activation": False,
    }

    try:
        verdict = release_gate.evaluate_manifest(manifest)
    except release_gate.SystemReleaseManifestError as exc:
        raise ReleaseManifestAssemblyError(
            f"assembled manifest was rejected by the final release gate: {exc}"
        ) from exc

    verdict_doc = verdict.as_dict()
    if verdict.release_ready is not True or verdict.state != "QUALIFIED":
        raise ReleaseManifestAssemblyError(
            "assembled manifest did not reach QUALIFIED/release_ready=true"
        )
    if verdict.production_activation is not False:
        raise ReleaseManifestAssemblyError(
            "final release gate overclaimed production activation"
        )
    return manifest, verdict_doc


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--modelrig-sha", required=True)
    parser.add_argument("--bodyrig-sha", required=True)
    parser.add_argument("--visionrig-sha", required=True)
    parser.add_argument("--voicerig-sha", required=True)
    for _gate, arg in GATE_ARGUMENTS:
        parser.add_argument(f"--{arg}", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verdict", type=Path)
    args = parser.parse_args(argv)

    evidence_refs = {
        gate: getattr(args, arg.replace("-", "_"))
        for gate, arg in GATE_ARGUMENTS
    }
    try:
        manifest, verdict = assemble(
            release_id=args.release_id,
            modelrig_sha=args.modelrig_sha,
            bodyrig_sha=args.bodyrig_sha,
            visionrig_sha=args.visionrig_sha,
            voicerig_sha=args.voicerig_sha,
            evidence_refs=evidence_refs,
        )
    except ReleaseManifestAssemblyError as exc:
        print(json.dumps({
            "schema": "kaliv-system-release-manifest-assembly/v1",
            "state": "INVALID",
            "production_activation": False,
            "error": str(exc),
        }))
        return 2

    _write_json(args.manifest, manifest)
    if args.verdict:
        _write_json(args.verdict, verdict)
    print(json.dumps({
        "schema": "kaliv-system-release-manifest-assembly/v1",
        "state": "QUALIFIED",
        "release_id": manifest["release_id"],
        "manifest": str(args.manifest),
        "verdict": str(args.verdict) if args.verdict else None,
        "production_activation": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
