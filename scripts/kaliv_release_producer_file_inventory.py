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
        if not isinstance(report.get("schema"), str) or not report["schema"]:
            raise InventoryError(f"{gate} report schema missing")
        if report.get("production_activation") is not False:
            raise InventoryError(f"{gate} source report overclaims production authority")
        if report.get("release_gate_satisfied") is True:
            raise InventoryError(f"{gate} source report overclaims system release authority")
        report_ref = report.get("release_evidence_ref", report.get("evidence_ref"))
        expected_ref = manifest["gates"][gate]["evidence_refs"][0]
        if report_ref != expected_ref:
            raise InventoryError(f"{gate} report ref differs from manifest ref")
        # A claimed status is not physical provenance. Reject explicit failure.
        if report.get("state") in ("INVALID", "FAILED", "BLOCKED"):
            raise InventoryError(f"{gate} source report is not successful")
        if report.get("status") in ("fail", "failed", "error"):
            raise InventoryError(f"{gate} source report is not successful")
        if report.get("qualified") is False:
            raise InventoryError(f"{gate} source report is not qualified")
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
