#!/usr/bin/env python3
"""Record and validate reusable proof-campaign gate receipts.

This is a narrow adapter around :mod:`proof_scope`, not a second carry-forward
mechanism.  A prior gate may count only when its receipt is green, its source
artifact (when one exists) is still byte-identical, its measurement
configuration still matches, and ``scope_unchanged(...)`` returns exactly
``True``. ``False`` and ``None`` both mean re-run.

Expected reuse refusals are printed as JSON on stdout.  Windows PowerShell 5.1
runs the campaign with ``$ErrorActionPreference='Stop'``; stderr on an expected
refusal could otherwise become a terminating ``NativeCommandError``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import proof_scope  # noqa: E402

SCHEMA = "modelrig-proof-gate-receipt/v1"
MAX_JSON_BYTES = 32 * 1024 * 1024
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

RECEIPTS = {
    "stage_a": Path("validation/proof-gates/stage-a-latest.json"),
    "forced_recovery": Path("validation/proof-gates/forced-recovery-latest.json"),
    "workflows": Path("validation/proof-gates/workflows-latest.json"),
    "t023": Path("validation/proof-gates/t023-latest.json"),
    "t033": Path("validation/proof-gates/t033-latest.json"),
}

SOURCES: dict[str, Path | None] = {
    "stage_a": Path("validation/physical-validation-candidate-final-latest.json"),
    "forced_recovery": None,
    "workflows": Path("validation/workflow-proof-latest.json"),
    "t023": Path("validation/agent3-termination-ui-physical-latest.json"),
    "t033": Path("validation/agent3-memory-protected-backup-physical-latest.json"),
}

T033_MAX_AGE_HOURS = 24.0


class ReceiptError(RuntimeError):
    pass


def _json_out(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _under_root(path: Path) -> Path:
    unresolved = path if path.is_absolute() else ROOT / path
    if unresolved.is_symlink():
        raise ReceiptError(f"path is a symlink: {path}")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ReceiptError(f"path escapes repository: {path}") from exc
    return resolved


def _load_json(path: Path) -> tuple[dict[str, Any], bytes, Path]:
    resolved = _under_root(path)
    if not resolved.is_file() or resolved.is_symlink():
        raise ReceiptError(f"JSON evidence is missing or irregular: {path}")
    raw = resolved.read_bytes()
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise ReceiptError(f"JSON evidence size is invalid: {path}")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"JSON evidence is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise ReceiptError(f"JSON evidence is not an object: {path}")
    return value, raw, resolved


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    resolved = _under_root(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=resolved.parent,
        prefix=resolved.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, resolved)


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _git_commit_exists(sha: str) -> bool:
    if SHA40.fullmatch(sha) is None:
        return False
    result = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "commit"


def _configuration(
    gate: str,
    *,
    planner_model: str | None,
    workflow_rounds: int | None,
    workflow_threshold: float | None,
) -> dict[str, Any]:
    if gate == "stage_a":
        planner = (planner_model or "").strip()
        if not planner:
            raise ReceiptError("Stage A receipt requires planner_model")
        return {"planner_model": planner}
    if gate == "workflows":
        planner = (planner_model or "").strip()
        if not planner:
            raise ReceiptError("workflow receipt requires planner_model")
        if isinstance(workflow_rounds, bool) or not isinstance(workflow_rounds, int) or workflow_rounds <= 0:
            raise ReceiptError("workflow receipt requires positive workflow_rounds")
        if isinstance(workflow_threshold, bool) or not isinstance(workflow_threshold, (int, float)):
            raise ReceiptError("workflow receipt requires workflow_threshold")
        threshold = float(workflow_threshold)
        if threshold < 0.0 or threshold > 1.0:
            raise ReceiptError("workflow_threshold must be between 0 and 1")
        return {
            "planner_model": planner,
            "workflow_rounds": workflow_rounds,
            "workflow_threshold": threshold,
        }
    return {}


def _require_t033_fresh(report: dict[str, Any], now: datetime) -> None:
    observed = _parse_time(report.get("generated_at"))
    if observed is None:
        raise ReceiptError("T-033 source generated_at is invalid")
    age = (now - observed).total_seconds() / 3600.0
    if age < -0.25:
        raise ReceiptError("T-033 source generated_at is in the future")
    if age > T033_MAX_AGE_HOURS:
        raise ReceiptError(
            f"T-033 physical evidence is {age:.1f}h old; max is {T033_MAX_AGE_HOURS:.1f}h"
        )


def _source_verdict(
    gate: str,
    report: dict[str, Any],
    expected_sha: str,
    configuration: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Recheck the producer-level verdict before a source can back a receipt."""
    if gate == "stage_a":
        if report.get("schema") != "kaliv-physical-validation-candidate-final/v1":
            raise ReceiptError("Stage A final report schema mismatch")
        if _nested(report, "gate", "passed") is not True:
            raise ReceiptError("Stage A final report is not PASS")
        if _nested(report, "gate", "production_activation") is not False:
            raise ReceiptError("Stage A final report moved production activation")
        actual_sha = _nested(report, "candidate", "git_sha")
    elif gate == "workflows":
        if report.get("schema") != "modelrig-workflow-proof/v1":
            raise ReceiptError("workflow aggregate schema mismatch")
        if report.get("passed") is not True:
            raise ReceiptError("workflow aggregate is not PASS")
        rounds = report.get("rounds")
        executions = report.get("executions")
        failures = report.get("runner_failures")
        mean = report.get("mean_completion_rate")
        threshold = report.get("threshold")
        planner = report.get("planner_model")
        if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds <= 0:
            raise ReceiptError("workflow rounds are invalid")
        if executions != rounds * 14:
            raise ReceiptError("workflow execution count does not match measured rounds")
        if failures != 0:
            raise ReceiptError("workflow aggregate contains runner failures")
        if not isinstance(mean, (int, float)) or not isinstance(threshold, (int, float)):
            raise ReceiptError("workflow aggregate mean/threshold is invalid")
        if float(mean) < float(threshold):
            raise ReceiptError("workflow aggregate is below threshold")
        if not isinstance(planner, str) or not planner.strip():
            raise ReceiptError("workflow aggregate planner_model is missing")
        if configuration:
            if rounds != configuration.get("workflow_rounds"):
                raise ReceiptError("workflow rounds differ from requested configuration")
            if abs(float(threshold) - float(configuration.get("workflow_threshold"))) > 1e-12:
                raise ReceiptError("workflow threshold differs from requested configuration")
            if planner != configuration.get("planner_model"):
                raise ReceiptError("workflow planner differs from requested configuration")
        actual_sha = report.get("sha")
    elif gate == "t023":
        if report.get("schema") != "kaliv-agent3-termination-ui-physical/v1":
            raise ReceiptError("T-023 report schema mismatch")
        if report.get("success") is not True:
            raise ReceiptError("T-023 report is not PASS")
        if report.get("production_activation") is not False:
            raise ReceiptError("T-023 report moved production activation")
        actual_sha = _nested(report, "candidate", "git_sha")
    elif gate == "t033":
        if report.get("schema") != "kaliv-agent3-memory-protected-backup-physical/v1":
            raise ReceiptError("T-033 report schema mismatch")
        if report.get("success") is not True:
            raise ReceiptError("T-033 report is not PASS")
        if report.get("production_activation") is not False:
            raise ReceiptError("T-033 report moved production activation")
        _require_t033_fresh(report, now)
        actual_sha = _nested(report, "candidate", "git_sha")
    else:
        raise ReceiptError(f"gate has no source validator: {gate}")
    if actual_sha != expected_sha:
        raise ReceiptError(
            f"{gate} source candidate mismatch: expected {expected_sha}, got {actual_sha}"
        )


