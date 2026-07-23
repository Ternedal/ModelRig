#!/usr/bin/env python3
"""Run and bind every Stage B verification step into one final receipt.

Stage B happens only after the exact Stage A SHA has been fast-forwarded, tagged
and published by a separate explicit decision. This command itself performs no
merge, tag, release, update, restart or activation. It verifies:

1. the published-release freeze;
2. semantic updater-chain evidence;
3. the seven-proof release campaign;
4. the physical browser attestation and existing eight-proof final gate.

Only the resulting ``kaliv-stage-b-physical-final/v1`` receipt represents the
fully hardened Stage B evidence bundle. ``production_activation`` is always false.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-stage-b-physical-final/v1"
CHAIN_SCHEMA = "kaliv-appliance-lifecycle-updater-chain/v1"
CAMPAIGN_SCHEMA = "kaliv-physical-validation-campaign/v1"
FINAL_SCHEMA = "kaliv-physical-validation-final/v1"
DEFAULT_LIFECYCLE = Path("validation/appliance-lifecycle-observations.json")
DEFAULT_CHAIN = Path("validation/appliance-lifecycle-updater-chain-latest.json")
DEFAULT_CAMPAIGN = Path("validation/physical-validation-campaign-latest.json")
DEFAULT_BROWSER = Path("validation/browser-peer-public-validation-physical-latest.json")
DEFAULT_COMPONENT_FINAL = Path("validation/physical-validation-final-latest.json")
DEFAULT_REPORT = Path("validation/stage-b-physical-final-latest.json")
MAX_BYTES = 32 * 1024 * 1024
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class StageBGateError(RuntimeError):
    """The Stage B evidence bundle is incomplete or inconsistent."""


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _resolve_under(root: Path, raw: Path) -> Path:
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise StageBGateError(f"path is a symlink: {raw}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise StageBGateError(f"path escapes repository: {raw}") from exc
    return resolved


def _load_json(root: Path, raw: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, raw)
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise StageBGateError(f"component report is missing or irregular: {raw}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_BYTES:
        raise StageBGateError(f"component report size is invalid: {raw}")
    body = path.read_bytes()
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageBGateError(f"component report is invalid UTF-8 JSON: {raw}") from exc
    if not isinstance(value, dict):
        raise StageBGateError(f"component report must be an object: {raw}")
    return value, body, path


def _load_candidate_identity(root: Path) -> dict[str, Any]:
    path = root / "scripts" / "physical_validation_campaign.py"
    spec = importlib.util.spec_from_file_location("stage_b_candidate_identity", path)
    if spec is None or spec.loader is None:
        raise StageBGateError("candidate identity module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    value = module.candidate_identity(root)
    if not isinstance(value, dict):
        raise StageBGateError("candidate identity is invalid")
    return value


def _candidate_matches(actual: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(actual, Mapping) and all(
        actual.get(key) == expected.get(key)
        for key in ("version", "git_sha", "code_sha256")
    )


def _run(label: str, args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        check=False,
    )
    return {"label": label, "command": args, "exit_code": int(result.returncode)}


def _component_meta(root: Path, raw: Path, value: Mapping[str, Any], body: bytes) -> dict[str, Any]:
    path = _resolve_under(root, raw)
    return {
        "path": str(path.relative_to(root.resolve())),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "schema": value.get("schema"),
    }


def evaluate_bundle(
    root: Path,
    *,
    candidate: Mapping[str, Any],
    chain_path: Path,
    campaign_path: Path,
    component_final_path: Path,
    steps: list[dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    for step in steps:
        if step.get("exit_code") != 0:
            errors.append(f"{step.get('label')} failed with exit code {step.get('exit_code')}")

    chain, chain_raw, _ = _load_json(root, chain_path)
    campaign, campaign_raw, _ = _load_json(root, campaign_path)
    final, final_raw, _ = _load_json(root, component_final_path)

    if chain.get("schema") != CHAIN_SCHEMA:
        errors.append("updater-chain schema mismatch")
    if chain.get("gate", {}).get("passed") is not True:
        errors.append("updater-chain gate.passed is not true")
    if chain.get("gate", {}).get("updater_chain_complete") is not True:
        errors.append("updater-chain is incomplete")
    if chain.get("gate", {}).get("production_activation") is not False:
        errors.append("updater-chain did not preserve production_activation=false")

    if campaign.get("schema") != CAMPAIGN_SCHEMA:
        errors.append("release campaign schema mismatch")
    if campaign.get("mode") != "verify":
        errors.append("release campaign was not produced in verify mode")
    if campaign.get("gate", {}).get("passed") is not True:
        errors.append("release campaign gate.passed is not true")
    if campaign.get("gate", {}).get("physical_campaign_complete") is not True:
        errors.append("seven-proof release campaign is incomplete")
    if campaign.get("gate", {}).get("production_activation") is not False:
        errors.append("release campaign did not preserve production_activation=false")
    if campaign.get("summary", {}).get("total") != 7:
        errors.append("release campaign summary.total is not seven")

    if final.get("schema") != FINAL_SCHEMA:
        errors.append("component final-gate schema mismatch")
    final_gate = final.get("gate") if isinstance(final.get("gate"), Mapping) else {}
    if final_gate.get("passed") is not True:
        errors.append("component final gate.passed is not true")
    if final_gate.get("all_physical_evidence_complete") is not True:
        errors.append("component final gate is not physically complete")
    if final_gate.get("production_activation") is not False:
        errors.append("component final gate did not preserve production_activation=false")
    if final.get("summary", {}).get("total") != 8:
        errors.append("component final summary.total is not eight")

    for label, value in (
        ("updater-chain", chain),
        ("release campaign", campaign),
        ("component final", final),
    ):
        if not _candidate_matches(value.get("candidate"), candidate):
            errors.append(f"{label} candidate identity mismatch")

    if candidate.get("identity_source") == "git" and candidate.get("working_tree_clean") is not True:
        errors.append("current release checkout is not clean")
    if candidate.get("version_stamps_consistent") is not True:
        errors.append("current release version stamps are inconsistent")
    if _SHA40.fullmatch(str(candidate.get("git_sha") or "")) is None:
        errors.append("current release Git SHA is invalid")
    if _SHA64.fullmatch(str(candidate.get("code_sha256") or "")) is None:
        errors.append("current release worker fingerprint is invalid")

    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "candidate": dict(candidate),
        "steps": steps,
        "evidence": {
            "updater_chain": _component_meta(root, chain_path, chain, chain_raw),
            "physical_campaign": _component_meta(root, campaign_path, campaign, campaign_raw),
            "component_final_gate": _component_meta(
                root, component_final_path, final, final_raw
            ),
        },
        "summary": {
            "total": 8,
            "passed": final.get("summary", {}).get("passed", []),
            "errors": errors,
        },
        "gate": {
            "passed": not errors,
            "release_freeze_complete": not errors,
            "updater_chain_complete": not errors,
            "physical_campaign_complete": not errors,
            "browser_peer_physical_complete": not errors,
            "all_physical_evidence_complete": not errors,
            "production_activation": False,
        },
    }
    return report, 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle-report", type=Path, default=DEFAULT_LIFECYCLE)
    parser.add_argument("--chain-report", type=Path, default=DEFAULT_CHAIN)
    parser.add_argument("--campaign-report", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--browser-attestation", type=Path, default=DEFAULT_BROWSER)
    parser.add_argument("--component-final-report", type=Path, default=DEFAULT_COMPONENT_FINAL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    parser.add_argument("--min-model-exact", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.max_age_hours > 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    if not 0 <= args.min_model_exact <= 1:
        parser.error("--min-model-exact must be between 0 and 1")

    now = datetime.now(timezone.utc)
    steps: list[dict[str, Any]] = []
    report: dict[str, Any]
    exit_code = 2
    try:
        steps.append(_run("release freeze", [sys.executable, str(ROOT / "scripts" / "freeze_check.py")]))
        if steps[-1]["exit_code"] == 0:
            steps.append(
                _run(
                    "updater-chain gate",
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "appliance_lifecycle_updater_chain.py"),
                        "--lifecycle-report",
                        str(args.lifecycle_report),
                        "--report",
                        str(args.chain_report),
                    ],
                )
            )
        if steps[-1]["exit_code"] == 0:
            steps.append(
                _run(
                    "seven-proof release campaign",
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "physical_validation_campaign.py"),
                        "--mode",
                        "verify",
                        "--lifecycle-report",
                        str(args.lifecycle_report),
                        "--max-age-hours",
                        str(args.max_age_hours),
                        "--min-model-exact",
                        str(args.min_model_exact),
                        "--report",
                        str(args.campaign_report),
                    ],
                )
            )
        if steps[-1]["exit_code"] == 0:
            steps.append(
                _run(
                    "eight-proof component final gate",
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "physical_validation_final_gate.py"),
                        "--campaign-report",
                        str(args.campaign_report),
                        "--browser-attestation",
                        str(args.browser_attestation),
                        "--max-age-hours",
                        str(args.max_age_hours),
                        "--report",
                        str(args.component_final_report),
                    ],
                )
            )

        if any(step["exit_code"] != 0 for step in steps):
            raise StageBGateError("Stage B component sequence stopped safely")
        candidate = _load_candidate_identity(ROOT)
        report, exit_code = evaluate_bundle(
            ROOT,
            candidate=candidate,
            chain_path=args.chain_report,
            campaign_path=args.campaign_report,
            component_final_path=args.component_final_report,
            steps=steps,
            now=now,
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "steps": steps,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
            "summary": {"total": 8, "passed": [], "errors": [str(exc)[:500]]},
            "gate": {
                "passed": False,
                "release_freeze_complete": False,
                "updater_chain_complete": False,
                "physical_campaign_complete": False,
                "browser_peer_physical_complete": False,
                "all_physical_evidence_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2

    destination = _resolve_under(ROOT, args.report)
    try:
        destination.relative_to((ROOT / "validation").resolve())
    except ValueError:
        parser.error("--report must remain under validation/")
    _write_json_atomic(destination, report)
    print(f"report: {destination.relative_to(ROOT)}")
    print("gate: " + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
