#!/usr/bin/env python3
"""Run pre-release physical validation as one fail-closed Stage A sequence.

The command can freeze an exact unpublished candidate, prepare or verify the six
pre-release physical proofs and, after an interactive one-use browser validation,
produce the seven-proof candidate receipt. It cannot integrate, publish or
activate anything. Every successful result keeps release validation pending and
production activation false.
"""
from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANCH = "agent/unified-candidate-1.58.143"
EXPECTED_VERSION = "1.58.143"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_JSON_BYTES = 32 * 1024 * 1024

FREEZE_REPORT = Path("validation/pre-release-candidate-freeze-latest.json")
CAMPAIGN_REPORT = Path("validation/physical-validation-candidate-campaign-latest.json")
BROWSER_ATTESTATION = Path("validation/browser-peer-public-validation-physical-latest.json")
FINAL_REPORT = Path("validation/physical-validation-candidate-final-latest.json")

FREEZE_SCHEMA = "kaliv-pre-release-candidate-freeze/v1"
CAMPAIGN_SCHEMA = "kaliv-physical-validation-candidate-campaign/v1"
FINAL_SCHEMA = "kaliv-physical-validation-candidate-final/v1"
PROOF_NAMES = (
    "preflight",
    "agent3",
    "model_eval",
    "voice",
    "rag",
    "scheduler_pilot",
)


