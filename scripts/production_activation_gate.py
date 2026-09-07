#!/usr/bin/env python3
"""Fail-closed promotion gate from physical evidence to live production activation.

Evidence receipts remain immutable and keep ``production_activation=false``.
This module is the separate authority that may write a create-only
``production_activation=true`` receipt, but only after:

* the complete machine-only BodyRig #846 seal still validates;
* the Agent 3 physical report is fresh and eligible for the write pilot;
* the promotion checkout differs from the validated candidate only by the
  explicitly allowlisted promotion tooling;
* the permanent appliance env contains the canonical production switches; and
* the restarted live appliance proves Agent3, tools and scheduler are actually
  mounted and healthy.

No token or scheduler approval secret is serialized into a receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

from scripts.bodyrig_unity_live_automatic_final_gate import validate_final_evidence
from scripts.bodyrig_unity_live_physical_gate import LivePhysicalGateError, _load_json

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

from app.agent3.validation_gate import assess_report  # noqa: E402
from app.build_identity import code_fingerprint  # noqa: E402

PRECHECK_SCHEMA = "kaliv-production-activation-preflight/v1"
FINAL_SCHEMA = "kaliv-production-activation/v1"
BODYRIG_FINAL_SCHEMA = "bodyrig.unity_live_automatic_final/v0.1"
CANDIDATE_BRANCH = "feat/unity-frame-source"
PROMOTION_BRANCH = "feat/production-activation-promotion"
MAX_JSON_BYTES = 2_000_000
MAX_PREFLIGHT_AGE_SECONDS = 3600
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

ALLOWED_PROMOTION_PATHS = frozenset(
    {
        "scripts/production_activation_gate.py",
        "scripts/production_activation_promote.ps1",
        "tests/workflow_production_activation_promotion.py",
        "PRODUCTION_ACTIVATION.md",
    }
)
REQUIRED_PROMOTION_PATHS = frozenset(
    {
        "scripts/production_activation_gate.py",
        "scripts/production_activation_promote.ps1",
    }
)
REQUIRED_SWITCHES = {
    "KALIV_AGENT3_ENABLED": "1",
    "KALIV_TOOLS_ENABLED": "1",
    "KALIV_SCHEDULER": "1",
    "KALIV_SCHEDULER_API": "1",
}
TARGET_ENV_KEYS = frozenset(
    {
        *REQUIRED_SWITCHES,
        "KALIV_AGENT3_VALIDATION_REPORT",
        "KALIV_SCHEDULER_APPROVAL_SECRET",
    }
)


class ProductionActivationError(RuntimeError):
    """Promotion authority is missing, stale, ambiguous or contradicted."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha_file(path: Path) -> str:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProductionActivationError(f"missing file: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProductionActivationError(f"file must be a non-symlink regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProductionActivationError(f"{label} is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProductionActivationError(f"{label} must be a non-symlink regular file")
    if info.st_size <= 0 or info.st_size > MAX_JSON_BYTES:
        raise ProductionActivationError(f"{label} size is invalid")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionActivationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProductionActivationError(f"{label} must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _require_sha40(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ProductionActivationError(f"{label} must be a full lowercase git SHA")
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProductionActivationError(f"{label} must be lowercase SHA-256")
    return value


def _git_text(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProductionActivationError(f"git {' '.join(args)} failed") from exc
    return result.stdout.strip()


def _git_is_ancestor(repo_root: Path, older: str, newer: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ProductionActivationError("git merge-base failed") from exc
    return result.returncode == 0


def _validate_promotion_tree(*, candidate_sha: str, repo_root: Path) -> dict[str, Any]:
    candidate_sha = _require_sha40(candidate_sha, label="candidate_sha")
    if _git_text(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ProductionActivationError("promotion checkout is not fully clean")

    _git_text(repo_root, "fetch", "--quiet", "origin", CANDIDATE_BRANCH, PROMOTION_BRANCH)
    head = _require_sha40(_git_text(repo_root, "rev-parse", "HEAD"), label="promotion HEAD")
    remote_candidate = _require_sha40(
        _git_text(repo_root, "rev-parse", f"origin/{CANDIDATE_BRANCH}"),
        label="remote candidate",
    )
    remote_promotion = _require_sha40(
        _git_text(repo_root, "rev-parse", f"origin/{PROMOTION_BRANCH}"),
        label="remote promotion head",
    )
    if remote_candidate != candidate_sha:
        raise ProductionActivationError("remote #846 head moved after physical evidence")
    if remote_promotion != head:
        raise ProductionActivationError("local promotion checkout is not current remote promotion head")
    if not _git_is_ancestor(repo_root, candidate_sha, head):
        raise ProductionActivationError("promotion branch is not descended from the validated candidate")

    raw = _git_text(repo_root, "diff", "--name-only", f"{candidate_sha}..{head}")
    changed = frozenset(line.strip() for line in raw.splitlines() if line.strip())
    unexpected = changed - ALLOWED_PROMOTION_PATHS
    if unexpected:
        raise ProductionActivationError(
            "promotion branch changes non-promotion files: " + ", ".join(sorted(unexpected))
        )
    if not REQUIRED_PROMOTION_PATHS.issubset(changed):
        raise ProductionActivationError("promotion branch is missing required activation tooling")
    return {"promotion_git_sha": head, "changed_paths": sorted(changed)}


def _validate_bodyrig_evidence(
    *, candidate_sha: str, evidence_dir: Path, repo_root: Path
) -> dict[str, Any]:
    candidate_sha = _require_sha40(candidate_sha, label="candidate_sha")
    try:
        result = validate_final_evidence(
            evidence_dir=evidence_dir,
            expected_sha=candidate_sha,
            repo_root=repo_root,
            require_git_state=False,
        )
    except LivePhysicalGateError as exc:
        raise ProductionActivationError(f"BodyRig automatic final evidence failed: {exc}") from exc

    if result.get("schema") != BODYRIG_FINAL_SCHEMA:
        raise ProductionActivationError("BodyRig final evidence schema mismatch")
    if result.get("production_activation") is not False:
        raise ProductionActivationError("BodyRig evidence must remain production_activation=false")
    for key in ("machine_live_proof", "machine_quality", "product_exercise"):
        if result.get(key) is not True:
            raise ProductionActivationError(f"BodyRig final evidence did not prove {key}")

    evidence_dir = evidence_dir.expanduser().resolve()
    run, _, _ = _load_json(evidence_dir / "live-run-receipt.json")
    authority = run.get("authority")
    if not isinstance(authority, Mapping):
        raise ProductionActivationError("BodyRig run authority is missing")
    recorded_main = _require_sha40(authority.get("origin_main_sha"), label="BodyRig recorded main")

    _git_text(repo_root, "fetch", "--quiet", "origin", "main", CANDIDATE_BRANCH)
    if _git_text(repo_root, "rev-parse", f"origin/{CANDIDATE_BRANCH}") != candidate_sha:
        raise ProductionActivationError("remote #846 head moved after BodyRig proof")
    if _git_text(repo_root, "rev-parse", "origin/main") != recorded_main:
        raise ProductionActivationError("origin/main moved after BodyRig proof")
    if _git_text(repo_root, "rev-list", "--count", f"{candidate_sha}..origin/main") != "0":
        raise ProductionActivationError("validated #846 candidate is behind current origin/main")

    final_path = evidence_dir / "live-automatic-final-receipt.json"
    final_receipt, final_sha = _load_object(final_path, label="BodyRig final receipt")
    if final_receipt.get("schema") != BODYRIG_FINAL_SCHEMA:
        raise ProductionActivationError("stored BodyRig final receipt schema mismatch")
    if final_receipt.get("candidate_git_sha") != candidate_sha:
        raise ProductionActivationError("stored BodyRig final receipt candidate mismatch")
    return {
        "result": result,
        "final_receipt_sha256": final_sha,
        "origin_main_sha": recorded_main,
    }


def _validate_agent3_report(report_path: Path) -> dict[str, Any]:
    report, report_sha = _load_object(report_path, label="Agent3 rig-validation report")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    code_sha = code_fingerprint()
    assessment = assess_report(
        report,
        current_version=version,
        current_code=code_sha,
        report_sha256=report_sha,
    )
    if assessment.get("eligible_for_write_pilot") is not True:
        reasons = assessment.get("write_pilot_reasons") or assessment.get("reasons") or []
        raise ProductionActivationError(
            "Agent3 physical report is not eligible for write pilot: "
            + ", ".join(str(item) for item in reasons)
        )
    if assessment.get("production_activation") is not False:
        raise ProductionActivationError("Agent3 evidence must remain production_activation=false")
    if assessment.get("version_match") is not True or assessment.get("code_match") is not True:
        raise ProductionActivationError("Agent3 report does not match current version/code")
    if assessment.get("write_decision") != "approve":
        raise ProductionActivationError("Agent3 production proof must exercise the approved write path")
    return {
        "report_sha256": report_sha,
        "version": version,
        "worker_code_sha256": code_sha,
        "finished_at": assessment.get("finished_at"),
    }


def _target_env_values(env_path: Path) -> dict[str, str]:
    try:
        info = env_path.lstat()
    except OSError as exc:
        raise ProductionActivationError("modelrig.env is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProductionActivationError("modelrig.env must be a non-symlink regular file")
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProductionActivationError("modelrig.env is unreadable") from exc

    values: dict[str, str] = {}
    seen: set[str] = set()
    targets = {name.casefold(): name for name in TARGET_ENV_KEYS}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        folded = raw_key.strip().casefold()
        canonical = targets.get(folded)
        if canonical is None:
            continue
        if canonical in seen:
            raise ProductionActivationError(f"modelrig.env contains duplicate target key {canonical}")
        seen.add(canonical)
        value = raw_value.strip()
        if "#" in value:
            raise ProductionActivationError(f"promotion target {canonical} must not carry an inline comment")
        if len(value) >= 2 and value[0] in {'"', "'"}:
            if value[-1] != value[0]:
                raise ProductionActivationError(f"promotion target {canonical} has mismatched quotes")
            value = value[1:-1]
        values[canonical] = value
    return values


def _validate_target_env(*, env_path: Path, agent3_report: Path) -> dict[str, Any]:
    values = _target_env_values(env_path)
    for key, expected in REQUIRED_SWITCHES.items():
        if values.get(key) != expected:
            raise ProductionActivationError(f"modelrig.env does not canonically set {key}={expected}")
    configured_report = values.get("KALIV_AGENT3_VALIDATION_REPORT")
    if not configured_report:
        raise ProductionActivationError("modelrig.env does not set KALIV_AGENT3_VALIDATION_REPORT")
    left = os.path.normcase(os.path.abspath(os.path.expanduser(configured_report)))
    right = os.path.normcase(str(agent3_report.expanduser().resolve()))
    if left != right:
        raise ProductionActivationError("modelrig.env points Agent3 at a different validation report")
    secret = values.get("KALIV_SCHEDULER_APPROVAL_SECRET") or ""
    if len(secret.encode("utf-8")) < 32:
        raise ProductionActivationError("scheduler approval secret is missing or shorter than 32 bytes")
    return {
        "env_sha256": _sha_file(env_path),
        "switches": dict(REQUIRED_SWITCHES),
        "agent3_validation_report_configured": True,
        "scheduler_approval_secret_present": True,
    }


def _canonical_loopback_url(value: str, *, label: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
    except ValueError as exc:
        raise ProductionActivationError(f"{label} URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProductionActivationError(f"{label} must be an explicit loopback http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProductionActivationError(f"{label} URL must not contain credentials/query/fragment")
    path = parsed.path
    if path not in {"", "/"}:
        raise ProductionActivationError(f"{label} URL must not contain a path")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _request_json(url: str, *, token: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            raw = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ProductionActivationError("runtime redirect refused; Bearer credentials are never forwarded") from exc
        raise ProductionActivationError(f"runtime GET failed with HTTP {exc.code}: {url}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise ProductionActivationError(f"runtime GET failed: {url}") from exc
    if status != 200 or len(raw) > MAX_JSON_BYTES:
        raise ProductionActivationError(f"runtime GET returned invalid status/size: {url}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionActivationError(f"runtime GET returned invalid JSON: {url}") from exc
    if not isinstance(value, dict):
        raise ProductionActivationError(f"runtime GET must return an object: {url}")
    return value


def _request_ok(url: str, *, timeout: float = 5.0) -> None:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                raise ProductionActivationError(f"health endpoint is not OK: {url}")
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise ProductionActivationError(f"health endpoint failed: {url}") from exc


def _validate_live_runtime(
    *, base_url: str, worker_url: str, token_env: str, agent3_report_sha256: str
) -> dict[str, Any]:
    base = _canonical_loopback_url(base_url, label="backend")
    worker = _canonical_loopback_url(worker_url, label="worker")
    token = os.environ.get(token_env, "").strip()
    if not token:
        raise ProductionActivationError(f"{token_env} is not set in process environment")

    _request_ok(base + "/healthz")
    _request_ok(worker + "/healthz")

    agent = _request_json(base + "/api/v1/experimental/agent3/status", token=token)
    if agent.get("enabled") is not True or agent.get("experimental") is not True:
        raise ProductionActivationError("live Agent3 route is not enabled")
    rig = agent.get("rig_validation")
    if not isinstance(rig, Mapping):
        raise ProductionActivationError("live Agent3 status lacks rig_validation")
    if rig.get("eligible_for_write_pilot") is not True:
        raise ProductionActivationError("live Agent3 does not assess the rig as write-pilot eligible")
    if rig.get("production_activation") is not False:
        raise ProductionActivationError("Agent3 evidence status must remain production_activation=false")
    if rig.get("report_sha256") != agent3_report_sha256:
        raise ProductionActivationError("live Agent3 is assessing a different rig-validation report")

    tools = _request_json(base + "/api/v1/tools", token=token)
    tool_items = tools.get("tools")
    if not isinstance(tool_items, list) or not tool_items:
        raise ProductionActivationError("live tools surface is empty or malformed")

    scheduler = _request_json(base + "/api/v1/schedules/status", token=token)
    if scheduler.get("configured") is not True:
        raise ProductionActivationError("live scheduler is not configured")
    if scheduler.get("running") is not True or scheduler.get("resources_open") is not True:
        raise ProductionActivationError("live scheduler runner/resources are not active")
    if scheduler.get("last_error") not in (None, ""):
        raise ProductionActivationError("live scheduler reports an error")

    listed = _request_json(base + "/api/v1/schedules", token=token)
    if not isinstance(listed.get("schedules"), list):
        raise ProductionActivationError("live scheduler admin surface is malformed")

    return {
        "backend_health": True,
        "worker_health": True,
        "agent3_enabled": True,
        "agent3_write_pilot_eligible": True,
        "tools_surface": True,
        "scheduler_configured": True,
        "scheduler_running": True,
        "scheduler_resources_open": True,
        "scheduler_admin_surface": True,
    }


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ProductionActivationError(f"{label} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionActivationError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ProductionActivationError(f"{label} timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise ProductionActivationError(f"receipt destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(value), indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, raw_tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise ProductionActivationError("receipt destination appeared before commit")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_preflight(
    *,
    candidate_sha: str,
    bodyrig_evidence_dir: Path,
    agent3_report: Path,
    env_file: Path,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    candidate_sha = _require_sha40(candidate_sha, label="candidate_sha")
    tree = _validate_promotion_tree(candidate_sha=candidate_sha, repo_root=repo_root)
    body = _validate_bodyrig_evidence(
        candidate_sha=candidate_sha, evidence_dir=bodyrig_evidence_dir, repo_root=repo_root
    )
    agent = _validate_agent3_report(agent3_report)
    env_sha = _sha_file(env_file)
    result = body["result"]
    return {
        "schema": PRECHECK_SCHEMA,
        "created_at": _utc_now(),
        "production_activation": False,
        "candidate_git_sha": candidate_sha,
        "promotion_git_sha": tree["promotion_git_sha"],
        "origin_main_sha": body["origin_main_sha"],
        "version": agent["version"],
        "worker_code_sha256": agent["worker_code_sha256"],
        "promotion_changed_paths": tree["changed_paths"],
        "bodyrig": {
            "final_receipt_sha256": body["final_receipt_sha256"],
            "body_id": result.get("body_id"),
            "package_sha256": result.get("package_sha256"),
            "machine_live_proof": True,
            "machine_quality": True,
            "product_exercise": True,
        },
        "agent3": {
            "report_sha256": agent["report_sha256"],
            "write_pilot_eligible": True,
            "write_decision": "approve",
        },
        "environment": {"before_sha256": env_sha},
    }


def finalize_activation(
    *,
    candidate_sha: str,
    bodyrig_evidence_dir: Path,
    agent3_report: Path,
    env_file: Path,
    preflight_path: Path,
    base_url: str,
    worker_url: str,
    token_env: str,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    preflight, preflight_sha = _load_object(preflight_path, label="production activation preflight")
    if preflight.get("schema") != PRECHECK_SCHEMA or preflight.get("production_activation") is not False:
        raise ProductionActivationError("production activation preflight schema/state mismatch")
    candidate_sha = _require_sha40(candidate_sha, label="candidate_sha")
    if preflight.get("candidate_git_sha") != candidate_sha:
        raise ProductionActivationError("preflight candidate SHA mismatch")
    created = _parse_time(preflight.get("created_at"), label="preflight")
    age = datetime.now(timezone.utc) - created
    if age.total_seconds() < -300 or age.total_seconds() > MAX_PREFLIGHT_AGE_SECONDS:
        raise ProductionActivationError("production activation preflight is stale")

    tree = _validate_promotion_tree(candidate_sha=candidate_sha, repo_root=repo_root)
    if preflight.get("promotion_git_sha") != tree["promotion_git_sha"]:
        raise ProductionActivationError("promotion HEAD moved after preflight")
    if preflight.get("promotion_changed_paths") != tree["changed_paths"]:
        raise ProductionActivationError("promotion diff changed after preflight")

    body = _validate_bodyrig_evidence(
        candidate_sha=candidate_sha, evidence_dir=bodyrig_evidence_dir, repo_root=repo_root
    )
    agent = _validate_agent3_report(agent3_report)
    if (preflight.get("bodyrig") or {}).get("final_receipt_sha256") != body["final_receipt_sha256"]:
        raise ProductionActivationError("BodyRig evidence changed after preflight")
    if (preflight.get("agent3") or {}).get("report_sha256") != agent["report_sha256"]:
        raise ProductionActivationError("Agent3 report changed after preflight")
    if preflight.get("worker_code_sha256") != agent["worker_code_sha256"]:
        raise ProductionActivationError("worker code identity changed after preflight")
    if preflight.get("origin_main_sha") != body["origin_main_sha"]:
        raise ProductionActivationError("origin/main authority changed after preflight")

    env = _validate_target_env(env_path=env_file, agent3_report=agent3_report)
    live = _validate_live_runtime(
        base_url=base_url,
        worker_url=worker_url,
        token_env=token_env,
        agent3_report_sha256=agent["report_sha256"],
    )
    result = body["result"]
    return {
        "schema": FINAL_SCHEMA,
        "created_at": _utc_now(),
        "production_activation": True,
        "scope": ["agent3", "tools", "scheduler", "scheduler_api"],
        "candidate_git_sha": candidate_sha,
        "promotion_git_sha": tree["promotion_git_sha"],
        "origin_main_sha": body["origin_main_sha"],
        "version": agent["version"],
        "worker_code_sha256": agent["worker_code_sha256"],
        "bindings": {
            "preflight_sha256": preflight_sha,
            "bodyrig_final_receipt_sha256": body["final_receipt_sha256"],
            "agent3_report_sha256": agent["report_sha256"],
            "environment_before_sha256": (preflight.get("environment") or {}).get("before_sha256"),
            "environment_after_sha256": env["env_sha256"],
        },
        "bodyrig": {
            "body_id": result.get("body_id"),
            "package_sha256": result.get("package_sha256"),
            "machine_live_proof": True,
            "machine_quality": True,
            "product_exercise": True,
        },
        "agent3": {
            "write_pilot_eligible": True,
            "report_bound_live": True,
        },
        "runtime": live,
        "switches": env["switches"],
        "scheduler_approval_secret_present": True,
        "human_acceptance_required": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--candidate-sha", required=True)
    common.add_argument("--bodyrig-evidence-dir", type=Path, required=True)
    common.add_argument("--agent3-report", type=Path, required=True)
    common.add_argument("--env-file", type=Path, required=True)
    common.add_argument("--output", type=Path, required=True)

    sub.add_parser("preflight", parents=[common])
    final = sub.add_parser("finalize", parents=[common])
    final.add_argument("--preflight", type=Path, required=True)
    final.add_argument("--base-url", default="http://127.0.0.1:8080")
    final.add_argument("--worker-url", default="http://127.0.0.1:8099")
    final.add_argument("--token-env", default="MODELRIG_TOKEN")

    args = parser.parse_args()
    try:
        if args.command == "preflight":
            result = build_preflight(
                candidate_sha=args.candidate_sha,
                bodyrig_evidence_dir=args.bodyrig_evidence_dir,
                agent3_report=args.agent3_report,
                env_file=args.env_file,
                repo_root=ROOT,
            )
            _write_create_only(args.output, result)
            print(
                "PRODUCTION ACTIVATION PREFLIGHT: PASS — "
                f"candidate {result['candidate_git_sha']} · production_activation=false"
            )
        else:
            result = finalize_activation(
                candidate_sha=args.candidate_sha,
                bodyrig_evidence_dir=args.bodyrig_evidence_dir,
                agent3_report=args.agent3_report,
                env_file=args.env_file,
                preflight_path=args.preflight,
                base_url=args.base_url,
                worker_url=args.worker_url,
                token_env=args.token_env,
                repo_root=ROOT,
            )
            _write_create_only(args.output, result)
            print(
                "PRODUCTION ACTIVATION: PASS — "
                f"candidate {result['candidate_git_sha']} · production_activation=true"
            )
            print(f"  receipt: {args.output}")
        return 0
    except (ProductionActivationError, LivePhysicalGateError) as exc:
        print(f"PRODUCTION ACTIVATION: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
