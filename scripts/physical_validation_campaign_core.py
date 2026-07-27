#!/usr/bin/env python3
"""Aggregate every physical ModelRig proof against one exact candidate.

The physical validation campaign currently spans independent tools and reports:
freeze/preflight, Agent 3 appliance evidence, planner model eval, voice baseline,
RAG baseline and appliance lifecycle observations. Each is useful alone, but a
folder full of green JSON files is not proof if they describe different commits,
worker fingerprints or software versions.

This evaluation-only script changes no runtime state and makes no network calls.
It computes the current candidate identity, validates each local evidence file,
checks freshness and cross-report identity, and writes one atomic campaign
receipt. ``--mode prepare`` creates a trustworthy checklist while evidence is
still missing. ``--mode verify`` exits 0 only when every physical proof is
present, fresh, candidate-bound and green.
"""
from __future__ import annotations

# F-1502/F-1503: this reader must not leave .pyc in the candidate tree --
# a fresh cache would look like an extra to the check that forbids extras.
import sys as _sys
_sys.dont_write_bytecode = True
import os as _os
_os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "kaliv-physical-validation-campaign/v1"
LIFECYCLE_SCHEMA = "kaliv-appliance-lifecycle-observations/v1"
PREFLIGHT_SCHEMA = "kaliv-rig-preflight/v1"
SCHEDULER_PILOT_SCHEMA = "kaliv-scheduler-pilot/v4"
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
DEFAULT_REPORT = Path("validation/physical-validation-campaign-latest.json")

DEFAULT_PATHS = {
    "preflight": Path("validation/rig-preflight-latest.json"),
    "agent3": Path("validation/agent3-rig-validation-latest.json"),
    "model_eval": Path("validation/agent3-model-eval-latest.json"),
    "voice": Path("validation/voice-baseline-latest.json"),
    "rag": Path("validation/rag-benchmark-latest.json"),
    "lifecycle": Path("validation/appliance-lifecycle-observations.json"),
    "scheduler_pilot": Path("validation/scheduler-pilot-latest.json"),
}

COMMANDS = {
    "freeze": "python scripts\\freeze_check.py",
    "preflight": (
        "python scripts\\rig_preflight.py "
        "--report validation\\rig-preflight-latest.json"
    ),
    "agent3": (
        "powershell -File scripts\\run-agent3-rig-validation.ps1 "
        "-BaseUrl http://127.0.0.1:8080 -PlannerModel <MODEL>"
    ),
    "model_eval": (
        "python scripts\\agent3_model_eval.py --planner-model <MODEL> "
        "--report validation\\agent3-model-eval-latest.json"
    ),
    "voice": (
        "python scripts\\voice_baseline.py --worker-url http://127.0.0.1:8099 "
        "--model <MODEL> --repetitions 2 --cold-start-confirmed "
        "--cancellation-probes 4 "
        "--manual-observations validation\\voice-manual-observations.json "
        "--require-manual --report validation\\voice-baseline-latest.json"
    ),
    "rag": (
        "python scripts\\rag_benchmark.py --scales 1000,10000 --queries 40 "
        "--repetitions 2 --embedding-model nomic-embed-text "
        "--report validation\\rag-benchmark-latest.json"
    ),
    "lifecycle": (
        "Copy-Item eval\\appliance_lifecycle_observations.example.json "
        "validation\\appliance-lifecycle-observations.json"
    ),
    "scheduler_pilot": (
        "Koer DEVICE_TEST.md sektion 1.6 (read + note_append), og derefter: "
        "python scripts\\scheduler_pilot_report.py "
        "--read-schedule-id <ID> --write-schedule-id <ID> "
        "--manual-observations validation\\scheduler-manual-observations.json "
        "--report validation\\scheduler-pilot-latest.json "
        "(koer fra workerens arbejdsmappe, eller peg --schedules-db/"
        "--jobs-db/--audit-db paa dens filer)"
    ),
    "verify": (
        "python scripts\\physical_validation_campaign.py --mode verify "
        "--report validation\\physical-validation-campaign-latest.json"
    ),
}


class CampaignError(RuntimeError):
    """The campaign itself cannot produce a trustworthy result."""


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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
        temp = Path(handle.name)
    temp.replace(path)


