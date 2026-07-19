#!/usr/bin/env python3
"""Preflight for the physical validation -- check the rig is ready BEFORE running it.

The validation itself (run-agent3-rig-validation.ps1) is thorough, but it assumes
the whole rig is already up: backend on :8080, worker on :8099 started with the
report path wired in, Ollama serving the planner model, a paired-device token in
the environment. If any one link is down, it fails partway with an error to
debug -- and rig time is the scarce resource this whole project waits on.

This checks every link independently, in the order they would fail, and says
exactly what is wrong and how to fix it. It changes nothing and needs no token
to run the cheap checks. When every line is OK, the real validation should pass
on the first try instead of the third.

Usage on the rig (PowerShell or cmd, from the repo root):

    python scripts/rig_preflight.py

    # or point it somewhere other than the defaults:
    python scripts/rig_preflight.py --base-url http://127.0.0.1:8080

Exit code is 0 only when the rig is ready to validate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import urllib.error
import urllib.request

# The substrate-health half lives in a sibling module. Ensure this file's own
# directory is importable whether preflight is run directly, imported by the
# test via a spec loader, or invoked from another cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- tiny presentation layer, no dependencies -------------------------------

_OK = "  OK   "
_WARN = "  WARN "
_FAIL = "  FAIL "
PREFLIGHT_SCHEMA = "kaliv-rig-preflight/v1"


def _write_json_atomic(path: Path, value: dict) -> None:
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


def _attested_sha(root, version):
    """Gitless fallback: the sha the freeze gate verified and wrote down.

    The rig has no git (sources arrive as a ZIP), so identity comes from
    validation/frozen-candidate.json -- written by freeze_check only on a
    FROZEN verdict after resolving the published tag via the GitHub API and
    seeing ci+codeql green on that exact sha. Reading it here inherits that
    verdict; nothing looser. Missing or mismatching file: refuse loudly and
    point at the gate.
    """
    att = root / "validation" / "frozen-candidate.json"
    try:
        data = json.loads(att.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(
            "git er utilgaengelig og der findes ingen frossen-kandidat-"
            "attestation -- koer foerst: python scripts\\freeze_check.py "
            "(den skriver validation\\frozen-candidate.json paa FROZEN)"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "validation/frozen-candidate.json er ikke gyldig JSON -- koer "
            "freeze_check igen") from exc
    if data.get("version") != version:
        raise RuntimeError(
            f"attestationen gaelder version {data.get('version')!r}, men "
            f"traeet er {version!r} -- koer freeze_check igen paa DETTE trae")
    sha = data.get("git_sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("attestationens git_sha er ikke en gyldig sha")
    return sha


def _candidate_identity() -> dict:
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    git_sha = proc.stdout.strip()
    if proc.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", git_sha) is None:
        git_sha = _attested_sha(root, version)
    worker = root / "worker"
    if str(worker) not in sys.path:
        sys.path.insert(0, str(worker))
    from app.build_identity import code_fingerprint

    return {
        "version": version,
        "git_sha": git_sha,
        "code_sha256": code_fingerprint(),
    }


class Check:
    """One dependency, its result, and -- if it failed -- how to fix it."""

    def __init__(self, name: str):
        self.name = name
        self.status = "pending"
        self.detail = ""
        self.fix = ""

    def ok(self, detail: str = "") -> "Check":
        self.status = "ok"
        self.detail = detail
        return self

    def warn(self, detail: str, fix: str = "") -> "Check":
        self.status = "warn"
        self.detail = detail
        self.fix = fix
        return self

    def fail(self, detail: str, fix: str) -> "Check":
        self.status = "fail"
        self.detail = detail
        self.fix = fix
        return self

    def render(self) -> None:
        tag = {"ok": _OK, "warn": _WARN, "fail": _FAIL}[self.status]
        line = f"{tag} {self.name}"
        if self.detail:
            line += f" -- {self.detail}"
        print(line)
        if self.fix and self.status != "ok":
            for fl in self.fix.splitlines():
                print(f"         -> {fl}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "fix": self.fix,
        }


def _get(url: str, token: str | None = None, timeout: float = 5.0):
    """GET a URL, returning (status_code, parsed_json_or_text).

    urllib raises HTTPError for 4xx/5xx -- a URLError subclass -- so a 401 would
    otherwise surface as a connection error. Catch it and return the code, so
    the caller can tell "token rejected" from "backend down".
    """
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            code = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        code = exc.code
    try:
        return code, json.loads(body)
    except json.JSONDecodeError:
        return code, body


# --- the checks, in the order they would break a validation -----------------


def check_env(base_url: str) -> list[Check]:
    out = []

    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    c = Check("paired-device token (MODELRIG_TOKEN)")
    if token:
        out.append(c.ok(f"set ({len(token)} chars)"))
    else:
        out.append(c.fail(
            "not set",
            "Set a paired-device token in the environment (do NOT type it on the\n"
            "command line so it does not land in shell history):\n"
            '  $env:MODELRIG_TOKEN = "<your paired-device token>"',
        ))

    planner = os.environ.get("KALIV_AGENT3_PLANNER_MODEL", "").strip()
    c = Check("planner model (KALIV_AGENT3_PLANNER_MODEL)")
    if planner:
        out.append(c.ok(planner))
    else:
        out.append(c.fail(
            "not set",
            "Choose the model Agent 3 plans with, e.g.:\n"
            '  $env:KALIV_AGENT3_PLANNER_MODEL = "qwen3:14b"',
        ))

    report = os.environ.get("KALIV_AGENT3_VALIDATION_REPORT", "").strip()
    c = Check("report path wired for the worker (KALIV_AGENT3_VALIDATION_REPORT)")
    if report:
        out.append(c.ok(report))
    else:
        out.append(c.warn(
            "not set in THIS shell",
            "The worker reads its report path from this variable AT STARTUP. It is\n"
            "the single most common reason validation fails: the evidence gets\n"
            "written, but the running worker was started without the path and\n"
            "cannot see it. Before starting the worker, set:\n"
            '  $env:KALIV_AGENT3_VALIDATION_REPORT = '
            '"<repo>\\validation\\agent3-rig-validation-latest.json"\n'
            "The status check below proves whether the RUNNING worker actually has it.",
        ))
    return out, token


def check_backend(base_url: str) -> tuple[list[Check], bool]:
    out = []
    base = base_url.rstrip("/")

    c = Check(f"backend reachable ({base}/healthz)")
    reachable = False
    try:
        status, _ = _get(f"{base}/healthz")
        if status == 200:
            out.append(c.ok("200"))
            reachable = True
        else:
            out.append(c.fail(
                f"HTTP {status}",
                "The backend answered but not with 200. Check the server log; it may\n"
                "be starting, or bound to a different port than the one probed.",
            ))
    except urllib.error.URLError as exc:
        out.append(c.fail(
            f"cannot connect ({exc.reason})",
            "The Go backend is not answering on this address. Start the appliance\n"
            "(scripts\\kaliv-autostart.ps1 keeps server+worker alive at logon), or\n"
            "pass the right address with --base-url. If you use Tailscale to reach\n"
            "the rig, use the Tailscale address here.",
        ))
    return out, reachable


def check_authed_status(base_url: str, token: str) -> tuple[list[Check], dict]:
    out = []
    base = base_url.rstrip("/")
    rig = {}

    if not token:
        out.append(Check("authenticated status").warn(
            "skipped -- no token",
            "Set MODELRIG_TOKEN (above) to run the checks that need auth.",
        ))
        return out, rig

    # 1. token works at all
    c = Check(f"token accepted ({base}/api/v1/status)")
    try:
        status, body = _get(f"{base}/api/v1/status", token=token)
        if status == 200:
            out.append(c.ok("200"))
        elif status in (401, 403):
            out.append(c.fail(
                f"HTTP {status} -- token rejected",
                "The token in MODELRIG_TOKEN is not accepted. Use a current\n"
                "paired-device token; a rotated or expired one fails here.",
            ))
            return out, rig
        else:
            out.append(c.warn(f"HTTP {status}", "Unexpected status; check the server log."))
    except urllib.error.URLError as exc:
        out.append(c.fail(f"cannot connect ({exc.reason})",
                          "Backend went away between checks; re-run once it is up."))
        return out, rig

    # 2. the agent3 status endpoint and its rig_validation block
    c = Check("Agent 3 status endpoint (/experimental/agent3/status)")
    try:
        status, body = _get(f"{base}/api/v1/experimental/agent3/status", token=token)
        if status != 200 or not isinstance(body, dict):
            out.append(c.fail(
                f"HTTP {status}",
                "The worker did not return an Agent 3 status. Backend or worker is\n"
                "not the expected build, or the worker is not up on :8099.",
            ))
            return out, rig
        out.append(c.ok("200"))
    except urllib.error.URLError as exc:
        out.append(c.fail(f"cannot reach the worker via the backend ({exc.reason})",
                          "The backend is up but cannot reach the worker on :8099.\n"
                          "Start the worker, or check the worker log."))
        return out, rig

    # 3. the rig can identify what it ran (code_sha256) -- the F-508/F-607 binding
    code_sha = body.get("code_sha256")
    c = Check("rig reports code identity (code_sha256)")
    if isinstance(code_sha, str) and len(code_sha) == 64:
        out.append(c.ok(code_sha[:16] + "..."))
    else:
        out.append(c.fail(
            f"missing or malformed ({code_sha!r})",
            "The worker cannot say what code it is running, so the validation\n"
            "cannot bind evidence to this build. This is an unexpected build.",
        ))

    # 4. production_activation must be false, always
    c = Check("production_activation is false")
    if body.get("production_activation") is False:
        out.append(c.ok("false"))
    else:
        out.append(c.fail(
            f"is {body.get('production_activation')!r} -- must be false",
            "Safety invariant broken: status must never report production active.\n"
            "Do not proceed; this build is not the expected one.",
        ))

    rig = body.get("rig_validation") or {}
    return out, rig


def check_report_state(rig: dict) -> list[Check]:
    """Interpret the worker's own view of the report -- the crux of the run."""
    out = []
    if not rig:
        out.append(Check("worker's report view (rig_validation)").warn(
            "not available -- earlier check failed",
            "Fix the failures above first; this depends on them.",
        ))
        return out

    configured = rig.get("configured")
    present = rig.get("present")
    reasons = ", ".join(rig.get("reasons") or []) or "(none)"

    c = Check("worker was STARTED with the report path (rig_validation.configured)")
    if configured is True:
        out.append(c.ok("configured"))
    else:
        out.append(c.warn(
            "worker has no report path",
            "This is expected BEFORE the first validation run: the worker has not\n"
            "been started with KALIV_AGENT3_VALIDATION_REPORT. Set that variable,\n"
            "restart the worker, then run the validation. If you already did and\n"
            "still see this, the worker process predates the variable -- restart it.",
        ))
        return out  # nothing below is meaningful until configured

    c = Check("worker can SEE a report at its path (rig_validation.present)")
    if present is True:
        sha = rig.get("report_sha256")
        out.append(c.ok(f"present (sha {sha[:16]}...)" if sha else "present"))
    else:
        out.append(c.warn(
            f"no report yet at the configured path (reasons: {reasons})",
            "Expected before the first run -- the validation writes the report.\n"
            "After a successful run this becomes present. Nothing to fix now.",
        ))
        return out

    # If a report is already present, report whether the gate accepts it.
    c = Check("promotion gate accepts the existing report")
    if rig.get("eligible_for_developer_preview") is True:
        level = "write-pilot" if rig.get("eligible_for_write_pilot") is True else "developer-preview"
        out.append(c.ok(f"eligible ({level})"))
    else:
        out.append(c.warn(
            f"a report is present but the gate rejected it (reasons: {reasons})",
            "A prior run left a report the gate does not accept -- usually because\n"
            "the code changed since (version or code_sha256 mismatch). Re-run the\n"
            "validation against the current build.",
        ))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url",
                    default=os.environ.get("MODELRIG_BASE_URL", "http://127.0.0.1:8080"),
                    help="backend base URL (default: env MODELRIG_BASE_URL or "
                         "http://127.0.0.1:8080)")
    ap.add_argument(
        "--report",
        type=Path,
        help="optional atomic JSON report for the physical campaign",
    )
    args = ap.parse_args(argv)

    print()
    print("  Rig preflight -- is the rig ready to validate?")
    print(f"  backend: {args.base_url}")
    print("  " + "-" * 60)

    checks: list[Check] = []

    env_checks, token = check_env(args.base_url)
    checks += env_checks

    backend_checks, reachable = check_backend(args.base_url)
    checks += backend_checks

    rig = {}
    if reachable:
        status_checks, rig = check_authed_status(args.base_url, token)
        checks += status_checks
        checks += check_report_state(rig)
        # The substrate the validation runs THROUGH -- Ollama, planner model,
        # disk, ASR device -- not just the Agent 3 handshake (F-919 controlled run).
        from rig_preflight_substrate import check_substrate
        planner = os.environ.get("KALIV_AGENT3_PLANNER_MODEL", "").strip()
        checks += check_substrate(_get, Check, args.base_url, token, planner)
    else:
        checks.append(Check("authenticated + report checks").warn(
            "skipped -- backend not reachable",
            "Bring the backend up, then re-run.",
        ))

    print()
    for c in checks:
        c.render()
    print("  " + "-" * 60)

    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]

    # A report already present and accepted means validation has run and passed.
    already_valid = rig.get("eligible_for_developer_preview") is True
    ready = not fails
    if args.report is not None:
        report = {
            "schema": PREFLIGHT_SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate": _candidate_identity(),
            "backend": {"base_url": args.base_url},
            "ready": ready,
            "already_validated": already_valid,
            "summary": {
                "checks": len(checks),
                "ok": sum(c.status == "ok" for c in checks),
                "warnings": len(warns),
                "failures": len(fails),
            },
            "checks": [c.to_dict() for c in checks],
        }
        _write_json_atomic(args.report, report)
        print(f"  report: {args.report}")

    if fails:
        print(f"  NOT READY -- {len(fails)} blocker(s) above must be fixed first.")
        print("  Fix them, then run this again. Nothing was changed.")
        return 1
    if already_valid:
        print("  ALREADY VALIDATED -- the worker sees an accepted report.")
        print("  Re-run the validation only if the build changed since.")
        return 0
    if warns:
        print(f"  READY TO VALIDATE -- {len(warns)} expected pre-run note(s) above.")
        print("  Every hard dependency is up. Now run the real validation:")
        print("    powershell -File scripts\\run-agent3-rig-validation.ps1")
        print("  (the warnings above are the normal 'no report yet' state)")
        return 0
    print("  READY TO VALIDATE -- every dependency is up.")
    print("    powershell -File scripts\\run-agent3-rig-validation.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
