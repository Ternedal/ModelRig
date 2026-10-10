#!/usr/bin/env python3
"""Read-only inventory of source reports referenced by a Kaliv V1 manifest.

IMPORTANT: byte/hash/ref consistency is not producer authenticity or physical
release authority. This tool NEVER emits release_ready=true or a gate PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import kaliv_system_release_gate as release_gate

SCHEMA = "kaliv-system/producer-file-index/v1"
RESULT_SCHEMA = "kaliv-system/producer-file-inventory/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_INDEX_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
EXPECTED_PRODUCER_SCHEMAS = {
    "software_exact_green": "kaliv-system/software-exact-green-verdict/v1",
    "consciousness_live_lifecycle": "kaliv-consciousness-core/live-lifecycle-verdict/v1",
    "visionrig_physical_perception": "visionrig/physical-perception-qualification/v2",
    "voicerig_physical_acceptance": "kaliv-system/voicerig-physical-verdict/v1",
    "bodyrig_photoreal_likeness": "kaliv-system/bodyrig-photoreal-verdict/v1",
    "bodyrig_digital_twin_m6": "kaliv-system/bodyrig-digital-twin-m6-verdict/v1",
    "bodyrig_android_live_body": "modelrig.kaliv-body.android-physical-gate/v1",
    "end_to_end_latency": "kaliv-system/end-to-end-latency-verdict/v2",
    "recovery_soak": "kaliv-recovery-soak-qualification/v1",
    "repository_authority": "kaliv-system/repository-authority-verdict/v1",
}
REQUIRED_SUCCESS_MARKERS = {
    "software_exact_green": ("software_exact_green_gate_satisfied", True),
    "consciousness_live_lifecycle": ("consciousness_live_lifecycle_gate_satisfied", True),
    "voicerig_physical_acceptance": ("voicerig_physical_acceptance_gate_satisfied", True),
    "bodyrig_photoreal_likeness": ("bodyrig_photoreal_likeness_gate_satisfied", True),
    "bodyrig_digital_twin_m6": ("bodyrig_digital_twin_m6_gate_satisfied", True),
    "end_to_end_latency": ("end_to_end_latency_gate_satisfied", True),
    "recovery_soak": ("qualified", True),
    "repository_authority": ("repository_authority_gate_satisfied", True),
    "bodyrig_android_live_body": ("status", "pass"),
}
REQUIRED_VERDICT_STATES = {
    "software_exact_green": "QUALIFIED",
    "consciousness_live_lifecycle": "QUALIFIED",
    "voicerig_physical_acceptance": "QUALIFIED",
    "bodyrig_photoreal_likeness": "QUALIFIED",
    "bodyrig_digital_twin_m6": "QUALIFIED",
    "end_to_end_latency": "MEASURED",
    "repository_authority": "QUALIFIED",
}
# Source-verdict identity fields, as emitted by the frozen V1 qualifiers.
# These are untrusted claims until the independent producer is authenticated.
REPORT_REVISION_FIELDS = {
    "consciousness_live_lifecycle": ("candidate_git_sha", "Ternedal/ModelRig"),
    "voicerig_physical_acceptance": ("voicerig_revision", "Ternedal/VoiceRig"),
    "bodyrig_photoreal_likeness": ("bodyrig_revision", "Ternedal/BodyRig"),
    "bodyrig_digital_twin_m6": ("bodyrig_revision", "Ternedal/BodyRig"),
    "bodyrig_android_live_body": ("exact_head", "Ternedal/ModelRig"),
    "end_to_end_latency": ("candidate_git_sha", "Ternedal/ModelRig"),
    "recovery_soak": ("candidate_sha", "Ternedal/ModelRig"),
}


class InventoryError(ValueError):
    pass


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise InventoryError("duplicate JSON field")
        out[key] = value
    return out


def _json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(InventoryError("non-finite JSON")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise InventoryError(f"{label} must be a JSON object")
    return value


def _bounded_file(path: Path, limit: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise InventoryError(f"{label} must be a regular non-symlink file")
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise InventoryError(f"{label} cannot be read") from exc
    if len(raw) > limit:
        raise InventoryError(f"{label} exceeds size limit")
    return raw


def _report_path(root: Path, text: str) -> Path:
    if not isinstance(text, str) or not text or len(text) > 240 or "\\" in text:
        raise InventoryError("report path must be a bounded POSIX relative path")
    rel = Path(text)
    if rel.is_absolute() or any(part in (".", "..") for part in text.split("/")):
        raise InventoryError("report path must not be absolute or escaped")
    if rel.suffix != ".json":
        raise InventoryError("report path must name a JSON file")
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise InventoryError("report path contains a symlink")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise InventoryError("report path escaped evidence root")
    return candidate


def inventory(manifest: dict[str, Any], index: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        structural = release_gate.evaluate_manifest(manifest)
    except release_gate.SystemReleaseManifestError as exc:
        raise InventoryError(f"invalid release manifest: {exc}") from exc

    if set(index) != {"schema", "entries"} or index["schema"] != SCHEMA:
        raise InventoryError("invalid producer file index schema/fields")
    entries = index["entries"]
    if not isinstance(entries, list) or len(entries) > len(release_gate.REQUIRED_GATES):
        raise InventoryError("invalid producer file index entries")
    lookup: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"gate", "report_path", "sha256"}:
            raise InventoryError("invalid producer index entry")
        gate = entry["gate"]
        if not isinstance(gate, str) or gate not in release_gate.REQUIRED_GATES or gate in lookup:
            raise InventoryError("duplicate or unknown indexed gate")
        if not isinstance(entry["sha256"], str) or not _SHA256.fullmatch(entry["sha256"]):
            raise InventoryError("invalid indexed report SHA-256")
        lookup[gate] = entry
    requested = {
        gate for gate in release_gate.REQUIRED_GATES
        if manifest["gates"][gate]["status"] == "PASS"
    }
    if set(lookup) != requested:
        raise InventoryError("indexed reports must match exactly the declared PASS gates")

    pins = structural.pinned_repositories
    required_pins = {repo: pins[repo] for repo in release_gate.REQUIRED_REPOSITORIES}

    observed: list[dict[str, str]] = []
    for gate in release_gate.REQUIRED_GATES:
        if gate not in requested:
            continue
        entry = lookup[gate]
        path = _report_path(root, entry["report_path"])
        raw = _bounded_file(path, MAX_REPORT_BYTES, f"{gate} source report")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry["sha256"]:
            raise InventoryError(f"{gate} report bytes do not match indexed SHA-256")
        report = _json_bytes(raw, f"{gate} source report")
        if report.get("schema") != EXPECTED_PRODUCER_SCHEMAS[gate]:
            raise InventoryError(f"{gate} source report schema mismatch")
        # VisionRig carries the mandatory false activation flag inside its
        # nested gate, but any *additional* top-level true/unknown assertion
        # must also be rejected as contradictory authority.
        if ("production_activation" in report
                and report["production_activation"] is not False):
            raise InventoryError(f"{gate} source report overclaims production authority")
        if gate in ("software_exact_green", "repository_authority"):
            records = report.get("repositories")
            if not isinstance(records, list) or len(records) != 4:
                raise InventoryError(f"{gate} producer repository identity set is invalid")
            try:
                source_pins = {
                    item["repository"]: item["git_sha"] for item in records
                    if isinstance(item, dict)
                }
            except (KeyError, TypeError) as exc:
                raise InventoryError(f"{gate} producer repository identities malformed") from exc
            if len(source_pins) != 4 or source_pins != required_pins:
                raise InventoryError(f"{gate} producer repository revisions do not match manifest pins")
        if gate in REPORT_REVISION_FIELDS:
            field, repository = REPORT_REVISION_FIELDS[gate]
            if report.get(field) != pins[repository]:
                raise InventoryError(f"{gate} producer source revision differs from manifest pin")
        if gate == "visionrig_physical_perception":
            identity = report.get("visionrig")
            if not isinstance(identity, dict) or identity.get("service_revision") != pins["Ternedal/VisionRig"]:
                raise InventoryError("VisionRig source revision differs from manifest pin")
            physical_gate = report.get("gate")
            if (not isinstance(physical_gate, dict)
                    or physical_gate.get("passed") is not True
                    or physical_gate.get("physical_perception_qualified") is not True
                    or physical_gate.get("production_activation") is not False):
                raise InventoryError("VisionRig report lacks successful non-activating physical gate")
        elif report.get("production_activation") is not False:
            raise InventoryError(f"{gate} source report overclaims production authority")
        if ("release_gate_satisfied" in report
                and report["release_gate_satisfied"] is not False):
            raise InventoryError(f"{gate} source report overclaims system release authority")
        # A claimed status is not physical provenance. Reject explicit failure.
        if report.get("state") in ("INVALID", "FAILED", "BLOCKED"):
            raise InventoryError(f"{gate} source report is not successful")
        if report.get("status") in ("fail", "failed", "error"):
            raise InventoryError(f"{gate} source report is not successful")
        if report.get("qualified") is False:
            raise InventoryError(f"{gate} source report is not qualified")
        report_ref = report.get("release_evidence_ref", report.get("evidence_ref"))
        expected_ref = manifest["gates"][gate]["evidence_refs"][0]
        if report_ref != expected_ref:
            raise InventoryError(f"{gate} report ref differs from manifest ref")
        # Recompute *self-contained verdict* hashes where the actual producer
        # defines them that way. This is tamper detection, NOT source identity
        # or proof of a real sensor, physical acceptance or human review.
        if gate in {
            "software_exact_green", "repository_authority",
            "consciousness_live_lifecycle", "end_to_end_latency",
            "visionrig_physical_perception", "bodyrig_android_live_body",
        }:
            key = "evidence_ref" if gate == "bodyrig_android_live_body" else "release_evidence_ref"
            if key not in report:
                raise InventoryError(f"{gate} canonical source ref field missing")
            unsigned = dict(report)
            unsigned.pop(key)
            canonical = json.dumps(
                unsigned, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True, allow_nan=False,
            ).encode("utf-8")
            expected_digest = hashlib.sha256(canonical).hexdigest()
            if not expected_ref.endswith(":" + expected_digest):
                raise InventoryError(f"{gate} source verdict self-digest mismatch")
        if gate in REQUIRED_SUCCESS_MARKERS:
            marker, expected = REQUIRED_SUCCESS_MARKERS[gate]
            if report.get(marker) is not expected and report.get(marker) != expected:
                raise InventoryError(f"{gate} source report lacks a successful producer marker")
            # Avoid treating int(1) or string("true") as a true boolean.
            if expected is True and report.get(marker) is not True:
                raise InventoryError(f"{gate} source marker must be boolean true")
        if gate in REQUIRED_VERDICT_STATES:
            if report.get("state") != REQUIRED_VERDICT_STATES[gate]:
                raise InventoryError(f"{gate} source verdict state is not qualified")
        observed.append({
            "gate": gate,
            "report_path": entry["report_path"],
            "report_sha256": digest,
            "report_schema": report["schema"],
        })

    # No possible execution path produces release_ready=true. The operator
    # must verify source generation, human review and provenance separately.
    return {
        "schema": RESULT_SCHEMA,
        "state": "SOURCE_FILES_ACCOUNTED_FOR",
        "declared_pass_gates": len(observed),
        "pending_gates": list(structural.pending_gates),
        "failed_gates": list(structural.failed_gates),
        "files": observed,
        "producer_authenticity_proven": False,
        "physical_acceptance_proven": False,
        "release_gate_satisfied": False,
        "release_ready": False,
        "production_activation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.evidence_root.resolve(strict=True)
        if not root.is_dir():
            raise InventoryError("evidence root is not a directory")
        manifest = _json_bytes(
            _bounded_file(args.manifest, MAX_INDEX_BYTES, "manifest"), "manifest"
        )
        index = _json_bytes(
            _bounded_file(args.index, MAX_INDEX_BYTES, "index"), "index"
        )
        output = inventory(manifest, index, root)
    except (InventoryError, OSError) as exc:
        print(json.dumps({
            "schema": RESULT_SCHEMA, "state": "INVALID", "error": str(exc),
            "producer_authenticity_proven": False,
            "physical_acceptance_proven": False,
            "release_gate_satisfied": False, "release_ready": False,
            "production_activation": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