def _run(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    output = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, output


def _load_build_identity(root: Path) -> str:
    path = root / "worker" / "app" / "build_identity.py"
    spec = importlib.util.spec_from_file_location("campaign_build_identity", path)
    if spec is None or spec.loader is None:
        raise CampaignError("worker build identity module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.code_fingerprint()
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise CampaignError("worker code fingerprint is invalid")
    return value


def _load_frozen_attestation():
    path = Path(__file__).resolve().parent / "frozen_attestation.py"
    spec = importlib.util.spec_from_file_location("frozen_attestation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _attested_sha(root, version):
    """Gitless fallback: the strictly validated verdict the freeze gate wrote.

    All validation lives in frozen_attestation.load_attestation (F-1304):
    strict schema, version pin, freshness, and the offline tamper-evidence
    of recomputing the worker-source fingerprint against the tree we are
    actually standing on. This function only translates the refusal into
    the campaign's own error type.
    """
    fa = _load_frozen_attestation()
    try:
        return fa.load_attestation(Path(root), expected_version=version)[
            "git_sha"
        ]
    except fa.AttestationError as exc:
        raise CampaignError(str(exc)) from exc

def candidate_identity(root: Path) -> dict[str, Any]:
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CampaignError("VERSION cannot be read") from exc
    if not version:
        raise CampaignError("VERSION is empty")

    rc, git_sha = _run(root, "git", "rev-parse", "HEAD")
    gitless = rc != 0 or not re.fullmatch(r"[0-9a-f]{40}", git_sha)
    if gitless:
        git_sha = _attested_sha(root, version)
        branch, dirty = "", ""
    else:
        _, branch = _run(root, "git", "branch", "--show-current")
        _, dirty = _run(root, "git", "status", "--porcelain")
    rc, version_check = _run(root, sys.executable, "scripts/version_tool.py", "check")
    return {
        "version": version,
        "git_sha": git_sha,
        "code_sha256": _load_build_identity(root),
        "branch": (branch or None) if not gitless else None,
        "working_tree_clean": (not bool(dirty)) if not gitless else None,
        "dirty_entries": (len(dirty.splitlines()) if dirty else 0)
                         if not gitless else None,
        "identity_source": ("frozen-candidate-attestation" if gitless
                            else "git"),
        "version_stamps_consistent": rc == 0,
        "version_check_detail": None if rc == 0 else version_check[-500:],
    }


def _resolve_under(root: Path, raw: Path) -> Path:
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise CampaignError(f"evidence path escapes repository: {raw}") from exc
    return resolved


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink():
        raise CampaignError(f"evidence path is a symlink: {path}")
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise CampaignError(f"evidence path is not a regular file: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_EVIDENCE_BYTES:
        raise CampaignError(f"evidence size is invalid: {path} ({size} bytes)")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"evidence is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"evidence must be a JSON object: {path}")
    return value, raw


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _freshness(
    report: dict[str, Any],
    fields: tuple[tuple[str, ...], ...],
    *,
    now: datetime,
    max_age_hours: float,
) -> tuple[bool, float | None, str | None]:
    observed: datetime | None = None
    field_name: str | None = None
    for field in fields:
        parsed = _iso_datetime(_nested(report, *field))
        if parsed is not None:
            observed = parsed
            field_name = ".".join(field)
            break
    if observed is None:
        return False, None, "report has no valid timezone-aware evidence timestamp"
    age_hours = (now - observed).total_seconds() / 3600
    if age_hours < -0.25:
        return False, round(age_hours, 3), f"{field_name} is in the future"
    if age_hours > max_age_hours:
        return (
            False,
            round(age_hours, 3),
            f"evidence is {age_hours:.1f}h old; max is {max_age_hours:.1f}h",
        )
    return True, round(age_hours, 3), None


def _expect_equal(
    errors: list[str],
    label: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual != expected:
        errors.append(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _valid_digest(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _nonempty_text(errors: list[str], label: str, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")
        return None
    return value.strip()


def _validate_lifecycle_artifact(
    errors: list[str],
    label: str,
    root: Path,
    path_value: Any,
    digest_value: Any,
) -> dict[str, Any] | None:
    raw_path = _nonempty_text(errors, f"{label}.evidence_path", path_value)
    if not _valid_digest(digest_value, 64):
        errors.append(f"{label}.evidence_sha256 is not a 64-character digest")
        expected_digest = None
    else:
        expected_digest = digest_value
    if raw_path is None:
        return None
    relative_input = Path(raw_path)
    if relative_input.is_absolute() or ".." in relative_input.parts:
        errors.append(f"{label}.evidence_path must be repository-relative")
        return None
    unresolved = root / relative_input
    if unresolved.is_symlink():
        errors.append(f"{label}.evidence_path must not be a symlink")
        return None
    try:
        resolved = _resolve_under(root, relative_input)
        relative = resolved.relative_to(root.resolve())
    except CampaignError as exc:
        errors.append(f"{label}.evidence_path is invalid: {exc}")
        return None
    if relative.parts[:2] != ("validation", "appliance-lifecycle-evidence"):
        errors.append(
            f"{label}.evidence_path must be under "
            "validation/appliance-lifecycle-evidence"
        )
        return None
    if not resolved.exists() or not resolved.is_file():
        errors.append(f"{label}.evidence artifact is missing")
        return None
    try:
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_EVIDENCE_BYTES:
            errors.append(
                f"{label}.evidence artifact size is invalid: {size} bytes"
            )
            return None
        raw = resolved.read_bytes()
    except OSError as exc:
        errors.append(
            f"{label}.evidence artifact cannot be read: {type(exc).__name__}"
        )
        return None
    actual_digest = hashlib.sha256(raw).hexdigest()
    if expected_digest is not None and actual_digest != expected_digest:
        errors.append(f"{label}.evidence_sha256 does not match the artifact")
    return {
        "path": str(relative),
        "sha256": actual_digest,
        "bytes": len(raw),
    }


def _base_result(name: str, path: Path, raw: bytes) -> dict[str, Any]:
    return {
        "name": name,
        "path": str(path),
        "present": True,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "status": "pending",
        "age_hours": None,
        "errors": [],
        "warnings": [],
        "summary": {},
    }


def _validate_preflight(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    _thresholds: dict[str, Any],
) -> None:
    errors = result["errors"]
    _expect_equal(errors, "schema", report.get("schema"), PREFLIGHT_SCHEMA)
    _expect_equal(errors, "candidate.version", _nested(report, "candidate", "version"), candidate["version"])
    _expect_equal(errors, "candidate.git_sha", _nested(report, "candidate", "git_sha"), candidate["git_sha"])
    _expect_equal(
        errors,
        "candidate.code_sha256",
        _nested(report, "candidate", "code_sha256"),
        candidate["code_sha256"],
    )
    if report.get("ready") is not True:
        errors.append("preflight does not report ready=true")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("preflight checks are missing")
        failed = None
        warned = None
    else:
        failed = sum(
            isinstance(item, dict) and item.get("status") == "fail" for item in checks
        )
        warned = sum(
            isinstance(item, dict) and item.get("status") == "warn" for item in checks
        )
        if failed:
            errors.append(f"preflight contains {failed} failed check(s)")
    result["summary"] = {
        "ready": report.get("ready"),
        "already_validated": report.get("already_validated"),
        "failed_checks": failed,
        "warning_checks": warned,
    }


def _load_agent3_assessor(root: Path) -> Callable[..., dict[str, Any]]:
    worker = root / "worker"
    if str(worker) not in sys.path:
        sys.path.insert(0, str(worker))
    from app.agent3.validation_gate import assess_report

    return assess_report


def _validate_agent3(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    thresholds: dict[str, Any],
) -> None:
    errors = result["errors"]
    _expect_equal(
        errors,
        "schema",
        report.get("schema"),
        "kaliv-agent3-rig-validation/v1",
    )
    if report.get("success") is not True:
        errors.append("Agent 3 report does not have success=true")
    _expect_equal(errors, "target.modelrig_version", _nested(report, "target", "modelrig_version"), candidate["version"])
    _expect_equal(errors, "target.worker_version", _nested(report, "target", "worker_version"), candidate["version"])
    _expect_equal(errors, "target.code_sha256", _nested(report, "target", "code_sha256"), candidate["code_sha256"])
    if report.get("error") not in {None, ""}:
        errors.append("Agent 3 report contains an error")
    for key in ("deleted", "content_erased", "source_ref_erased"):
        if _nested(report, "cleanup", key) is not True:
            errors.append(f"Agent 3 cleanup.{key} is not true")
    try:
        assessor = thresholds["agent3_assessor"]
        assessment = assessor(
            report,
            current_version=candidate["version"],
            current_code=candidate["code_sha256"],
            report_sha256=result["sha256"],
        )
    except Exception as exc:
        errors.append(f"Agent 3 gate evaluation failed: {type(exc).__name__}")
        assessment = {}
    if assessment.get("eligible_for_developer_preview") is not True:
        errors.append(
            "Agent 3 report is not eligible for developer preview: "
            + ", ".join(assessment.get("reasons") or ["unknown reason"])
        )
    if assessment.get("production_activation") is not False:
        errors.append("Agent 3 assessment did not preserve production_activation=false")
    result["summary"] = {
        "success": report.get("success"),
        "planner_model": _nested(report, "target", "planner_model"),
        "write_decision": _nested(report, "target", "write_decision"),
        "eligible_for_developer_preview": assessment.get(
            "eligible_for_developer_preview"
        ),
        "eligible_for_write_pilot": assessment.get("eligible_for_write_pilot"),
        "production_activation": assessment.get("production_activation"),
    }


def _validate_model_eval(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    thresholds: dict[str, Any],
) -> None:
    errors = result["errors"]
    _expect_equal(errors, "schema", report.get("schema"), "kaliv-agent3-model-eval/v1")
    _expect_equal(errors, "backend.version", _nested(report, "backend", "version"), candidate["version"])
    _expect_equal(errors, "backend.code_sha256", _nested(report, "backend", "code_sha256"), candidate["code_sha256"])
    if _nested(report, "target", "execution_mode") != "plan-only":
        errors.append("model eval execution_mode is not plan-only")
    if _nested(report, "target", "starts_plans") is not False:
        errors.append("model eval does not prove starts_plans=false")
    if _nested(report, "target", "executes_tools") is not False:
        errors.append("model eval does not prove executes_tools=false")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        errors.append("model eval summary is missing")
        summary = {}
    if summary.get("request_errors") != 0:
        errors.append(f"model eval request_errors is {summary.get('request_errors')!r}")
    exact = summary.get("exact_match_rate")
    discipline = summary.get("discipline_rate")
    if not isinstance(exact, (int, float)) or isinstance(exact, bool):
        errors.append("model eval exact_match_rate is invalid")
    elif float(exact) < thresholds["min_model_exact"]:
        errors.append(
            f"model eval exact_match_rate {exact:.3f} is below "
            f"{thresholds['min_model_exact']:.3f}"
        )
    if discipline != 1.0:
        errors.append(f"model eval discipline_rate must be 1.0, got {discipline!r}")
    result["summary"] = {
        "planner_model": _nested(report, "target", "planner_model"),
        "tasks": summary.get("tasks"),
        "request_errors": summary.get("request_errors"),
        "exact_match_rate": exact,
        "discipline_rate": discipline,
        "latency_ms": summary.get("latency_ms"),
    }


def _validate_voice(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    _thresholds: dict[str, Any],
) -> None:
    errors = result["errors"]
    _expect_equal(errors, "schema", report.get("schema"), "kaliv-voice-baseline/v1")
    _expect_equal(errors, "build.version", _nested(report, "build", "version"), candidate["version"])
    _expect_equal(errors, "build.git_sha", _nested(report, "build", "git_sha"), candidate["git_sha"])
    if _nested(report, "gate", "passed") is not True:
        errors.append("voice baseline gate.passed is not true")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        errors.append("voice summary is missing")
        summary = {}
    if summary.get("errors") != 0:
        errors.append(f"voice summary.errors is {summary.get('errors')!r}")
    if summary.get("cold_probe_completed") is not True:
        errors.append("voice cold probe was not completed")
    manual = summary.get("manual")
    if not isinstance(manual, dict) or manual.get("provided") is not True or manual.get("passed") is not True:
        errors.append("voice manual stop/barge-in matrix is not present and passed")
    cancellation = summary.get("cancellation")
    if not isinstance(cancellation, dict):
        errors.append("voice cancellation summary is missing")
    elif cancellation.get("passed") != cancellation.get("probes"):
        errors.append("not every voice cancellation probe passed")
    result["summary"] = {
        "completed": summary.get("completed"),
        "errors": summary.get("errors"),
        "wer_micro": summary.get("wer_micro"),
        "cer_micro": summary.get("cer_micro"),
        "first_audio_ms": _nested(summary, "latency_ms", "first_audio"),
        "cold_probe_completed": summary.get("cold_probe_completed"),
        "manual": manual,
        "cancellation": cancellation,
    }


def _validate_rag(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    _thresholds: dict[str, Any],
) -> None:
    errors = result["errors"]
    _expect_equal(errors, "schema", report.get("schema"), "kaliv-rag-benchmark/v1")
    _expect_equal(errors, "build.version", _nested(report, "build", "version"), candidate["version"])
    _expect_equal(errors, "build.git_sha", _nested(report, "build", "git_sha"), candidate["git_sha"])
    if _nested(report, "gate", "passed") is not True:
        errors.append("RAG benchmark gate.passed is not true")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        errors.append("RAG summary is missing")
        summary = {}
    if summary.get("errors") != 0:
        errors.append(f"RAG summary.errors is {summary.get('errors')!r}")
    configured_scales = _nested(report, "configuration", "scales")
    if configured_scales != [1000, 10000]:
        errors.append(f"RAG scales must be [1000, 10000], got {configured_scales!r}")
    scales = report.get("scales")
    if not isinstance(scales, list) or len(scales) != 2:
        errors.append("RAG report must contain exactly two scale results")
        scales = []
    for item in scales:
        if not isinstance(item, dict) or _nested(item, "cleanup", "clean") is not True:
            errors.append("RAG scale cleanup is not clean")
            break
    result["summary"] = {
        "embedding_model": _nested(report, "ollama", "embedding_model"),
        "scales": configured_scales,
        "minimum_recall_at_5": summary.get("minimum_recall_at_5"),
        "maximum_query_p95_ms": summary.get("maximum_query_p95_ms"),
        "errors": summary.get("errors"),
    }


def _bool(errors: list[str], label: str, value: Any) -> bool:
    if value is not True:
        errors.append(f"{label} is not true")
        return False
    return True


def _bounded_ms(errors: list[str], label: str, value: Any, maximum: float) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
        or value > maximum
    ):
        errors.append(f"{label} must be a number from 0 to {maximum:g}")


def _validate_lifecycle(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    _thresholds: dict[str, Any],
) -> None:
    errors = result["errors"]
    _expect_equal(errors, "schema", report.get("schema"), LIFECYCLE_SCHEMA)
    _expect_equal(errors, "candidate.version", _nested(report, "candidate", "version"), candidate["version"])
    _expect_equal(errors, "candidate.git_sha", _nested(report, "candidate", "git_sha"), candidate["git_sha"])
    _expect_equal(errors, "candidate.code_sha256", _nested(report, "candidate", "code_sha256"), candidate["code_sha256"])
    host = report.get("host")
    if not isinstance(host, dict):
        errors.append("lifecycle host is missing")
    else:
        _nonempty_text(errors, "host.hostname", host.get("hostname"))
        _nonempty_text(errors, "host.windows_version", host.get("windows_version"))
    started_at = _iso_datetime(report.get("started_at"))
    finished_at = _iso_datetime(report.get("finished_at"))
    if started_at is None:
        errors.append("lifecycle started_at is invalid")
    if finished_at is None:
        errors.append("lifecycle finished_at is invalid")
    if started_at is not None and finished_at is not None and started_at > finished_at:
        errors.append("lifecycle started_at is after finished_at")
    trials = report.get("trials")
    if not isinstance(trials, dict):
        errors.append("lifecycle trials are missing")
        trials = {}
    root = _thresholds.get("root")
    artifacts: dict[str, Any] = {}
    if not isinstance(root, Path):
        errors.append("campaign root is unavailable for lifecycle artifacts")

    def capture_artifact(name: str, trial: dict[str, Any]) -> None:
        if isinstance(root, Path):
            artifact = _validate_lifecycle_artifact(
                errors,
                name,
                root,
                trial.get("evidence_path"),
                trial.get("evidence_sha256"),
            )
            if artifact is not None:
                artifacts[name] = artifact

    reboot = trials.get("reboot")
    if not isinstance(reboot, dict):
        errors.append("reboot trial is missing")
    else:
        _bool(errors, "reboot.performed", reboot.get("performed"))
        _bool(errors, "reboot.ready", reboot.get("ready"))
        _bounded_ms(errors, "reboot.ready_ms", reboot.get("ready_ms"), 30 * 60 * 1000)
        _expect_equal(errors, "reboot.backend_version", reboot.get("backend_version"), candidate["version"])
        _expect_equal(errors, "reboot.worker_version", reboot.get("worker_version"), candidate["version"])
        _expect_equal(errors, "reboot.worker_code_sha256", reboot.get("worker_code_sha256"), candidate["code_sha256"])
        capture_artifact("reboot", reboot)

    for name in ("supervisor_backend", "supervisor_worker"):
        trial = trials.get(name)
        if not isinstance(trial, dict):
            errors.append(f"{name} trial is missing")
            continue
        _bool(errors, f"{name}.performed", trial.get("performed"))
        _bool(errors, f"{name}.restarted", trial.get("restarted"))
        _bool(errors, f"{name}.ready", trial.get("ready"))
        _bounded_ms(errors, f"{name}.restart_ms", trial.get("restart_ms"), 10 * 60 * 1000)
        _expect_equal(errors, f"{name}.active_version", trial.get("active_version"), candidate["version"])
        _expect_equal(errors, f"{name}.active_code_sha256", trial.get("active_code_sha256"), candidate["code_sha256"])
        capture_artifact(name, trial)

    good = trials.get("good_update")
    if not isinstance(good, dict):
        errors.append("good_update trial is missing")
    else:
        _bool(errors, "good_update.performed", good.get("performed"))
        _bool(errors, "good_update.ready", good.get("ready"))
        if good.get("rollback_observed") is not False:
            errors.append("good_update.rollback_observed must be false")
        _bool(errors, "good_update.data_preserved", good.get("data_preserved"))
        _bool(errors, "good_update.schedules_preserved", good.get("schedules_preserved"))
        _expect_equal(errors, "good_update.target_version", good.get("target_version"), candidate["version"])
        _expect_equal(errors, "good_update.target_git_sha", good.get("target_git_sha"), candidate["git_sha"])
        _expect_equal(errors, "good_update.target_code_sha256", good.get("target_code_sha256"), candidate["code_sha256"])
        source_version = _nonempty_text(
            errors, "good_update.source_version", good.get("source_version")
        )
        if source_version == candidate["version"]:
            errors.append("good_update.source_version must differ from the candidate")
        if not _valid_digest(good.get("source_git_sha"), 40):
            errors.append("good_update.source_git_sha is not a 40-character digest")
        elif good.get("source_git_sha") == candidate["git_sha"]:
            errors.append("good_update.source_git_sha must differ from the candidate")
        capture_artifact("good_update", good)

    bad = trials.get("bad_update")
    if not isinstance(bad, dict):
        errors.append("bad_update trial is missing")
    else:
        _bool(errors, "bad_update.performed", bad.get("performed"))
        _bool(errors, "bad_update.rejected_or_rolled_back", bad.get("rejected_or_rolled_back"))
        _bool(errors, "bad_update.ready", bad.get("ready"))
        _bool(errors, "bad_update.data_preserved", bad.get("data_preserved"))
        _bool(errors, "bad_update.schedules_preserved", bad.get("schedules_preserved"))
        _expect_equal(errors, "bad_update.active_version", bad.get("active_version"), candidate["version"])
        _expect_equal(errors, "bad_update.active_git_sha", bad.get("active_git_sha"), candidate["git_sha"])
        _expect_equal(errors, "bad_update.active_code_sha256", bad.get("active_code_sha256"), candidate["code_sha256"])
        _nonempty_text(
            errors, "bad_update.attempted_version", bad.get("attempted_version")
        )
        if not _valid_digest(bad.get("attempted_git_sha"), 40):
            errors.append("bad_update.attempted_git_sha is not a 40-character digest")
        if bad.get("attempted_git_sha") == candidate["git_sha"]:
            errors.append("bad_update attempted_git_sha must differ from the candidate")
        capture_artifact("bad_update", bad)

    result["summary"] = {
        "host": report.get("host"),
        "reboot_ready_ms": _nested(report, "trials", "reboot", "ready_ms"),
        "backend_restart_ms": _nested(
            report, "trials", "supervisor_backend", "restart_ms"
        ),
        "worker_restart_ms": _nested(
            report, "trials", "supervisor_worker", "restart_ms"
        ),
        "good_update_ready": _nested(report, "trials", "good_update", "ready"),
        "bad_update_recovered": _nested(
            report, "trials", "bad_update", "rejected_or_rolled_back"
        ),
        "artifacts": artifacts,
    }


def _validate_scheduler_pilot(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    _thresholds: dict[str, Any],
) -> None:
    errors = result["errors"]
    _expect_equal(errors, "schema", report.get("schema"), SCHEDULER_PILOT_SCHEMA)
    _expect_equal(errors, "candidate.version",
                  _nested(report, "candidate", "version"), candidate["version"])
    _expect_equal(errors, "candidate.git_sha",
                  _nested(report, "candidate", "git_sha"), candidate["git_sha"])
    _expect_equal(errors, "candidate.code_sha256",
                  _nested(report, "candidate", "code_sha256"),
                  candidate["code_sha256"])
    # F-1305: the report must be manifest-bound, window-bound and complete --
    # a pilot proof that cannot say WHEN it ran, WHAT exactly ran, and that
    # NOTHING ELSE ran, is presence, not proof.
    if not _nested(report, "pilot_window", "start"):
        errors.append(
            "pilot_window.start mangler -- rapporten kan ikke sige hvornaar "
            "piloten fandt sted")
    if _nested(report, "manifest", "read", "tool") != "rig_status":
        errors.append(
            "manifest.read.tool er ikke rig_status -- rapporten er ikke "
            "bundet til runbookens section-1.6 manifest")
    if _nested(report, "manifest", "write", "args") != {"text": "pilot"}:
        errors.append(
            "manifest.write er ikke den kanoniske section-1.6 pilot-write "
            "-- write-halvdelen skal vaere exact (F-1404)")
    exec_unlisted = _nested(report, "inventory", "executions_unlisted")
    if exec_unlisted is None:
        errors.append(
            "inventory.executions_unlisted mangler -- execution-"
            "completeness kan ikke bedommes (F-1405)")
    elif exec_unlisted:
        names = ", ".join(
            f"{e.get('id')}({e.get('tool')})" for e in exec_unlisted)
        errors.append(
            f"unlisted executions i pilotvinduet: {names} -- noget KOERTE "
            "som beviset ikke daekker (F-1405)")
    # Freshness re-check, independent of the producer (defense in depth):
    # the newest durable timestamp in the forensics must lie within the
    # rig-day window of the report's own generated_at -- replayed
    # historical pilot IDs die here even if a doctored producer let them by.
    #
    # F-1504: the producer enforces per-HALF freshness and a <=12h span
    # across halves; a validator that only checks the single newest stamp
    # would pass a stale read half carried by a fresh write half. Re-derive
    # BOTH properties independently, per half, with the same thresholds.
    gen = report.get("generated_at")
    gen_ts = None
    if isinstance(gen, str):
        try:
            gen_ts = datetime.fromisoformat(gen).timestamp()
        except ValueError:
            errors.append("generated_at er ikke en ISO-8601 tid")
    per_half_newest: dict[str, float] = {}
    per_half_oldest: dict[str, float] = {}
    stamps = []
    for half in ("read", "write"):
        fdata = _nested(report, "forensics", half) or {}
        half_stamps = []
        win = fdata.get("window") or {}
        for key in ("first_created", "last_resolved"):
            if isinstance(win.get(key), (int, float)):
                half_stamps.append(float(win[key]))
        for occ in fdata.get("occurrences") or []:
            for key in ("created", "resolved"):
                if isinstance(occ.get(key), (int, float)):
                    half_stamps.append(float(occ[key]))
        if half_stamps:
            per_half_newest[half] = max(half_stamps)
            per_half_oldest[half] = min(half_stamps)
            stamps.extend(half_stamps)
    if gen_ts is not None:
        for half, newest in per_half_newest.items():
            age_h = (gen_ts - newest) / 3600.0
            if age_h > 24.0:
                errors.append(
                    f"{half}-halvdelen er {age_h:.1f} timer aeldre end "
                    "rapporten (max 24) -- en gammel halvdel maa ikke baere "
                    "en frisk med (F-1504 parity)")
    if len(per_half_newest) == 2 and len(per_half_oldest) == 2:
        span_h = (max(per_half_newest.values())
                  - min(per_half_oldest.values())) / 3600.0
        if span_h > 12.0:
            errors.append(
                f"pilot-halvdelene spaender {span_h:.1f} timer (max 12) -- "
                "read og write er ikke fra SAMME pilot (F-1504 parity)")
    if stamps and gen_ts is not None:
        age_h = (gen_ts - max(stamps)) / 3600.0
        if age_h > 24.0:
            errors.append(
                f"pilot-forensikken er {age_h:.1f} timer aeldre end "
                "rapporten (max 24) -- historiske pilot-IDs beviser "
                "ikke denne kandidats rig-dag")
    elif not stamps and (_nested(report, "forensics", "read")
                         or _nested(report, "forensics", "write")):
        errors.append(
            "pilot-forensik uden tidsstempler -- alderen kan ikke bedommes")

    unlisted = _nested(report, "inventory", "unlisted_in_window")
    if unlisted is None:
        errors.append(
            "inventory.unlisted_in_window mangler -- pilotens completeness "
            "kan ikke bedommes")
    elif unlisted:
        names = ", ".join(
            f"{e.get('id')}({e.get('tool')})" for e in unlisted)
        errors.append(
            f"unlisted schedules i pilotvinduet: {names} -- beviset "
            "daekker ikke alt der koerte")

    read_runs = _nested(report, "read_schedule", "runs_used")
    if not isinstance(read_runs, int) or read_runs < 1:
        errors.append("read_schedule.runs_used must be >= 1 -- the read half "
                      "of the pilot never ran")
    if _nested(report, "read_schedule", "receipts_count") != 0:
        errors.append("read_schedule.receipts_count must be 0 -- reads carry "
                      "no approvals by design")

    write_runs = _nested(report, "write_schedule", "runs_used")
    if not isinstance(write_runs, int) or write_runs < 1:
        errors.append("write_schedule.runs_used must be >= 1 -- the write "
                      "half of the pilot never ran")
    receipts = _nested(report, "write_schedule", "receipts_count")
    if not isinstance(receipts, int) or receipts < 1:
        errors.append("write_schedule.receipts_count must be >= 1 -- an "
                      "approved write without its receipt must not exist")
    device = _nested(report, "write_schedule", "first_receipt", "device_id")
    if not (isinstance(device, str) and device):
        errors.append("write_schedule.first_receipt.device_id must name the "
                      "approving device")
    issued = _nested(report, "write_schedule", "first_receipt", "issued_at")
    consumed = _nested(report, "write_schedule", "first_receipt", "consumed_at")
    if not isinstance(issued, (int, float)) \
            or not isinstance(consumed, (int, float)) or consumed < issued:
        errors.append("write_schedule.first_receipt must carry issued_at <= "
                      "consumed_at")
    # F-1603: full receipt-contract parity with the producer -- re-prove the
    # fingerprint binding, revision match and kind independently, so a
    # doctored producer that skipped them cannot slip a receipt covering a
    # DIFFERENT grant than the one that ran.
    approved_fp = _nested(report, "write_schedule", "approved_fingerprint")
    receipt_fp = _nested(report, "write_schedule", "first_receipt",
                         "fingerprint")
    if not (isinstance(approved_fp, str) and approved_fp):
        errors.append("write_schedule.approved_fingerprint must bind the "
                      "granted approval -- an approved write without its "
                      "fingerprint binding cannot be proven (F-1603)")
    elif receipt_fp != approved_fp:
        errors.append("write_schedule.first_receipt.fingerprint must equal "
                      "the schedule's approved_fingerprint -- the approval "
                      "must cover the grant that RAN, not another (F-1603)")
    sched_rev = _nested(report, "write_schedule", "revision")
    receipt_rev = _nested(report, "write_schedule", "first_receipt",
                          "revision")
    if (sched_rev is not None and receipt_rev is not None
            and sched_rev != receipt_rev):
        errors.append("write_schedule.first_receipt.revision must match the "
                      "schedule's revision -- the approval is from another "
                      "version of the grant (F-1603)")
    kind = _nested(report, "write_schedule", "first_receipt", "kind")
    if not (isinstance(kind, str) and kind):
        errors.append("write_schedule.first_receipt.kind must name the "
                      "approval kind -- an unlabelled receipt cannot be "
                      "audited (F-1603)")

    if _nested(report, "manual", "revocation_confirmed") is not True:
        errors.append("manual.revocation_confirmed must be true -- the "
                      "operator confirms the mid-flight pause produced a "
                      "cancelled job and a refunded slot")
    line = _nested(report, "manual", "recovery_line")
    if not (isinstance(line, str) and "recovered" in line):
        errors.append("manual.recovery_line must contain the startup "
                      "recovery line ('recovered ...')")
    w_for = _nested(report, "forensics", "write") or {}
    w_occs = w_for.get("occurrences") or []
    pinned = [o for o in w_occs if o.get("status") == "executed"
              and "attempt" in (o.get("audit_outcomes") or [])
              and "executed" in (o.get("audit_outcomes") or [])]
    if not pinned:
        errors.append("forensics.write must pin at least one executed "
                      "occurrence whose audit sequence contains attempt AND "
                      "executed -- aggregate counters are not a promotion "
                      "proof (F-1206)")
    elif not any((o.get("job") or {}).get("status") == "completed"
                 for o in pinned):
        errors.append("the pinned write occurrence must be bound to a "
                      "completed job")
    if not (w_for.get("receipts") or []):
        errors.append("forensics.write.receipts must contain the stored "
                      "receipt row")
    r_for = _nested(report, "forensics", "read") or {}
    r_occs = r_for.get("occurrences") or []
    if not any(o.get("status") == "released"
               and (o.get("job") or {}).get("status") == "cancelled"
               for o in r_occs):
        errors.append("forensics.read must contain the pause proof: a "
                      "released occurrence bound to a cancelled job")
    if not isinstance(_nested(report, "forensics", "read", "window",
                              "first_created"), (int, float)):
        errors.append("forensics.read.window must anchor the pilot in time")
    if _nested(report, "pilot", "passed") is not True:
        errors.append("pilot.passed must be true -- the producer itself "
                      "judged the pilot as not holding")


VALIDATORS: dict[
    str,
    tuple[
        Callable[[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], None],
        tuple[tuple[str, ...], ...],
    ],
] = {
    "preflight": (_validate_preflight, (("generated_at",),)),
    "agent3": (_validate_agent3, (("finished_at",),)),
    "model_eval": (_validate_model_eval, (("finished_at",),)),
    "voice": (_validate_voice, (("generated_at",),)),
    "rag": (_validate_rag, (("generated_at",),)),
    "lifecycle": (_validate_lifecycle, (("finished_at",),)),
    "scheduler_pilot": (_validate_scheduler_pilot, (("generated_at",),)),
}


def validate_evidence(
    root: Path,
    name: str,
    path: Path,
    *,
    candidate: dict[str, Any],
    thresholds: dict[str, Any],
    now: datetime,
    max_age_hours: float,
) -> dict[str, Any]:
    resolved = _resolve_under(root, path)
    relative = resolved.relative_to(root.resolve())
    try:
        report, raw = _load_json(resolved)
    except FileNotFoundError:
        return {
            "name": name,
            "path": str(relative),
            "present": False,
            "sha256": None,
            "bytes": 0,
            "status": "missing",
            "age_hours": None,
            "errors": ["evidence file is missing"],
            "warnings": [],
            "summary": {},
        }
    except Exception as exc:
        return {
            "name": name,
            "path": str(relative),
            "present": True,
            "sha256": None,
            "bytes": None,
            "status": "fail",
            "age_hours": None,
            "errors": [_safe_error(exc)["message"]],
            "warnings": [],
            "summary": {},
        }

    result = _base_result(name, relative, raw)
    validator, timestamp_fields = VALIDATORS[name]
    fresh, age_hours, freshness_error = _freshness(
        report,
        timestamp_fields,
        now=now,
        max_age_hours=max_age_hours,
    )
    result["age_hours"] = age_hours
    if not fresh and freshness_error:
        result["errors"].append(freshness_error)
    try:
        validator(report, result, candidate, thresholds)
    except Exception as exc:
        result["errors"].append(
            f"validator failed unexpectedly: {type(exc).__name__}: {str(exc)[:200]}"
        )
    result["status"] = "pass" if not result["errors"] else "fail"
    return result


def campaign_report(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = Path(__file__).resolve().parents[1]
    now = datetime.now(timezone.utc)
    candidate = candidate_identity(root)
    assessor = _load_agent3_assessor(root)
    thresholds: dict[str, Any] = {
        "min_model_exact": args.min_model_exact,
        "agent3_assessor": assessor,
        "root": root,
    }
    paths = {
        "preflight": args.preflight_report,
        "agent3": args.agent3_report,
        "model_eval": args.model_eval_report,
        "voice": args.voice_report,
        "rag": args.rag_report,
        "lifecycle": args.lifecycle_report,
        "scheduler_pilot": args.scheduler_pilot_report,
    }
    evidence = {
        name: validate_evidence(
            root,
            name,
            path,
            candidate=candidate,
            thresholds=thresholds,
            now=now,
            max_age_hours=args.max_age_hours,
        )
        for name, path in paths.items()
    }

    candidate_errors: list[str] = []
    if candidate["working_tree_clean"] is False:
        candidate_errors.append(
            f"working tree has {candidate['dirty_entries']} uncommitted change(s)"
        )
    if not candidate["version_stamps_consistent"]:
        candidate_errors.append("version stamps are inconsistent")

    failed = [name for name, item in evidence.items() if item["status"] == "fail"]
    missing = [name for name, item in evidence.items() if item["status"] == "missing"]
    passed = [name for name, item in evidence.items() if item["status"] == "pass"]
    all_evidence_passed = len(passed) == len(evidence)
    if args.mode == "prepare":
        gate_passed = not candidate_errors and not failed
        exit_code = 0 if gate_passed else 1
    else:
        gate_passed = not candidate_errors and all_evidence_passed
        exit_code = 0 if gate_passed else 1

    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "mode": args.mode,
        "candidate": candidate,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "configuration": {
            "max_age_hours": args.max_age_hours,
            "min_model_exact": args.min_model_exact,
        },
        "commands": COMMANDS,
        "evidence": evidence,
        "summary": {
            "total": len(evidence),
            "passed": passed,
            "failed": failed,
            "missing": missing,
            "candidate_errors": candidate_errors,
        },
        "gate": {
            "passed": gate_passed,
            "physical_campaign_complete": all_evidence_passed,
            "production_activation": False,
        },
    }
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "verify"), default="verify")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--preflight-report", type=Path, default=DEFAULT_PATHS["preflight"])
    parser.add_argument("--agent3-report", type=Path, default=DEFAULT_PATHS["agent3"])
    parser.add_argument("--model-eval-report", type=Path, default=DEFAULT_PATHS["model_eval"])
    parser.add_argument("--voice-report", type=Path, default=DEFAULT_PATHS["voice"])
    parser.add_argument("--rag-report", type=Path, default=DEFAULT_PATHS["rag"])
    parser.add_argument("--lifecycle-report", type=Path, default=DEFAULT_PATHS["lifecycle"])
    parser.add_argument("--scheduler-pilot-report", type=Path, default=DEFAULT_PATHS["scheduler_pilot"])
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    parser.add_argument("--min-model-exact", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.max_age_hours > 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    if not 0 <= args.min_model_exact <= 1:
        parser.error("--min-model-exact must be between 0 and 1")

    try:
        report, exit_code = campaign_report(args)
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": args.mode,
            "error": _safe_error(exc),
            "summary": {
                "total": 0,
                "passed": [],
                "failed": ["campaign"],
                "missing": [],
                "candidate_errors": [],
            },
            "gate": {
                "passed": False,
                "physical_campaign_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2
    _write_json_atomic(args.report, report)
    print(f"report: {args.report}")
    print(
        "gate: "
        + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED")
        + f" (mode={args.mode})"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