class StageAOperatorError(RuntimeError):
    """Stage A was blocked before it could claim trustworthy completion."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise StageAOperatorError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


campaign_contract = _load_module(
    "stage_a_campaign_contract", ROOT / "scripts" / "physical_validation_campaign.py"
)


def _run(
    executable: str,
    arguments: Sequence[str],
    *,
    root: Path = ROOT,
    timeout: int = 1800,
) -> None:
    try:
        process = subprocess.run(
            [executable, *arguments],
            cwd=root,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageAOperatorError(
            f"command could not complete: {Path(executable).name}"
        ) from exc
    if process.returncode != 0:
        raise StageAOperatorError(
            f"command was blocked or failed: {Path(executable).name} "
            f"(exit {process.returncode})"
        )


def _git(*arguments: str, root: Path = ROOT) -> str:
    try:
        process = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageAOperatorError("git command could not complete") from exc
    output = (process.stdout or process.stderr or "").strip()
    if process.returncode != 0:
        raise StageAOperatorError(f"git {' '.join(arguments)} failed")
    return output


def _require_physical_operator() -> None:
    if os.name != "nt":
        raise StageAOperatorError("Stage A operator must run on the physical Windows ModelRig")
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" or os.environ.get("CI"):
        raise StageAOperatorError("Stage A operator refuses CI and hosted runners")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise StageAOperatorError("Stage A operator requires an interactive terminal")


def _require_token() -> None:
    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
        raise StageAOperatorError("GITHUB_TOKEN or GH_TOKEN is required for exact-head checks")


def _candidate_identity(expected_sha: str, *, root: Path = ROOT) -> dict[str, Any]:
    if SHA40.fullmatch(expected_sha) is None:
        raise StageAOperatorError("--expected-sha must be a lowercase 40-hex Git SHA")
    if shutil.which("git") is None:
        raise StageAOperatorError("Git was not found on PATH")
    if not Path(sys.executable).is_file():
        raise StageAOperatorError("Python executable is unavailable")

    top = Path(_git("rev-parse", "--show-toplevel", root=root)).resolve()
    if top != root.resolve():
        raise StageAOperatorError("operator must run from the ModelRig checkout")
    head = _git("rev-parse", "HEAD", root=root)
    if head != expected_sha:
        raise StageAOperatorError(f"HEAD {head} does not equal expected candidate {expected_sha}")
    branch = _git("branch", "--show-current", root=root)
    if branch != EXPECTED_BRANCH:
        raise StageAOperatorError(f"candidate must be checked out on {EXPECTED_BRANCH}")
    if _git("status", "--porcelain", root=root):
        raise StageAOperatorError("candidate working tree is not clean")

    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if version != EXPECTED_VERSION:
        raise StageAOperatorError(
            f"candidate version {version!r} does not equal expected {EXPECTED_VERSION}"
        )
    _run(sys.executable, ["scripts/version_tool.py", "check"], root=root, timeout=120)

    _git("fetch", "--quiet", "origin", "main", root=root)
    main_sha = _git("rev-parse", "origin/main", root=root)
    try:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", main_sha, expected_sha],
            cwd=root,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageAOperatorError("main ancestry check could not complete") from exc
    if ancestor.returncode != 0:
        raise StageAOperatorError(
            f"candidate {expected_sha} does not contain current origin/main {main_sha}"
        )

    identity = campaign_contract.candidate_identity(root)
    expected = {
        "identity_source": "git",
        "git_sha": expected_sha,
        "version": EXPECTED_VERSION,
        "working_tree_clean": True,
        "version_stamps_consistent": True,
    }
    for key, value in expected.items():
        if identity.get(key) != value:
            raise StageAOperatorError(f"candidate identity {key} mismatch")
    return identity


def _resolve_report(path: Path, *, root: Path = ROOT) -> Path:
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise StageAOperatorError(f"report path escapes repository: {path}") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise StageAOperatorError(f"required report is missing or irregular: {path}")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise StageAOperatorError(f"report size is invalid: {path}")
    return resolved


def _load_json(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    source = _resolve_report(path, root=root)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageAOperatorError(f"report is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise StageAOperatorError(f"report root is not an object: {path}")
    return value


def _same_candidate(
    report: Mapping[str, Any], identity: Mapping[str, Any], label: str
) -> None:
    candidate = report.get("candidate")
    if not isinstance(candidate, Mapping):
        raise StageAOperatorError(f"{label} candidate identity is missing")
    for key in ("version", "git_sha", "code_sha256"):
        if candidate.get(key) != identity.get(key):
            raise StageAOperatorError(f"{label} candidate.{key} mismatch")


def _require_pending_gate(gate: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(gate, Mapping):
        raise StageAOperatorError(f"{label} gate is missing")
    required = {
        "passed": True,
        "release_validation_pending": True,
        "release_complete": False,
        "production_activation": False,
    }
    for key, value in required.items():
        if gate.get(key) is not value:
            raise StageAOperatorError(f"{label} gate.{key} mismatch")
    return gate


def _run_freeze(
    expected_sha: str, identity: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    _require_token()
    _run(
        sys.executable,
        [
            "scripts/candidate_freeze_check.py",
            "--expected-sha",
            expected_sha,
            "--report",
            str(FREEZE_REPORT),
        ],
        root=root,
    )
    report = _load_json(FREEZE_REPORT, root=root)
    if report.get("schema") != FREEZE_SCHEMA:
        raise StageAOperatorError("candidate freeze schema mismatch")
    _same_candidate(report, identity, "candidate freeze")
    gate = _require_pending_gate(report.get("gate"), "candidate freeze")
    if gate.get("candidate_freeze_complete") is not True:
        raise StageAOperatorError("candidate freeze is incomplete")
    checks = report.get("software_checks")
    required = {"ci", "agent3-diagnostics", "agent3-full-diagnostics", "codeql"}
    if not isinstance(checks, Mapping) or set(checks) != required:
        raise StageAOperatorError("candidate freeze software-check allowlist mismatch")
    if any(checks.get(name) != "success" for name in required):
        raise StageAOperatorError("candidate freeze contains a non-success software check")
    return report


def _run_campaign(
    mode: str,
    identity: Mapping[str, Any],
    *,
    max_age_hours: float,
    min_model_exact: float,
    root: Path = ROOT,
) -> dict[str, Any]:
    _run(
        sys.executable,
        [
            "scripts/physical_validation_candidate_campaign.py",
            "--mode",
            mode,
            "--max-age-hours",
            str(max_age_hours),
            "--min-model-exact",
            str(min_model_exact),
            "--report",
            str(CAMPAIGN_REPORT),
        ],
        root=root,
    )
    report = _load_json(CAMPAIGN_REPORT, root=root)
    if report.get("schema") != CAMPAIGN_SCHEMA or report.get("mode") != mode:
        raise StageAOperatorError("candidate campaign schema or mode mismatch")
    _same_candidate(report, identity, "candidate campaign")
    gate = _require_pending_gate(report.get("gate"), "candidate campaign")
    complete = gate.get("candidate_campaign_complete")
    if not isinstance(complete, bool):
        raise StageAOperatorError("candidate campaign completeness is not boolean")
    if mode == "verify" and complete is not True:
        raise StageAOperatorError("candidate campaign is incomplete")

    summary = report.get("summary")
    if not isinstance(summary, Mapping) or summary.get("total") != len(PROOF_NAMES):
        raise StageAOperatorError("candidate campaign proof total mismatch")
    if mode == "verify":
        if report.get("proof_allowlist") != list(PROOF_NAMES):
            raise StageAOperatorError("candidate campaign proof allowlist mismatch")
        if summary.get("passed") != list(PROOF_NAMES):
            raise StageAOperatorError("candidate campaign did not pass the exact six proofs")
        if summary.get("failed") not in ([], None) or summary.get("missing") not in ([], None):
            raise StageAOperatorError("candidate campaign still has failed or missing proof")
    return report


def _validate_url(raw: str) -> str:
    if not raw or raw.strip() != raw:
        raise StageAOperatorError(
            "--url must be a non-empty exact URL without surrounding spaces"
        )
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise StageAOperatorError("--url is malformed") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise StageAOperatorError("--url must be an exact HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise StageAOperatorError("--url must not contain credentials or a fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise StageAOperatorError("--url port is malformed") from exc
    if port not in (None, 443):
        raise StageAOperatorError("--url must use HTTPS port 443")
    return raw


def _run_browser(url: str, *, root: Path = ROOT) -> None:
    powershell = (
        shutil.which("powershell")
        or shutil.which("powershell.exe")
        or shutil.which("pwsh")
    )
    if not powershell:
        raise StageAOperatorError("PowerShell was not found on PATH")
    _run(
        powershell,
        [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "scripts" / "run-browser-peer-public-validation.ps1"),
            "-Url",
            url,
        ],
        root=root,
        timeout=1800,
    )
    _resolve_report(BROWSER_ATTESTATION, root=root)


def _run_final_gate(
    identity: Mapping[str, Any], *, max_age_hours: float, root: Path = ROOT
) -> dict[str, Any]:
    _run(
        sys.executable,
        [
            "scripts/physical_validation_candidate_gate.py",
            "--candidate-campaign",
            str(CAMPAIGN_REPORT),
            "--browser-attestation",
            str(BROWSER_ATTESTATION),
            "--max-age-hours",
            str(max_age_hours),
            "--report",
            str(FINAL_REPORT),
        ],
        root=root,
    )
    report = _load_json(FINAL_REPORT, root=root)
    if report.get("schema") != FINAL_SCHEMA:
        raise StageAOperatorError("Stage A final receipt schema mismatch")
    _same_candidate(report, identity, "Stage A final receipt")
    gate = _require_pending_gate(report.get("gate"), "Stage A final receipt")
    expected = {
        "candidate_campaign_complete": True,
        "browser_peer_physical_complete": True,
        "candidate_ready_for_fast_forward": True,
        "release_complete": False,
        "all_physical_evidence_complete": False,
        "production_activation": False,
    }
    for key, value in expected.items():
        if gate.get(key) is not value:
            raise StageAOperatorError(f"Stage A final gate.{key} mismatch")
    summary = report.get("summary")
    if not isinstance(summary, Mapping) or summary.get("total") != 7:
        raise StageAOperatorError("Stage A final proof total is not seven")
    if summary.get("passed") != [*PROOF_NAMES, "browser_peer_physical"]:
        raise StageAOperatorError("Stage A final passed-proof order mismatch")
    if summary.get("errors") not in ([], None):
        raise StageAOperatorError("Stage A final receipt contains errors")
    return report


def execute(
    action: str,
    expected_sha: str,
    *,
    url: str | None = None,
    max_age_hours: float = 168.0,
    min_model_exact: float = 1.0,
    root: Path = ROOT,
    physical_guard: bool = True,
) -> dict[str, Any]:
    if action not in {"prepare", "verify", "complete"}:
        raise StageAOperatorError(f"unsupported action: {action}")
    exact_url = _validate_url(url or "") if action == "complete" else None
    if action != "complete" and url:
        raise StageAOperatorError("--url is only valid with complete")
    if physical_guard:
        _require_physical_operator()

    identity = _candidate_identity(expected_sha, root=root)
    _run_freeze(expected_sha, identity, root=root)

    if action == "prepare":
        report = _run_campaign(
            "prepare",
            identity,
            max_age_hours=max_age_hours,
            min_model_exact=min_model_exact,
            root=root,
        )
        missing = report.get("summary", {}).get("missing", [])
        print("Stage A prepared for exact candidate " + expected_sha)
        print("Manual proofs still missing: " + (", ".join(missing) if missing else "none"))
        print("Next: collect the six proofs, then run action 'verify'.")
        return report

    campaign = _run_campaign(
        "verify",
        identity,
        max_age_hours=max_age_hours,
        min_model_exact=min_model_exact,
        root=root,
    )
    if action == "verify":
        print("Six candidate proofs verified for exact candidate " + expected_sha)
        print("Next: run action 'complete' with one approved exact HTTPS/443 URL.")
        return campaign

    assert exact_url is not None
    _run_browser(exact_url, root=root)
    final = _run_final_gate(identity, max_age_hours=max_age_hours, root=root)
    print("STAGE A PASS: seven proofs bind to exact candidate " + expected_sha)
    print("Release validation remains pending. Production activation remains false.")
    print("Stop and review validation/physical-validation-candidate-final-latest.json.")
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "complete"))
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--url")
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    parser.add_argument("--min-model-exact", type=float, default=1.0)
    args = parser.parse_args(argv)
    if not 0 < args.max_age_hours <= 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    if not 0 <= args.min_model_exact <= 1:
        parser.error("--min-model-exact must be between 0 and 1")
    if args.action == "complete" and not args.url:
        parser.error("complete requires --url")
    if args.action != "complete" and args.url:
        parser.error("--url is only valid with complete")
    try:
        execute(
            args.action,
            args.expected_sha,
            url=args.url,
            max_age_hours=args.max_age_hours,
            min_model_exact=args.min_model_exact,
        )
    except Exception as exc:
        print(
            f"Stage A BLOCKED: {type(exc).__name__}: {str(exc)[:500]}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
