#!/usr/bin/env python3
"""Authoritative Stage B final gate including strict source/bootstrap/interruption proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
STRICT_SCHEMA = "kaliv-stage-b-strict-evidence/v1"
FINAL_SCHEMA = "kaliv-stage-b-physical-final/v1"
DEFAULT_STRICT = Path("validation/stage-b-strict-evidence-latest.json")
DEFAULT_REPORT = Path("validation/stage-b-physical-final-latest.json")
MAX_BYTES = 32 * 1024 * 1024


class StageBV2Error(RuntimeError):
    pass


def _resolve(raw: Path) -> Path:
    path = raw if raw.is_absolute() else ROOT / raw
    if path.is_symlink():
        raise StageBV2Error(f"path is a symlink: {raw}")
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise StageBV2Error(f"path escapes repository: {raw}") from exc
    return resolved


def _load(raw: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve(raw)
    if not path.is_file() or path.is_symlink():
        raise StageBV2Error(f"report is missing or irregular: {raw}")
    body = path.read_bytes()
    if not body or len(body) > MAX_BYTES:
        raise StageBV2Error(f"report size is invalid: {raw}")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise StageBV2Error(f"report must be an object: {raw}")
    return value, body, path


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".",
        suffix=".tmp", delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _run(args: list[str], cwd: Path | None = None) -> int:
    return subprocess.run(
        args, cwd=cwd or ROOT, env=os.environ.copy(), check=False
    ).returncode


def _candidate_matches(left: Any, right: Any) -> bool:
    return isinstance(left, Mapping) and isinstance(right, Mapping) and all(
        left.get(key) == right.get(key) for key in ("version", "git_sha", "code_sha256")
    )


def _blocked_receipt(now: str, error: str, *, status: str = "blocked") -> dict[str, Any]:
    return {
        "schema": FINAL_SCHEMA,
        "generated_at": now,
        "status": status,
        "steps": [],
        "summary": {"total": 8, "passed": [], "errors": [error]},
        "gate": {
            "passed": False,
            "release_freeze_complete": False,
            "updater_chain_complete": False,
            "strict_evidence_complete": False,
            "physical_campaign_complete": False,
            "browser_peer_physical_complete": False,
            "all_physical_evidence_complete": False,
            "production_activation": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle-report", type=Path, default=Path("validation/appliance-lifecycle-observations.json"))
    parser.add_argument("--strict-report", type=Path, default=DEFAULT_STRICT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    parser.add_argument("--min-model-exact", type=float, default=1.0)
    # A candidate is frozen before a gate can be corrected, so the contract a
    # release is judged by is not always the copy shipped inside it. The
    # wizard, the campaign and the strict gate all take --root for this; this
    # one did not, which is why it could not judge 1.58.151's evidence.
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    destination = _resolve(args.report)
    try:
        destination.relative_to((ROOT / "validation").resolve())
    except ValueError:
        parser.error("--report must remain under validation/")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write(
        destination,
        _blocked_receipt(
            now,
            "verification in progress; no prior green receipt is current",
            status="verification_in_progress",
        ),
    )

    strict_path = _resolve(args.strict_report)
    base_temp = Path("validation/.stage-b-physical-base.json")
    base_temp_path = _resolve(base_temp)
    for stale in (strict_path, base_temp_path):
        try:
            stale.unlink(missing_ok=True)
        except OSError as exc:
            report = _blocked_receipt(now, f"stale intermediate report could not be removed: {exc}")
            _write(destination, report)
            return 2

    target_root = args.root.resolve() if args.root is not None else ROOT
    strict_command = [
        sys.executable,
        str(ROOT / "scripts" / "stage_b_strict_evidence.py"),
        "--lifecycle-report", str(args.lifecycle_report),
        "--report", str(args.strict_report),
    ]
    if args.root is not None:
        strict_command.extend(["--root", str(target_root)])
    base_command = [
        sys.executable,
        str(ROOT / "scripts" / "stage_b_physical_gate.py"),
        "--lifecycle-report", str(args.lifecycle_report),
        "--report", str(base_temp),
        "--max-age-hours", str(args.max_age_hours),
        "--min-model-exact", str(args.min_model_exact),
    ]
    if args.root is not None:
        base_command.extend(["--root", str(target_root)])
    steps = [
        {"label": "strict source/bootstrap/interruption gate", "command": strict_command, "exit_code": _run(strict_command, target_root)}
    ]
    if steps[-1]["exit_code"] == 0:
        steps.append({"label": "base Stage B physical gate", "command": base_command, "exit_code": _run(base_command, target_root)})

    errors: list[str] = []
    try:
        strict, strict_raw, strict_path = _load(args.strict_report)
        if strict.get("schema") != STRICT_SCHEMA:
            errors.append("strict evidence schema mismatch")
        if strict.get("gate", {}).get("passed") is not True:
            errors.append("strict evidence gate did not pass")
        if strict.get("gate", {}).get("strict_evidence_complete") is not True:
            errors.append("strict evidence is incomplete")
        if strict.get("gate", {}).get("production_activation") is not False:
            errors.append("strict evidence changed production_activation")
    except Exception as exc:
        strict = {}
        strict_raw = b""
        strict_path = _resolve(args.strict_report)
        errors.append(f"strict evidence could not be loaded: {exc}")

    if len(steps) < 2 or steps[-1]["exit_code"] != 0:
        errors.append("base Stage B physical gate did not pass")
        base = {}
    else:
        try:
            base, _, _ = _load(base_temp)
            if base.get("schema") != FINAL_SCHEMA:
                errors.append("base final schema mismatch")
            if base.get("gate", {}).get("passed") is not True:
                errors.append("base final gate did not pass")
        except Exception as exc:
            base = {}
            errors.append(f"base final report could not be loaded: {exc}")

    if strict and base and not _candidate_matches(strict.get("candidate"), base.get("candidate")):
        errors.append("strict and base candidate identities differ")

    if errors:
        report = _blocked_receipt(now, errors[0])
        report["steps"] = steps
        report["summary"]["errors"] = errors
        code = 1
    else:
        report = dict(base)
        report["generated_at"] = now
        report["status"] = "complete"
        report["steps"] = steps + list(base.get("steps") or [])
        evidence = dict(base.get("evidence") or {})
        evidence["strict_stage_b"] = {
            "path": str(strict_path.relative_to(ROOT.resolve())),
            "sha256": hashlib.sha256(strict_raw).hexdigest(),
            "bytes": len(strict_raw),
            "schema": strict.get("schema"),
        }
        report["evidence"] = evidence
        gate = dict(base.get("gate") or {})
        gate["strict_evidence_complete"] = True
        gate["all_physical_evidence_complete"] = True
        gate["production_activation"] = False
        report["gate"] = gate
        summary = dict(base.get("summary") or {})
        summary["errors"] = []
        report["summary"] = summary
        code = 0

    _write(destination, report)
    try:
        base_temp_path.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"report: {destination.relative_to(ROOT)}")
    print("gate: " + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
