#!/usr/bin/env python3
"""Fail-closed auditor for A4-25f physical qualification evidence.

This auditor validates evidence produced by the isolated A4-25f physical harness.
It never authorizes production activation or a human GO decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "dk.ternedal.modelrig.a425f"
OUTPUT_MARKER_SCHEMA = "modelrig-agent4/a4-25f-output-root/v1"
FIXTURE_SCHEMA = "modelrig-agent4/a4-25f-physical-fixture/v1"
MUTATION_SCHEMA = "modelrig-agent4/a4-25f-physical-mutation/v1"
STATE_SCHEMA = "modelrig-agent4/a4-25f-operator-state/v1"
MATRIX_SCHEMA = "modelrig-agent4/a4-25f-physical-matrix/v1"
CURSOR_MATRIX_SCHEMA = "modelrig-agent4/a4-25f-cursor-matrix/v1"
CLEANUP_SCHEMA = "modelrig-agent4/a4-25f-cleanup/v1"
AUDIT_SCHEMA = "modelrig-agent4/a4-25f-physical-audit/v1"
EXPECTED_MUTATION_MODES = (
    "campaign-add",
    "campaign-delete",
    "campaign-transition",
    "evidence-append",
    "evidence-append",
)
EXPECTED_MAIN_STAGES = {
    "list-start",
    "list-continue",
    "detail-capture",
    "timeline-start",
    "timeline-continue",
    "evidence-start",
    "evidence-continue",
    "verification",
    "selected-root-404",
    "server-422",
    "current-unavailable-503",
    "fresh-root",
    "unknown-root",
    "expired-retained-410",
}
EXPECTED_CURSOR_STAGES = (
    "root-mismatch",
    "resource-mismatch",
    "filter-mismatch",
    "campaign-mismatch",
)
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_SECRET_KEYS = {
    "token",
    "bearer",
    "authorization",
    "admin_key",
    "pairing_code",
    "raw_cursor",
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"required A4-25f evidence file is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise RuntimeError(f"A4-25f evidence must be a JSON object: {path.name}")
    return value


def _require_bool(value: Any, expected: bool, label: str) -> None:
    if value is not expected:
        raise RuntimeError(f"{label} must be {str(expected).lower()}")


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise RuntimeError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _git_dirty() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"],
        text=True,
    ).strip()


def _require_exact_clean_head(expected_sha: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise ValueError("expected SHA must be 40 lowercase hexadecimal characters")
    actual = _git_head()
    if actual != expected_sha:
        raise RuntimeError(f"wrong checkout: expected {expected_sha}, got {actual}")
    if _git_dirty():
        raise RuntimeError("A4-25f evidence audit requires an exact clean checkout")


def _resolve_output(output_root: Path) -> Path:
    output = output_root.expanduser().resolve()
    try:
        output.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("A4-25f audit output must stay outside the repository")
    if output == Path(output.anchor):
        raise ValueError("A4-25f audit output must not be the filesystem root")
    return output


def _bound_file(output: Path, candidate: str | Path, expected_name: str | None = None) -> Path:
    path = Path(candidate)
    if not path.is_absolute():
        path = output / path
    path = path.resolve()
    try:
        path.relative_to(output)
    except ValueError as exc:
        raise RuntimeError(f"evidence path escapes A4-25f output: {path}") from exc
    if expected_name is not None and path.name != expected_name:
        raise RuntimeError(f"unexpected A4-25f evidence filename: {path.name}")
    return path


def _assert_no_secrets(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = key.lower()
            if normalized in FORBIDDEN_SECRET_KEYS:
                raise RuntimeError(f"forbidden secret field in {label}: {key}")
            _assert_no_secrets(nested, label)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_secrets(nested, label)
    elif isinstance(value, str) and re.search(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", value):
        raise RuntimeError(f"bearer credential-like value found in {label}")


def _verify_self_digest(value: dict[str, Any], field: str, label: str) -> None:
    claimed = _require_sha256(value.get(field), f"{label}.{field}")
    unsigned = dict(value)
    del unsigned[field]
    actual = "sha256:" + hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    if actual != claimed:
        raise RuntimeError(f"{label} self-digest mismatch")


def _verify_references(output: Path, directory: str, references: Any, label: str) -> list[Path]:
    if not isinstance(references, list) or not references:
        raise RuntimeError(f"{label} must contain at least one receipt reference")
    base = (output / directory).resolve()
    seen: set[str] = set()
    paths: list[Path] = []
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            raise RuntimeError(f"{label}[{index}] must be an object")
        name = reference.get("name")
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
            raise RuntimeError(f"{label}[{index}] has an unsafe filename")
        if name in seen:
            raise RuntimeError(f"{label} contains duplicate receipt {name}")
        seen.add(name)
        expected = _require_sha256(reference.get("sha256"), f"{label}[{index}].sha256")
        path = (base / name).resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise RuntimeError(f"{label} receipt escapes its directory") from exc
        if not path.is_file():
            raise RuntimeError(f"referenced receipt is missing: {name}")
        if _sha256_file(path) != expected:
            raise RuntimeError(f"referenced receipt hash mismatch: {name}")
        paths.append(path)
    return paths


def _validate_fixture(value: dict[str, Any], expected_sha: str) -> None:
    if value.get("schema") != FIXTURE_SCHEMA or value.get("repository_sha") != expected_sha:
        raise RuntimeError("fixture manifest authority mismatch")
    if value.get("root_parent_snapshot_id") is not None or value.get("root_sequence") != 1:
        raise RuntimeError("fixture manifest is not the A4-25f genesis root")
    if value.get("campaign_count") != 31:
        raise RuntimeError("fixture manifest campaign count drifted")
    for key in ("external_dispatch", "background_runtime", "api_mounted", "public_network", "production_activation"):
        _require_bool(value.get(key), False, f"fixture.{key}")
    _verify_self_digest(value, "manifest_sha256", "fixture")
    _assert_no_secrets(value, "fixture")


def _validate_mutation(value: dict[str, Any], expected_sha: str) -> None:
    if value.get("schema") != MUTATION_SCHEMA or value.get("repository_sha") != expected_sha:
        raise RuntimeError("mutation receipt authority mismatch")
    if value.get("pending_projections_after") != 0:
        raise RuntimeError("mutation receipt has pending projections")
    for key in ("external_dispatch", "background_runtime", "api_mounted", "public_network", "production_activation"):
        _require_bool(value.get(key), False, f"mutation.{key}")
    _verify_self_digest(value, "receipt_sha256", "mutation")
    _assert_no_secrets(value, "mutation")


def _validate_phone_receipt(value: dict[str, Any], label: str) -> None:
    _require_bool(value.get("success"), True, f"{label}.success")
    _require_bool(value.get("credential_in_receipt"), False, f"{label}.credential_in_receipt")
    if "raw_cursor_in_receipt" in value:
        _require_bool(value.get("raw_cursor_in_receipt"), False, f"{label}.raw_cursor_in_receipt")
    _require_bool(value.get("production_activation"), False, f"{label}.production_activation")
    _assert_no_secrets(value, label)


def _validate_cleanup(value: dict[str, Any], expected_sha: str, serial_hash: str) -> None:
    if value.get("schema") != CLEANUP_SCHEMA or value.get("repository_sha") != expected_sha:
        raise RuntimeError("cleanup receipt authority mismatch")
    if value.get("package_name") != PACKAGE_NAME:
        raise RuntimeError("cleanup receipt package mismatch")
    for key in (
        "package_removed",
        "firewall_rule_removed",
        "reserved_ports_closed",
        "backend_device_store_removed",
        "backend_process_removed",
        "worker_process_removed",
        "physical_cleanup",
    ):
        _require_bool(value.get(key), True, f"cleanup.{key}")
    for key in ("credential_in_receipt", "public_network", "production_activation"):
        _require_bool(value.get(key), False, f"cleanup.{key}")
    if value.get("adb_serial_sha256") != serial_hash:
        raise RuntimeError("cleanup receipt belongs to a different Pixel")
    _assert_no_secrets(value, "cleanup")


def audit_evidence(output_root: Path, *, expected_sha: str) -> dict[str, Any]:
    _require_exact_clean_head(expected_sha)
    output = _resolve_output(output_root)

    marker = _load_json(output / ".modelrig-a4-25f-output.json")
    if marker.get("schema") != OUTPUT_MARKER_SCHEMA:
        raise RuntimeError("A4-25f output marker schema mismatch")
    _require_bool(marker.get("production_activation"), False, "output_marker.production_activation")
    _assert_no_secrets(marker, "output_marker")

    state_path = output / "a4-25f-operator-state.json"
    state = _load_json(state_path)
    if state.get("schema") != STATE_SCHEMA or state.get("expected_sha") != expected_sha:
        raise RuntimeError("operator state authority mismatch")
    if state.get("phase") != "stopped":
        raise RuntimeError("operator Stop must complete before A4-25f audit")
    if state.get("package_name") != PACKAGE_NAME:
        raise RuntimeError("operator state package mismatch")
    if int(state.get("backend_pid", -1)) != 0 or int(state.get("worker_pid", -1)) != 0:
        raise RuntimeError("operator state still records active harness processes")
    _require_bool(state.get("public_network"), False, "state.public_network")
    _require_bool(state.get("production_activation"), False, "state.production_activation")
    if Path(str(state.get("output_root", ""))).resolve() != output:
        raise RuntimeError("operator state output root mismatch")
    serial = state.get("adb_serial")
    if not isinstance(serial, str) or not serial:
        raise RuntimeError("operator state is missing the physical Pixel serial")
    serial_hash = _sha256_text(serial)
    _assert_no_secrets(state, "operator_state")

    fixture_path = output / "fixture-manifest.json"
    fixture = _load_json(fixture_path)
    _validate_fixture(fixture, expected_sha)

    matrix_path = _bound_file(
        output,
        str(state.get("matrix_receipt", "")),
        "a4-25f-physical-matrix.json",
    )
    matrix = _load_json(matrix_path)
    if matrix.get("schema") != MATRIX_SCHEMA or matrix.get("repository_sha") != expected_sha:
        raise RuntimeError("physical matrix authority mismatch")
    if matrix.get("package_name") != PACKAGE_NAME:
        raise RuntimeError("physical matrix package mismatch")
    if matrix.get("baseline_root") != fixture.get("root_snapshot_id"):
        raise RuntimeError("physical matrix baseline root does not match fixture genesis")
    if matrix.get("stage_count") != len(EXPECTED_MAIN_STAGES) or matrix.get("mutation_count") != len(EXPECTED_MUTATION_MODES):
        raise RuntimeError("physical matrix stage/mutation count drifted")
    for key in (
        "worker_restart_tested",
        "backend_restart_tested",
        "android_process_restart_tested",
        "expired_retained_root_tested",
        "selected_root_404_tested",
        "server_422_tested",
        "unavailable_503_tested",
        "physical_execution",
    ):
        _require_bool(matrix.get(key), True, f"matrix.{key}")
    for key in ("credential_in_receipt", "raw_cursor_in_receipt", "public_network", "production_activation"):
        _require_bool(matrix.get(key), False, f"matrix.{key}")
    _assert_no_secrets(matrix, "physical_matrix")

    mutation_paths = _verify_references(output, "mutations", matrix.get("mutation_receipts"), "matrix.mutation_receipts")
    if len(mutation_paths) != len(EXPECTED_MUTATION_MODES):
        raise RuntimeError("physical matrix must bind exactly five mutation receipts")
    mutations = [_load_json(path) for path in mutation_paths]
    for mutation in mutations:
        _validate_mutation(mutation, expected_sha)
    mutations.sort(key=lambda value: int(value.get("root_sequence_after", -1)))
    if tuple(value.get("mode") for value in mutations) != EXPECTED_MUTATION_MODES:
        raise RuntimeError("A4-25f mutation order drifted")
    previous_root = fixture.get("root_snapshot_id")
    previous_sequence = int(fixture.get("root_sequence", -1))
    for mutation in mutations:
        if mutation.get("root_before") != previous_root:
            raise RuntimeError("A4-25f mutation root chain is discontinuous")
        if mutation.get("root_after_parent") != previous_root:
            raise RuntimeError("A4-25f mutation parent root mismatch")
        if int(mutation.get("root_sequence_before", -1)) != previous_sequence:
            raise RuntimeError("A4-25f mutation before-sequence mismatch")
        if int(mutation.get("root_sequence_after", -1)) != previous_sequence + 1:
            raise RuntimeError("A4-25f mutation sequence is not contiguous")
        previous_root = mutation.get("root_after")
        previous_sequence += 1
    if matrix.get("retained_detail_root") != mutations[1].get("root_after"):
        raise RuntimeError("physical matrix retained detail root is not the post-delete root")
    if matrix.get("final_current_root") != previous_root:
        raise RuntimeError("physical matrix final current root does not close the mutation chain")

    phone_paths = _verify_references(output, "phone-receipts", matrix.get("phone_receipts"), "matrix.phone_receipts")
    phone_receipts = [_load_json(path) for path in phone_paths]
    for path, receipt in zip(phone_paths, phone_receipts):
        _validate_phone_receipt(receipt, path.name)
    main_stages = {str(receipt.get("stage")) for receipt in phone_receipts if isinstance(receipt.get("stage"), str)}
    if not EXPECTED_MAIN_STAGES.issubset(main_stages):
        missing = sorted(EXPECTED_MAIN_STAGES - main_stages)
        raise RuntimeError(f"physical matrix is missing phone stage receipts: {', '.join(missing)}")

    cursor_matrix_path = output / "a4-25f-cursor-matrix.json"
    cursor_matrix = _load_json(cursor_matrix_path)
    if cursor_matrix.get("schema") != CURSOR_MATRIX_SCHEMA or cursor_matrix.get("repository_sha") != expected_sha:
        raise RuntimeError("cursor matrix authority mismatch")
    if cursor_matrix.get("package_name") != PACKAGE_NAME:
        raise RuntimeError("cursor matrix package mismatch")
    if tuple(cursor_matrix.get("stages") or ()) != EXPECTED_CURSOR_STAGES or cursor_matrix.get("receipt_count") != len(EXPECTED_CURSOR_STAGES):
        raise RuntimeError("cursor matrix stage set drifted")
    if cursor_matrix.get("adb_serial_sha256") != serial_hash:
        raise RuntimeError("cursor matrix belongs to a different Pixel")
    for key in ("physical_execution",):
        _require_bool(cursor_matrix.get(key), True, f"cursor_matrix.{key}")
    for key in ("credential_in_receipt", "raw_cursor_in_receipt", "public_network", "production_activation"):
        _require_bool(cursor_matrix.get(key), False, f"cursor_matrix.{key}")
    _assert_no_secrets(cursor_matrix, "cursor_matrix")
    cursor_paths = _verify_references(output, "phone-receipts", cursor_matrix.get("receipts"), "cursor_matrix.receipts")
    cursor_receipts = [_load_json(path) for path in cursor_paths]
    if tuple(receipt.get("stage") for receipt in cursor_receipts) != EXPECTED_CURSOR_STAGES:
        raise RuntimeError("cursor receipts do not match cursor matrix order")
    for path, receipt in zip(cursor_paths, cursor_receipts):
        _validate_phone_receipt(receipt, path.name)
        _require_bool(receipt.get("local_rejection"), True, f"{path.name}.local_rejection")
        if receipt.get("error_kind") != "PROTOCOL":
            raise RuntimeError(f"{path.name} did not prove a local PROTOCOL rejection")

    cleanup_path = output / "a4-25f-cleanup.json"
    cleanup = _load_json(cleanup_path)
    _validate_cleanup(cleanup, expected_sha, serial_hash)

    receipt: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "audited_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository_sha": expected_sha,
        "package_name": PACKAGE_NAME,
        "fixture_manifest_sha256": _sha256_file(fixture_path),
        "physical_matrix_sha256": _sha256_file(matrix_path),
        "cursor_matrix_sha256": _sha256_file(cursor_matrix_path),
        "cleanup_sha256": _sha256_file(cleanup_path),
        "mutation_receipt_count": len(mutations),
        "main_phone_receipt_count": len(phone_receipts),
        "cursor_receipt_count": len(cursor_receipts),
        "root_chain_start": fixture.get("root_snapshot_id"),
        "root_chain_end": previous_root,
        "all_referenced_hashes_verified": True,
        "mutation_chain_verified": True,
        "main_matrix_verified": True,
        "cursor_matrix_verified": True,
        "cleanup_verified": True,
        "credentials_absent_from_evidence": True,
        "physical_qualification_evidence_valid": True,
        "human_go_authorized": False,
        "public_network": False,
        "production_activation": False,
    }
    receipt["audit_sha256"] = "sha256:" + hashlib.sha256(_canonical_json(receipt)).hexdigest()
    audit_path = output / "a4-25f-physical-audit.json"
    audit_path.write_text(
        json.dumps(receipt, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    audit_evidence(args.output_root, expected_sha=args.expected_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
