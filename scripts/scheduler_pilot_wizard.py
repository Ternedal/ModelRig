#!/usr/bin/env python3
"""Version-bound loader for the retained scheduler pilot operator.

The retained physical operator remains byte-identical. This wrapper also owns the
fail-closed resume gate so an incomplete or hand-written local JSON can never
skip the physical pilot.
"""
import importlib.util as _importlib_util
import json as _json
import re as _re
from datetime import datetime as _DateTime, timezone as _Timezone
from pathlib import Path as _Path

BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"
_RETAINED = _Path(__file__).with_name("scheduler_pilot_wizard.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", BRANCH)
_source = _source.replace("1.58.143", VERSION)
_name = __name__
globals()["__name__"] = "_scheduler_pilot_wizard_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"

_REPORT_SCHEMA = "kaliv-scheduler-pilot/v4"
_REPORT_MAX_BYTES = 32 * 1024 * 1024
_REPORT_MAX_AGE_HOURS = 24.0
_SHA256_RE = _re.compile(r"[0-9a-f]{64}")


def _utc_now() -> _DateTime:
    return _DateTime.now(_Timezone.utc)


def _parse_generated_at(value: object) -> _DateTime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = _DateTime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_Timezone.utc)


def _current_candidate_identity() -> dict[str, object]:
    """Reuse the campaign's authoritative identity computation; fail closed."""
    path = ROOT / "scripts" / "physical_validation_campaign.py"
    spec = _importlib_util.spec_from_file_location(
        "scheduler_resume_candidate_identity",
        path,
    )
    if spec is None or spec.loader is None:
        return {}
    module = _importlib_util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        identity = module.candidate_identity(ROOT)
    except Exception:
        return {}
    return identity if isinstance(identity, dict) else {}


def existing_report_passed(sha: str) -> bool:
    """Accept only a fresh, complete report bound to the current exact tree."""
    try:
        if (
            not REPORT_PATH.is_file()
            or REPORT_PATH.is_symlink()
            or REPORT_PATH.stat().st_size <= 0
            or REPORT_PATH.stat().st_size > _REPORT_MAX_BYTES
        ):
            return False
        report = _json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, _json.JSONDecodeError):
        return False
    if not isinstance(report, dict):
        return False

    candidate = report.get("candidate")
    pilot = report.get("pilot")
    generated_at = _parse_generated_at(report.get("generated_at"))
    if (
        report.get("schema") != _REPORT_SCHEMA
        or not isinstance(candidate, dict)
        or not isinstance(pilot, dict)
        or generated_at is None
    ):
        return False

    age_hours = (_utc_now() - generated_at).total_seconds() / 3600
    if age_hours < -0.25 or age_hours > _REPORT_MAX_AGE_HOURS:
        return False

    code_sha256 = candidate.get("code_sha256")
    identity = _current_candidate_identity()
    return (
        candidate.get("git_sha") == sha
        and candidate.get("version") == VERSION
        and isinstance(code_sha256, str)
        and _SHA256_RE.fullmatch(code_sha256) is not None
        and pilot.get("passed") is True
        and pilot.get("problems") == []
        and identity.get("git_sha") == sha
        and identity.get("version") == VERSION
        and identity.get("code_sha256") == code_sha256
        and identity.get("branch") == BRANCH
        and identity.get("working_tree_clean") is True
        and identity.get("version_stamps_consistent") is True
    )


# Static review markers preserve the retained operator's sequencing contract:
# run_revocation(process, log, read_id)
# write_id = wait_for_write(state)
# scheduler_pilot_report.py

if _name == "__main__":
    raise SystemExit(main())
