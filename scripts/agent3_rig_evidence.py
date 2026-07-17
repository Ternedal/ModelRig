#!/usr/bin/env python3
"""Produce promotion-grade Agent 3.0 evidence on the physical ModelRig.

This wrapper keeps the existing guarded validation harness focused on the
end-to-end behavior, then adds the promotion requirements that must be tied to
one concrete build:

- the protected Go backend version;
- the mounted worker/FastAPI version;
- an explicitly named local Ollama planner model;
- the same fail-closed assessment exposed by Agent 3.0 status.

It never enables production routing. A successful report is evidence only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Executing this file directly puts scripts/ on sys.path, so the sibling harness
# imports normally. Add worker/ explicitly for the pure promotion evaluator.
import agent3_rig_validation as validation

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = REPO_ROOT / "worker"
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.agent3.validation_gate import assess_report  # noqa: E402


class EvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class VersionBinding:
    modelrig_version: str
    worker_version: str
    code_sha256: str


RunValidation = Callable[..., dict[str, Any]]


def _required_version(payload: dict[str, Any], field: str, source: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{source} did not return a non-empty {field!r}")
    return value.strip()


def preflight_versions(client: validation.Client) -> VersionBinding:
    """Read both protected version sources and require exact equality."""

    backend = client.request("GET", "/api/v1/status")
    modelrig_version = _required_version(backend, "version", "backend status")

    agent_status = client.request("GET", "/api/v1/experimental/agent3/status")
    if agent_status.get("enabled") is not True or agent_status.get("experimental") is not True:
        raise EvidenceError(f"unexpected Agent 3.0 status: {agent_status}")
    if agent_status.get("production_activation") is not False:
        raise EvidenceError("Agent 3.0 status must keep production_activation=false")
    worker_version = _required_version(agent_status, "worker_version", "Agent 3.0 status")
    # A rig that cannot say which code it runs cannot produce evidence about
    # code (F-508). Refused here rather than recorded as null, because a report
    # with a null identity is a report that proves a version string matched a
    # version string.
    code_sha256 = _required_version(agent_status, "code_sha256", "Agent 3.0 status")
    if len(code_sha256) != 64:
        raise EvidenceError(f"code_sha256 is not a sha256 digest: {code_sha256!r}")

    if modelrig_version != worker_version:
        raise EvidenceError(
            "backend and worker versions differ: "
            f"backend={modelrig_version!r}, worker={worker_version!r}"
        )
    return VersionBinding(modelrig_version, worker_version, code_sha256)


def _load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvidenceError(f"validation report could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceError("validation report is not valid JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceError("validation report must be a JSON object")
    return value


def _write_report(path: Path, report: dict[str, Any]) -> None:
    # Reuse the harness' atomic writer so a crash cannot leave a half-written
    # promotion report that later appears to be authoritative.
    validation._write_report(path, report)


def produce_evidence(
    client: validation.Client,
    *,
    planner_model: str,
    approve_write: bool,
    report_path: Path,
    poll_seconds: float = 0.5,
    max_wait_seconds: float = 60.0,
    run_validation: RunValidation = validation.run_validation,
) -> dict[str, Any]:
    model = planner_model.strip() if isinstance(planner_model, str) else ""
    if not model:
        raise EvidenceError("planner_model is required for promotion evidence")

    print("[preflight] Bind evidence to backend + worker versions")
    binding = preflight_versions(client)
    print(
        "            "
        f"version={binding.modelrig_version} planner_model={model}"
    )

    report = run_validation(
        client,
        planner_model=model,
        approve_write=approve_write,
        report_path=report_path,
        poll_seconds=poll_seconds,
        max_wait_seconds=max_wait_seconds,
    )
    if report.get("success") is not True:
        raise EvidenceError(f"validation harness did not succeed: {report.get('error')}")

    # Load the bytes the harness actually persisted instead of trusting only its
    # in-memory return value. The promotion gate evaluates the same artifact the
    # operator will configure later.
    persisted = _load_report(report_path)
    target = persisted.get("target")
    if not isinstance(target, dict):
        raise EvidenceError("validation report is missing target metadata")
    target["modelrig_version"] = binding.modelrig_version
    target["code_sha256"] = binding.code_sha256
    target["worker_version"] = binding.worker_version
    target["planner_model"] = model

    checks = persisted.setdefault("checks", {})
    if not isinstance(checks, dict):
        raise EvidenceError("validation report checks must be an object")
    checks["version_binding"] = {
        "modelrig_version": binding.modelrig_version,
        "worker_version": binding.worker_version,
        "match": True,
    }
    _write_report(report_path, persisted)

    raw = report_path.read_bytes()
    # The collector's job is to collect. It passes the rig's own identity here
    # because at THIS moment the tree under test IS the rig -- comparing it to
    # itself would be theatre. The comparison that matters happens later, when
    # ACTIVATION_READINESS checks the stored report against the code on main:
    # that is where "did this evidence describe the software we are about to
    # switch on" is a real question with a real chance of answering no.
    assessment = assess_report(
        persisted,
        current_version=binding.worker_version,
        current_code=binding.code_sha256,
        report_sha256=hashlib.sha256(raw).hexdigest(),
    )
    if assessment.get("eligible_for_developer_preview") is not True:
        raise EvidenceError(
            "report failed the developer-preview promotion gate: "
            + ", ".join(assessment.get("reasons") or ["unknown reason"])
        )
    if approve_write and assessment.get("eligible_for_write_pilot") is not True:
        raise EvidenceError(
            "approved write report failed the write-pilot gate: "
            + ", ".join(
                assessment.get("write_pilot_reasons") or ["unknown reason"]
            )
        )
    if assessment.get("production_activation") is not False:
        raise EvidenceError("promotion assessment must never activate production")

    return {
        "report": persisted,
        "assessment": assessment,
        "version_binding": {
            "modelrig_version": binding.modelrig_version,
            "worker_version": binding.worker_version,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = validation.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.token:
        print("ERROR: MODELRIG_TOKEN/--token is required", file=sys.stderr)
        return 2
    if not args.planner_model or not args.planner_model.strip():
        print(
            "ERROR: KALIV_AGENT3_PLANNER_MODEL/--planner-model is required",
            file=sys.stderr,
        )
        return 2

    try:
        result = produce_evidence(
            validation.Client(args.base_url, args.token, args.http_timeout),
            planner_model=args.planner_model,
            approve_write=args.approve_write,
            report_path=Path(args.report),
            poll_seconds=args.poll_seconds,
            max_wait_seconds=args.run_timeout,
        )
    except (EvidenceError, validation.ValidationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"FAIL: unexpected {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    assessment = result["assessment"]
    level = (
        "write-pilot"
        if assessment.get("eligible_for_write_pilot")
        else "developer-preview"
    )
    print(
        "PASS: version-bound Agent 3.0 evidence produced "
        f"(eligible_for={level}, production_activation=false)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