def _source_metadata(
    gate: str,
    sha: str,
    configuration: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    source = SOURCES[gate]
    if source is None:
        return None
    report, raw, resolved = _load_json(source)
    _source_verdict(gate, report, sha, configuration, now=now)
    metadata: dict[str, Any] = {
        "path": str(resolved.relative_to(ROOT.resolve())).replace("\\", "/"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
    if gate == "t033":
        metadata["generated_at"] = report.get("generated_at")
    return metadata


def record(
    gate: str,
    sha: str,
    version: str,
    *,
    planner_model: str | None = None,
    workflow_rounds: int | None = None,
    workflow_threshold: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if gate not in RECEIPTS:
        raise ReceiptError(f"unknown gate: {gate}")
    if not _git_commit_exists(sha):
        raise ReceiptError("taken_on_sha is not a local Git commit")
    observed_now = now or datetime.now(timezone.utc)
    configuration = _configuration(
        gate,
        planner_model=planner_model,
        workflow_rounds=workflow_rounds,
        workflow_threshold=workflow_threshold,
    )
    source = _source_metadata(gate, sha, configuration, now=observed_now)
    receipt = {
        "schema": SCHEMA,
        "gate": gate,
        "generated_at": observed_now.isoformat().replace("+00:00", "Z"),
        "taken_on_sha": sha,
        "version": version,
        "configuration": configuration,
        "passed": True,
        "source": source,
        "production_activation": False,
    }
    _atomic_json(RECEIPTS[gate], receipt)
    return receipt


def validate(
    gate: str,
    head_sha: str,
    *,
    planner_model: str | None = None,
    workflow_rounds: int | None = None,
    workflow_threshold: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if gate not in RECEIPTS:
        raise ReceiptError(f"unknown gate: {gate}")
    if not _git_commit_exists(head_sha):
        raise ReceiptError("head_sha is not a local Git commit")
    observed_now = now or datetime.now(timezone.utc)
    expected_configuration = _configuration(
        gate,
        planner_model=planner_model,
        workflow_rounds=workflow_rounds,
        workflow_threshold=workflow_threshold,
    )
    receipt, _, receipt_path = _load_json(RECEIPTS[gate])
    if receipt.get("schema") != SCHEMA:
        raise ReceiptError("receipt schema mismatch")
    if receipt.get("gate") != gate:
        raise ReceiptError("receipt gate mismatch")
    if receipt.get("passed") is not True:
        raise ReceiptError("receipt is not PASS")
    if receipt.get("production_activation") is not False:
        raise ReceiptError("receipt moved production activation")
    if receipt.get("configuration") != expected_configuration:
        raise ReceiptError("receipt measurement configuration mismatch")
    taken_on = receipt.get("taken_on_sha")
    if not isinstance(taken_on, str) or not _git_commit_exists(taken_on):
        raise ReceiptError("receipt taken_on_sha is invalid or unavailable")

    source_meta = receipt.get("source")
    if SOURCES[gate] is None:
        if source_meta is not None:
            raise ReceiptError("source-less gate receipt unexpectedly names a source")
    else:
        if not isinstance(source_meta, dict):
            raise ReceiptError("receipt source metadata is missing")
        path_value = source_meta.get("path")
        digest = source_meta.get("sha256")
        size = source_meta.get("bytes")
        if not isinstance(path_value, str) or not path_value:
            raise ReceiptError("receipt source path is missing")
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise ReceiptError("receipt source digest is invalid")
        report, raw, source_path = _load_json(Path(path_value))
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ReceiptError("receipt source digest no longer matches")
        if size != len(raw):
            raise ReceiptError("receipt source byte count no longer matches")
        canonical = _under_root(SOURCES[gate])
        if source_path != canonical:
            raise ReceiptError("receipt source path is not the canonical gate source")
        _source_verdict(
            gate,
            report,
            taken_on,
            expected_configuration,
            now=observed_now,
        )

    try:
        unchanged = proof_scope.scope_unchanged(ROOT, gate, taken_on, head_sha)
    except Exception as exc:  # an unanswered scope question is never yes
        raise ReceiptError(f"scope check failed closed: {type(exc).__name__}") from exc
    if unchanged is not True:
        raise ReceiptError(f"scope cannot be reused: {unchanged!r}")

    return {
        "gate": gate,
        "passed": True,
        "reused": True,
        "taken_on_sha": taken_on,
        "head_sha": head_sha,
        "configuration": expected_configuration,
        "receipt": str(receipt_path.relative_to(ROOT.resolve())).replace("\\", "/"),
        "source": source_meta,
    }


def _add_configuration_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--planner-model")
    parser.add_argument("--workflow-rounds", type=int)
    parser.add_argument("--workflow-threshold", type=float)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    record_parser = sub.add_parser("record")
    record_parser.add_argument("--gate", choices=sorted(RECEIPTS), required=True)
    record_parser.add_argument("--sha", required=True)
    record_parser.add_argument("--version", required=True)
    _add_configuration_args(record_parser)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--gate", choices=sorted(RECEIPTS), required=True)
    validate_parser.add_argument("--head-sha", required=True)
    _add_configuration_args(validate_parser)

    args = parser.parse_args(argv)
    common = {
        "planner_model": args.planner_model,
        "workflow_rounds": args.workflow_rounds,
        "workflow_threshold": args.workflow_threshold,
    }
    try:
        if args.command == "record":
            result = record(args.gate, args.sha, args.version, **common)
        else:
            result = validate(args.gate, args.head_sha, **common)
    except Exception as exc:
        _json_out(
            {
                "passed": False,
                "error": type(exc).__name__,
                "detail": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            }
        )
        return 1
    _json_out(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
